"""Tool-free OpenAI-compatible committee execution with disk caching."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from math import ceil
from pathlib import Path
from typing import Any

import requests

from .aggregate import BallotError, aggregate_ballots, parse_ballot, validate_ballot
from .config import Config, provider_from_environment
from .lint import lint_packet
from .packet import default_packet_path, digest, read_packet
from .personas import committee_mix, mixes
from .prompts import CONDITIONS, system_prompt, user_prompt


class RunError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def seed_label(seed: float) -> str:
    return format(seed, "g")


def run_key(mix: str, condition: str, seed: float) -> str:
    return f"{mix}|{condition}|{seed_label(seed)}"


def run_artifact_dir(base: Path, aggregates: dict[str, Any]) -> Path:
    """Locate the raw calls for an aggregate, including pre-compaction runs."""
    if "artifact_dir" not in aggregates:
        return base
    relative = Path(aggregates["artifact_dir"])
    if (len(relative.parts) != 2 or relative.parts[0] != "experiments"
            or len(relative.name) != 64 or any(c not in "0123456789abcdef" for c in relative.name)):
        raise ValueError(f"Invalid run artifact directory: {relative}")
    return base / relative


def _raw_path(base: Path, mix: str, condition: str, seed: float, agent_id: str) -> Path:
    return base / "raw" / mix / condition / seed_label(seed) / f"{agent_id}.json"


def _ballot_path(base: Path, mix: str, condition: str, seed: float, agent_id: str) -> Path:
    return base / "ballots" / mix / condition / seed_label(seed) / f"{agent_id}.json"


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def estimate(
    config: Config,
    packet: dict[str, Any],
    mix_names: tuple[str, ...] | None = None,
    condition_names: tuple[str, ...] | None = None,
    seeds: tuple[float, ...] | None = None,
) -> dict[str, float | int]:
    longest_system = max(
        (system_prompt(member) for mix in (mix_names or mixes()) for member in committee_mix(mix)),
        key=lambda prompt: len(prompt.encode("utf-8")),
    )
    longest_user = max(
        (user_prompt(packet, condition) for condition in (condition_names or tuple(CONDITIONS))),
        key=lambda prompt: len(prompt.encode("utf-8")),
    )
    # Compact score rows are token-dense. The real frozen packet measured
    # about 2.78 UTF-8 bytes per token with o200k_base; round conservatively.
    input_per_call = ceil(len((longest_system + "\n" + longest_user).encode("utf-8")) / 2.7)
    calls = len(mix_names or mixes()) * len(condition_names or tuple(CONDITIONS)) * len(seeds or config.temperature_seeds) * 13
    input_tokens = input_per_call * calls
    output_tokens = config.assumed_output_tokens * calls
    cost = (input_tokens * config.pricing_usd_per_million["input"] + output_tokens * config.pricing_usd_per_million["output"]) / 1_000_000
    return {
        "calls": calls,
        "sample_input_tokens_per_call": input_per_call,
        "estimated_input_tokens": input_tokens,
        "estimated_output_tokens": output_tokens,
        "estimated_usd": round(cost, 4),
        "max_budget_usd": config.max_budget_usd,
    }


class ChatClient:
    def __init__(self, config: Config):
        self.provider, self.base_url, self.key = provider_from_environment()
        self.config = config

    def complete(self, system: str, user: str, temperature: float) -> tuple[str, dict[str, Any]]:
        # The payload intentionally contains no tools, search, function-calling, retrieval, or browsing parameters.
        payload = {
            "model": self.config.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": temperature,
        }
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"},
                json=payload,
                timeout=self.config.timeout_s,
            )
        except requests.RequestException as exc:
            raise RunError(f"{self.provider} chat completion failed: {exc}") from exc
        if response.status_code >= 400:
            raise RunError(f"{self.provider} chat completion HTTP {response.status_code}: {response.text[:500]}")
        try:
            result = response.json()
            content = result["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise RunError(f"{self.provider} response lacked choices[0].message.content") from exc
        if not isinstance(content, str):
            raise RunError(f"{self.provider} response content was not text")
        return content, result.get("usage") or {}


def _cached_ballot(path: Path, candidates: list[str], agent_id: str, persona: str) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        ballot = _read_json(path)
        validate_ballot(ballot, candidates, agent_id, persona)
        return ballot
    except (OSError, ValueError, BallotError):
        return None


def _run_one(
    client: ChatClient, config: Config, packet: dict[str, Any], base: Path, mix: str, condition: str, seed: float, member: Any,
) -> tuple[dict[str, Any] | None, int, list[dict[str, Any]]]:
    candidates = packet["candidates"]
    ballot_file = _ballot_path(base, mix, condition, seed, member.agent_id)
    if ballot := _cached_ballot(ballot_file, candidates, member.agent_id, member.persona):
        return ballot, 0, []
    raw_file = _raw_path(base, mix, condition, seed, member.agent_id)
    state: dict[str, Any] = {"attempts": []}
    if raw_file.exists():
        try:
            state = _read_json(raw_file)
        except (OSError, ValueError):
            state = {"attempts": []}
    attempts = list(state.get("attempts", []))
    system, user = system_prompt(member), user_prompt(packet, condition)
    failures: list[dict[str, Any]] = []
    for attempt in attempts:
        try:
            ballot = parse_ballot(attempt["content"])
            validate_ballot(ballot, candidates, member.agent_id, member.persona)
            _write_json(ballot_file, ballot)
            return ballot, 0, failures
        except (KeyError, BallotError) as exc:
            failures.append({"agent_id": member.agent_id, "attempt": attempt.get("number"), "error": str(exc)})
    calls = 0
    while len(attempts) < config.max_retries:
        calls += 1
        try:
            content, usage = client.complete(system, user, seed)
            attempt = {"number": len(attempts) + 1, "at_utc": utc_now(), "content": content, "usage": usage}
        except RunError as exc:
            attempt = {"number": len(attempts) + 1, "at_utc": utc_now(), "error": str(exc), "content": "", "usage": {}}
        attempts.append(attempt)
        state["attempts"] = attempts
        _write_json(raw_file, state)
        if not attempt["content"]:
            failures.append({"agent_id": member.agent_id, "attempt": attempt["number"], "error": attempt.get("error", "empty response")})
            continue
        try:
            ballot = parse_ballot(attempt["content"])
            validate_ballot(ballot, candidates, member.agent_id, member.persona)
        except BallotError as exc:
            failures.append({"agent_id": member.agent_id, "attempt": attempt["number"], "error": str(exc)})
            continue
        _write_json(ballot_file, ballot)
        return ballot, calls, failures
    return None, calls, failures


def run_committee(
    config: Config,
    packet_path: str | Path | None = None,
    mix_names: tuple[str, ...] | None = None,
    condition_names: tuple[str, ...] | None = None,
    seeds: tuple[float, ...] | None = None,
) -> dict[str, Any]:
    path = Path(packet_path or default_packet_path(config.release_id))
    lint_packet(path, config)
    packet = read_packet(path)
    selected_mixes = mix_names or mixes()
    selected_conditions = condition_names or tuple(CONDITIONS)
    selected_seeds = seeds or config.temperature_seeds
    unknown_mixes = set(selected_mixes) - set(mixes())
    unknown_conditions = set(selected_conditions) - set(CONDITIONS)
    if unknown_mixes or unknown_conditions:
        raise RunError(f"Unknown experiment scope: mixes={sorted(unknown_mixes)}, conditions={sorted(unknown_conditions)}")
    cost_estimate = estimate(config, packet, selected_mixes, selected_conditions, selected_seeds)
    if float(cost_estimate["estimated_usd"]) > config.max_budget_usd:
        raise RunError(
            f"Estimated ${cost_estimate['estimated_usd']:.2f} exceeds max_budget_usd ${config.max_budget_usd:.2f}; "
            "raise max_budget_usd in config.yaml to proceed. No model calls were made."
        )
    client = ChatClient(config)
    packet_hash = sha256(path.read_bytes()).hexdigest()
    # Never reuse a cached ballot generated from different evidence, prompts, or a different model.
    identity = digest({
        "packet_sha256": packet_hash,
        "provider": client.provider,
        "model": config.model,
        "user_prompts": {name: user_prompt(packet, name) for name in CONDITIONS},
        "system_prompts": {
            mix: [system_prompt(member) for member in committee_mix(mix)] for mix in mixes()
        },
    })
    artifact_dir = f"experiments/{identity}"
    base = run_artifact_dir(config.ballot_dir, {"artifact_dir": artifact_dir})
    base.mkdir(parents=True, exist_ok=True)
    metadata_file = base / "run_metadata.json"
    metadata = _read_json(metadata_file) if metadata_file.exists() else {"first_call_utc": None, "failures": [], "actual_usage": {"input_tokens": 0, "output_tokens": 0}}
    all_runs: dict[str, Any] = {}
    for mix in selected_mixes:
        for condition in selected_conditions:
            for seed in selected_seeds:
                ballots: list[dict[str, Any]] = []
                failures: list[dict[str, Any]] = []
                for member in committee_mix(mix):
                    ballot, calls, member_failures = _run_one(client, config, packet, base, mix, condition, seed, member)
                    if calls and metadata.get("first_call_utc") is None:
                        metadata["first_call_utc"] = utc_now()
                    failures.extend(member_failures)
                    if ballot is not None:
                        ballots.append(ballot)
                metadata["failures"].extend(failures)
                if len(ballots) < 10:
                    metadata["last_call_utc"] = utc_now()
                    _write_json(metadata_file, metadata)
                    raise RunError(f"{mix}/{condition}/{seed_label(seed)} has only {len(ballots)} valid ballots; aborting (minimum is 10).")
                all_runs[run_key(mix, condition, seed)] = aggregate_ballots(ballots, packet["candidates"], packet.get("ratings", {}).get("sp_plus") or {})
    metadata["last_call_utc"] = utc_now()
    usage = {"input_tokens": 0, "output_tokens": 0}
    for raw in (base / "raw").glob("**/*.json"):
        for item in _read_json(raw).get("attempts", []):
            item_usage = item.get("usage") or {}
            usage["input_tokens"] += int(item_usage.get("prompt_tokens", 0) or 0)
            usage["output_tokens"] += int(item_usage.get("completion_tokens", 0) or 0)
    metadata["actual_usage"] = usage
    price = config.pricing_usd_per_million
    metadata["actual_cost_usd"] = round((usage["input_tokens"] * price["input"] + usage["output_tokens"] * price["output"]) / 1_000_000, 6)
    _write_json(metadata_file, metadata)
    result = {
        "release_id": config.release_id,
        "packet_sha256": packet_hash,
        "provider": client.provider,
        "model": config.model,
        "artifact_dir": artifact_dir,
        "generated_at_utc": utc_now(),
        "scope": {"mixes": list(selected_mixes), "conditions": list(selected_conditions), "seeds": list(selected_seeds)},
        "runs": all_runs,
        "estimate": cost_estimate,
    }
    _write_json(config.ballot_dir / "aggregates.json", result)
    return result
