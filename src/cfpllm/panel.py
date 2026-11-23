"""Run the weekly six-model OpenRouter panel with a persistent spend ledger."""

from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from threading import Lock
from zoneinfo import ZoneInfo

import requests

from .aggregate import aggregate_ballots, parse_ballot, validate_ballot
from .config import load_config
from .lint import lint_packet
from .packet import read_packet
from .personas import DEFAULT_WEEKLY_PROFILE, WEEKLY_PROFILES, weekly_committee
from .prompts import CONDITIONS, system_prompt, user_prompt

# Model ID, provider allowlist, effort, USD per million input/output tokens.
MODELS = {
    "luna": ("openai/gpt-6-luna", ["openai"], "none", .10, .50),
    "haiku": ("anthropic/claude-haiku-5.5", ["anthropic"], "none", .10, .50),
    "gemini": ("google/gemini-3.8-flash", ["google-ai-studio/flex", "google-vertex/global/flex"], "low", .375, 1.875),
    "deepseek": ("deepseek/deepseek-v4.1-flash-1017", ["siliconflow/fp8", "deepseek", "coreweave/fp8"], "none", .30, 1.20),
    "glm": ("z-ai/glm-5.3-flash", ["deepinfra/fp4", "novita/fp8", "siliconflow/fp8", "coreweave", "together"], "low", .37, 1.25),
    "minimax": ("minimax/minimax-m3.1-flash", ["fireworks", "digitalocean", "together"], "low", .15, .60),
}
BUDGET = 15.0
MAX_OUTPUT = 5000
MAX_ATTEMPTS = 3


def stamp():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def plan(profile: str = DEFAULT_WEEKLY_PROFILE):
    members = weekly_committee(profile)
    mixed_models = ("luna", "haiku", "gemini", "deepseek", "glm", "minimax",
                    "minimax", "glm", "deepseek", "gemini", "haiku", "luna", "glm")
    for variant in (*MODELS, "mixed"):
        for condition in CONDITIONS:
            for temperature in ((0.3, 0.7) if variant == "mixed" else (0.3,)):
                group = f"{variant}|{condition}|{temperature:g}"
                for index, member in enumerate(members):
                    model = mixed_models[index] if variant == "mixed" else variant
                    yield group, condition, temperature, member, model


def normalize_ballot(content, candidates, member):
    parsed = parse_ballot(content)
    if parsed.get("agent_id") is None:
        parsed["agent_id"] = member.agent_id
    if parsed.get("persona") is None:
        parsed["persona"] = member.persona
    if isinstance(parsed.get("rationales"), list):
        parsed["rationales"] = dict(zip(parsed["ranking"][:12], parsed["rationales"][:12], strict=True))
    elif isinstance(parsed.get("rationales"), dict):
        parsed["rationales"] = {team: parsed["rationales"][team] for team in parsed["ranking"][:12]
                                if team in parsed["rationales"]}
    validate_ballot(parsed, candidates, member.agent_id, member.persona)
    return {field: parsed[field] for field in ("agent_id", "persona", "ranking", "rationales")}


