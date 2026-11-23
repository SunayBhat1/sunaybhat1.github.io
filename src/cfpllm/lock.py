"""Manifest creation and optional Git timestamp proof for a fully completed run."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from typing import Any

from .config import Config, provider_from_environment
from .lint import lint_packet
from .packet import default_packet_path, read_packet
from .personas import mix_map, mixes
from .prompts import CONDITIONS
from .run import _read_json, _write_json, run_artifact_dir, run_key


class LockError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _source_hash(path: str) -> str:
    return sha256(Path(path).read_bytes()).hexdigest()


def _usage_from_raw(base: Path) -> dict[str, int]:
    total = {"input_tokens": 0, "output_tokens": 0}
    for path in (base / "raw").glob("**/*.json") if (base / "raw").exists() else []:
        try:
            for attempt in _read_json(path).get("attempts", []):
                usage = attempt.get("usage") or {}
                total["input_tokens"] += int(usage.get("prompt_tokens", 0) or 0)
                total["output_tokens"] += int(usage.get("completion_tokens", 0) or 0)
        except (OSError, ValueError):
            continue
    return total


def write_manifest(config: Config, packet_path: str | Path | None = None) -> tuple[Path, dict[str, Any]]:
    packet_file = Path(packet_path or default_packet_path(config.release_id))
    lint_packet(packet_file, config)
    aggregate_file = config.ballot_dir / "aggregates.json"
    if not aggregate_file.exists():
        raise LockError("No aggregates.json exists; run the committee successfully before locking.")
    aggregates = _read_json(aggregate_file)
    expected = {run_key(mix, condition, seed) for mix in mixes() for condition in CONDITIONS for seed in config.temperature_seeds}
    missing = sorted(expected - set(aggregates.get("runs", {})))
    if missing:
        raise LockError("Cannot lock an incomplete run; missing aggregates: " + ", ".join(missing))
    weak = [key for key, value in aggregates["runs"].items() if int(value.get("valid_ballots", 0)) < 10]
    if weak:
        raise LockError("Cannot lock runs with fewer than 10 valid ballots: " + ", ".join(weak))
    packet = read_packet(packet_file)
    packet_hash = packet_file.with_name("packet.sha256").read_text(encoding="ascii").strip().split()[0]
    if aggregates.get("packet_sha256", packet_hash) != packet_hash:
        raise LockError("The aggregates were generated from a different frozen packet.")
    source_dir = run_artifact_dir(config.ballot_dir, aggregates)
    metadata_path = source_dir / "run_metadata.json"
    metadata = _read_json(metadata_path) if metadata_path.exists() else {}
    try:
        provider, _, _ = provider_from_environment()
    except RuntimeError:
        provider = "unknown (key absent while locking)"
    usage = _usage_from_raw(source_dir)
    costs = config.pricing_usd_per_million
    manifest = {
        "release_id": config.release_id,
        "packet_sha256": packet_hash,
        "lock_tag": f"lock/{config.release_id}-{packet_hash[:8]}",
        "games_through": config.games_through,
        "prior_cfp_release": config.prior_cfp_release,
        "model": aggregates.get("model", config.model),
        "provider": aggregates.get("provider", provider),
        "prompt_templates": {
            "paths": ["src/cfpllm/prompts.py", "src/cfpllm/personas.py"],
            "sha256": {"src/cfpllm/prompts.py": _source_hash("src/cfpllm/prompts.py"), "src/cfpllm/personas.py": _source_hash("src/cfpllm/personas.py")},
        },
        "persona_mix_maps": mix_map(),
        "condition_definitions": CONDITIONS,
        "temperatures_seeds": list(config.temperature_seeds),
        "timestamps_utc": {
            "fetch": packet.get("meta", {}).get("fetched_at_utc"),
            "first_call": metadata.get("first_call_utc"),
            "last_call": metadata.get("last_call_utc"),
            "lock": _utc_now(),
        },
        "agent_failures": metadata.get("failures", []),
        "token_totals": usage,
        "estimated_cost_usd": round((usage["input_tokens"] * costs["input"] + usage["output_tokens"] * costs["output"]) / 1_000_000, 6),
        "tie_break": "higher SP+ where present, then alphabetical",
    }
    target = config.ballot_dir / "manifest.json"
    if "artifact_dir" in aggregates:
        manifest["artifact_dir"] = aggregates["artifact_dir"]
    _write_json(target, manifest)
    return target, manifest


def _git(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], text=True, capture_output=True, check=False)


def git_lock(config: Config, packet_hash: str) -> str:
    """Commit, tag, and push exact artifacts. Raises with copy-paste recovery commands on failure."""
    tag = f"lock/{config.release_id}-{packet_hash[:8]}"
    aggregate_file = config.ballot_dir / "aggregates.json"
    source = run_artifact_dir(config.ballot_dir, _read_json(aggregate_file))
    source_paths = [source] if source != config.ballot_dir else [
        path for name in ("raw", "ballots", "run_metadata.json") if (path := source / name).exists()
    ]
    paths = [
        str(aggregate_file), str(config.ballot_dir / "manifest.json"),
        *(str(path) for path in source_paths),
        "config.yaml", "src/cfpllm/prompts.py", "src/cfpllm/personas.py",
    ]
    added = _git(["add", "--", *paths])
    if added.returncode:
        raise LockError(f"git add failed: {added.stderr.strip()}")
    changed = _git(["diff", "--cached", "--quiet"])
    if changed.returncode == 1:
        committed = _git(["commit", "-m", f"lock({config.release_id}): freeze packet {packet_hash[:12]} and committee ballots"])
        if committed.returncode:
            raise LockError(f"git commit failed: {committed.stderr.strip()}")
    elif changed.returncode != 0:
        raise LockError(f"git diff --cached failed: {changed.stderr.strip()}")
    exists = _git(["rev-parse", "-q", "--verify", f"refs/tags/{tag}"])
    if exists.returncode:
        tagged = _git(["tag", "-a", tag, "-m", f"CFP LLM lock for {config.release_id}; packet {packet_hash}"])
        if tagged.returncode:
            raise LockError(f"git tag failed: {tagged.stderr.strip()}")
    pushed_branch = _git(["push", "origin", "HEAD"])
    pushed_tag = _git(["push", "origin", tag])
    if pushed_branch.returncode or pushed_tag.returncode:
        details = (pushed_branch.stderr + "\n" + pushed_tag.stderr).strip()
        raise LockError(
            f"Artifacts were prepared locally but push failed: {details}\n"
            f"Run: git push origin HEAD\nRun: git push origin {tag}\n"
            "Do not claim the lock is complete until both commands succeed."
        )
    return tag