def main(argv=None):
    parser = ArgumentParser(description="Run the six-model weekly CFP panel.")
    parser.add_argument("--profile", choices=WEEKLY_PROFILES, default=DEFAULT_WEEKLY_PROFILE,
                        help="Committee roster version (default: %(default)s).")
    args = parser.parse_args(argv)
    key = os.environ["OPENROUTER_API_KEY"]
    config = load_config()
    output_dir = "weekly-panel" if args.profile == "weekly-v1" else "weekly-panel-v2"
    root = config.ballot_dir / output_dir
    packet_file = config.packet_dir / "packet.json"
    lint_packet(packet_file, config)
    packet = read_packet(packet_file)
    packet_hash = sha256(packet_file.read_bytes()).hexdigest()
    expected = list(plan(args.profile))
    deadline = datetime.fromisoformat(f"{config.release_id}T16:00:00").replace(tzinfo=ZoneInfo("America/New_York"))
    if datetime.now(timezone.utc) >= deadline:
        raise SystemExit("The pre-release lock deadline has passed.")
    prompts = {condition: user_prompt(packet, condition) for condition in CONDITIONS}
    experiment = {
        "release_id": config.release_id, "packet_sha256": packet_hash, "lock_deadline": deadline.isoformat(),
        "requested_ballots": len(expected), "max_model_cost_usd": BUDGET,
        "model_settings": {name: dict(zip(("id", "providers", "reasoning_effort", "max_input_per_m", "max_output_per_m"), values))
                           for name, values in MODELS.items()},
        "conditions": CONDITIONS, "max_attempts_per_ballot": MAX_ATTEMPTS, "max_output_tokens": MAX_OUTPUT,
        "system_prompts": {member.agent_id: system_prompt(member, ordered_rationales=True)
                           for member in weekly_committee(args.profile)},
        "user_prompt_sha256": {name: sha256(prompt.encode()).hexdigest() for name, prompt in prompts.items()},
        "output_schema": "Top 25 canonical names; array of 12 ordered rationales normalized to team-keyed strings.",
        "profile": args.profile,
    }
    manifest_file = root / "experiment.json"
    if manifest_file.exists():
        original = json.loads(manifest_file.read_text())
        fixed = set(experiment) - {"model_settings"}
        if any(original.get(k) != experiment[k] for k in fixed):
            raise SystemExit("Existing weekly artifacts use a different packet or configuration.")
        if original["model_settings"] != experiment["model_settings"]:
            previous = original["model_settings"]
            changes = [model for model in MODELS if previous.get(model) != experiment["model_settings"][model]]
            if changes != ["glm"] or previous["glm"]["id"] != "z-ai/glm-5.3-flashx":
                raise SystemExit("Existing weekly artifacts use a different model configuration.")
            original["routing_changes"] = [{
                "from": previous["glm"]["id"], "to": experiment["model_settings"]["glm"]["id"],
                "reason": "OpenRouter zero-data-retention account settings excluded the FlashX endpoint.",
                "at_utc": stamp(),
            }]
            original["model_settings"] = experiment["model_settings"]
            save(manifest_file, original)
        experiment = original
    else:
        experiment["started_at_utc"] = stamp()
        save(manifest_file, experiment)
    candidates = packet["candidates"]
    budget_lock = Lock()
    accounted = sum(a.get("accounted_usd", 0) for path in (root / "calls").glob("*/*.json")
                    for a in json.loads(path.read_text()))

    def collect(case, one_attempt=False):
        nonlocal accounted
        group, condition, temperature, member, model = case
        model_id, providers, effort, price_in, price_out = MODELS[model]
        raw_path = root / "calls" / group / f"{member.agent_id}.json"
        result_path = root / "ballots" / group / f"{member.agent_id}.json"
        if result_path.exists():
            ballot = json.loads(result_path.read_text())
            validate_ballot(ballot, candidates, member.agent_id, member.persona)
            return case, ballot, []
        attempts = json.loads(raw_path.read_text()) if raw_path.exists() else []
        for attempt in reversed(attempts):
            if attempt.get("model") != model_id or not attempt.get("content"):
                continue
            try:
                ballot = normalize_ballot(attempt["content"], candidates, member)
            except (ValueError, TypeError, KeyError, IndexError):
                continue
            save(result_path, ballot)
            return case, ballot, attempts
        system = experiment["system_prompts"][member.agent_id]
        user = prompts[condition]
        # A byte-per-token bound, with chat framing and cache-write headroom.
        reserved = ((len(system.encode()) + len(user.encode()) + 2048) * price_in * 1.5
                    + MAX_OUTPUT * price_out) / 1_000_000
        sent = sum(attempt["model"] == model_id for attempt in attempts)
        remaining = min(1, MAX_ATTEMPTS - sent) if one_attempt else MAX_ATTEMPTS - sent
        for number in range(len(attempts) + 1, len(attempts) + remaining + 1):
            with budget_lock:
                if accounted + reserved > BUDGET or datetime.now(timezone.utc) >= deadline:
                    return case, None, ["budget or deadline reached"]
                accounted += reserved
            attempt = {"attempt": number, "model": model_id, "requested_temperature": temperature,
                       "started_at_utc": stamp(), "accounted_usd": reserved}
            attempts.append(attempt)
            save(raw_path, attempts)  # reservation survives interruption
            ballot = None
            try:
                payload = {
                    "model": model_id, "max_tokens": MAX_OUTPUT, "temperature": temperature,
                    "reasoning": {"effort": effort, "exclude": True},
                    "response_format": {"type": "json_object"},
                    "provider": {"only": providers, "allow_fallbacks": len(providers) > 1,
                                 "max_price": {"prompt": price_in, "completion": price_out}},
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                }
                if model in ("luna", "haiku"):
                    # These routes omit temperature from advertised capabilities.
                    payload.pop("temperature")
                    attempt["requested_temperature"] = None
                response = requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    json=payload, headers={"Authorization": f"Bearer {key}"}, timeout=(10, 105),
                )
                body = response.json()
                attempt.update(http_status=response.status_code, usage=body.get("usage") or {},
                               completion_id=body.get("id"), provider=body.get("provider"))
                if not response.ok or "error" in body:
                    if response.status_code < 500 and not body.get("id"):
                        attempt["accounted_usd"] = 0.0
                    raise ValueError(str(body.get("error", {}).get("message", "API error")))
                if attempt["usage"].get("cost") is not None:
                    attempt["accounted_usd"] = float(attempt["usage"]["cost"])
                choice = body["choices"][0]
                attempt["finish_reason"] = choice.get("finish_reason")
                attempt["content"] = choice["message"]["content"]
                ballot = normalize_ballot(attempt["content"] or "", candidates, member)
            except (requests.RequestException, ValueError, TypeError, KeyError, IndexError) as exc:
                attempt["error"] = str(exc).replace(key, "[redacted]")[:280]
            attempt["finished_at_utc"] = stamp()
            save(raw_path, attempts)
            with budget_lock:
                accounted += attempt["accounted_usd"] - reserved
            if ballot is not None:
                save(result_path, ballot)
                return case, ballot, attempts
            if attempt.get("http_status") in {401, 402, 403, 404}:
                break
        return case, None, attempts

    smoke = [next(case for case in expected if case[-1] == name) for name in MODELS]
    with ThreadPoolExecutor(max_workers=6) as pool:
        for case, ballot, attempts in pool.map(lambda case: collect(case, one_attempt=True), smoke):
            detail = "" if ballot or not attempts else str(attempts[-1])[:420]
            print("Preflight", case[-1], "valid" if ballot else detail, flush=True)
    completed = {}
    with ThreadPoolExecutor(max_workers=30) as pool:
        futures = [pool.submit(collect, case) for case in expected]
        for index, future in enumerate(as_completed(futures), 1):
            case, result, _ = future.result()
            if result:
                completed.setdefault(case[0], []).append((case[-1], result))
            if index % 16 == 0:
                print(f"{index}/{len(futures)} seats processed, {sum(map(len, completed.values()))} valid, ${accounted:.2f} accounted", flush=True)

    counts = {group: len(completed.get(group, ())) for group, *_ in expected}
    ballots = [dict(ballot, model=model, group=group) for group, rows in sorted(completed.items())
               for model, ballot in sorted(rows, key=lambda row: row[1]["agent_id"])]
    aggregates = {
        group: aggregate_ballots([ballot for _, ballot in rows], candidates, packet["ratings"].get("sp_plus"))
        for group, rows in sorted(completed.items()) if len(rows) >= 10
    }
    call_log = [dict(attempt, group=path.parent.name, agent_id=path.stem)
                for path in sorted((root / "calls").glob("*/*.json"))
                for attempt in json.loads(path.read_text())]
    result = {
        **experiment, "finished_at_utc": stamp(), "valid_by_group": counts,
        "valid_ballots": len(ballots), "attempted_calls": len(call_log),
        "cost_usd": round(sum(float(call["usage"]["cost"]) for call in call_log
                              if call.get("usage", {}).get("cost") is not None), 6),
        "accounted_usd": round(accounted, 6), "runs": aggregates,
        "official_status": "pending_release",
        "ballot_normalization": "Use seat metadata for omitted labels and retain the first 12 supplied rationales. Validate original ranking names, order, length and uniqueness.",
    }
    save(root / "aggregates.json", result)
    save(root / "valid-ballots.json", ballots)
    save(root / "usage.json", [{key: value for key, value in call.items() if key not in {"content", "error", "completion_id"}} for call in call_log])
    print(f"Complete: {len(ballots)} valid of {len(expected)} seats, {len(aggregates)}/{len(counts)} qualifying groups, ${result['cost_usd']:.4f} provider-reported.", flush=True)


if __name__ == "__main__":
    main()
