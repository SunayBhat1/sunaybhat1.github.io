"""Run the weekly six-model OpenRouter panel with a persistent spend ledger."""

from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from threading import Condition
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
                    "minimax", "glm", "deepseek", "gemini", "haiku", "luna", "glm", "luna")
    variants = ("mixed",) if profile == "weekly-v3" else (*MODELS, "mixed")
    for variant in variants:
        for condition in CONDITIONS:
            for temperature in ((0.3, 0.7) if variant == "mixed" else (0.3,)):
                group = f"{variant}|{condition}|{temperature:g}"
                for index, member in enumerate(members):
                    model = mixed_models[index] if variant == "mixed" else variant
                    yield group, condition, temperature, member, model


def normalize_ballot(content, candidates, member, *, allow_search_preamble=False):
    if allow_search_preamble:
        first, separator, remainder = content.strip().partition("\n\n")
        if separator and len(first) <= 300 and "{" not in first and remainder.startswith(("{", "```")):
            content = remainder
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


def describe_models(names):
    fields = ("id", "providers", "reasoning_effort", "max_input_per_m", "max_output_per_m")
    return {name: dict(zip(fields, MODELS[name], strict=True)) for name in names}


def main(argv=None):
    parser = ArgumentParser(description="Run the six-model weekly CFP panel.")
    parser.add_argument("--profile", choices=WEEKLY_PROFILES, default=DEFAULT_WEEKLY_PROFILE,
                        help="Committee roster version (default: %(default)s).")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--budget", type=float, default=BUDGET, help="Maximum USD for this run.")
    args = parser.parse_args(argv)
    if not 0 < args.budget <= BUDGET:
        parser.error(f"--budget must be positive and no more than {BUDGET:g}.")
    config = load_config(args.config)
    output_dir = {"weekly-v1": "weekly-panel", "weekly-v2": "weekly-panel-v2", "weekly-v3": "weekly-panel-v3"}[args.profile]
    root = config.ballot_dir / output_dir
    packet_file = config.packet_dir / "packet.json"
    lint_packet(packet_file, config)
    packet = read_packet(packet_file)
    if args.profile == "weekly-v3" and (packet["meta"].get("resume_schema") != 2 or not packet.get("opening_spreads")):
        raise SystemExit("Weekly-v3 requires a dated résumé packet with opening spreads.")
    packet_hash = sha256(packet_file.read_bytes()).hexdigest()
    expected = list(plan(args.profile))
    deadline = datetime.fromisoformat(f"{config.release_id}T16:00:00").replace(tzinfo=ZoneInfo("America/New_York"))
    if datetime.now(timezone.utc) >= deadline:
        raise SystemExit("The pre-release lock deadline has passed.")
    prompts = {condition: user_prompt(packet, condition) for condition in CONDITIONS}
    experiment = {
        "release_id": config.release_id, "packet_sha256": packet_hash, "lock_deadline": deadline.isoformat(),
        "requested_ballots": len(expected), "max_model_cost_usd": args.budget,
        "model_settings": describe_models(MODELS),
        "conditions": CONDITIONS, "max_attempts_per_ballot": MAX_ATTEMPTS, "max_output_tokens": MAX_OUTPUT,
        "system_prompts": {member.agent_id: system_prompt(member, ordered_rationales=True,
                                                         reassess_polls=packet["meta"].get("resume_schema") == 2)
                           for member in weekly_committee(args.profile)},
        "user_prompt_sha256": {name: sha256(prompt.encode()).hexdigest() for name, prompt in prompts.items()},
        "output_schema": "Top 25 canonical names; array of 12 ordered rationales normalized to team-keyed strings.",
        "profile": args.profile,
    }
    run_panel(root, packet, expected, prompts, experiment)


def run_panel(root, packet, expected, prompts, experiment):
    """Collect and aggregate a planned set of OpenRouter ballots with a shared budget."""
    key = os.environ["OPENROUTER_API_KEY"]
    deadline = datetime.fromisoformat(experiment["lock_deadline"])
    budget = experiment["max_model_cost_usd"]
    max_output = experiment["max_output_tokens"]
    max_attempts = experiment["max_attempts_per_ballot"]
    models = experiment["model_settings"]
    searches = experiment.get("search_by_condition", {})
    concurrency = 4 if searches else 30
    if datetime.now(timezone.utc) >= deadline:
        raise SystemExit("The pre-release lock deadline has passed.")
    manifest_file = root / "experiment.json"
    if manifest_file.exists():
        original = json.loads(manifest_file.read_text())
        fixed = set(experiment) - {"model_settings", "max_model_cost_usd"}
        if any(original.get(k) != experiment[k] for k in fixed):
            raise SystemExit("Existing weekly artifacts use a different packet or configuration.")
        if original["max_model_cost_usd"] != budget:
            original.setdefault("budget_changes", []).append({
                "from_usd": original["max_model_cost_usd"], "to_usd": budget, "at_utc": stamp(),
            })
            original["max_model_cost_usd"] = budget
            save(manifest_file, original)
        if original["model_settings"] != experiment["model_settings"]:
            previous = original["model_settings"]
            changes = [model for model in models if previous.get(model) != models[model]]
            if previous.keys() != models.keys() or changes != ["glm"] or previous["glm"]["id"] != "z-ai/glm-5.3-flashx":
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
    budget_lock = Condition()
    in_flight = 0
    accounted = sum(a.get("accounted_usd", 0) for path in (root / "calls").glob("*/*.json")
                    for a in json.loads(path.read_text()))

    def collect(case, one_attempt=False):
        nonlocal accounted, in_flight
        group, condition, temperature, member, model = case
        settings = models[model]
        model_id, providers, effort = settings["id"], settings["providers"], settings["reasoning_effort"]
        price_in, price_out = settings["max_input_per_m"], settings["max_output_per_m"]
        raw_path = root / "calls" / group / f"{member.agent_id}.json"
        result_path = root / "ballots" / group / f"{member.agent_id}.json"
        if result_path.exists():
            ballot = json.loads(result_path.read_text())
            validate_ballot(ballot, candidates, member.agent_id, member.persona)
            return case, ballot, []
        attempts = json.loads(raw_path.read_text()) if raw_path.exists() else []
        search = searches.get(condition)
        for attempt in reversed(attempts):
            if attempt.get("model") != model_id or not attempt.get("content"):
                continue
            if search and not attempt.get("web_search_requests"):
                continue
            try:
                ballot = normalize_ballot(attempt["content"], candidates, member, allow_search_preamble=bool(search))
            except (ValueError, TypeError, KeyError, IndexError):
                continue
            save(result_path, ballot)
            return case, ballot, attempts
        variant_prompts = experiment.get("arm_system_prompts", {}).get(condition, {})
        system = variant_prompts.get(member.agent_id, experiment["system_prompts"][member.agent_id])
        user = prompts[condition]
        # A byte-per-token bound, with chat framing and cache-write headroom.
        reserved = ((len(system.encode()) + len(user.encode()) + 2048) * price_in * 1.5
                    + max_output * price_out) / 1_000_000
        if search:
            reserved = max(reserved, search["reservation_usd"])
        sent = sum(attempt["model"] == model_id and not (
            search and attempt.get("error") == "Provider usage reports no completed web searches."
            and "content" not in attempt
        ) for attempt in attempts)
        remaining = min(1, max_attempts - sent) if one_attempt else max_attempts - sent
        for number in range(len(attempts) + 1, len(attempts) + remaining + 1):
            with budget_lock:
                while accounted + reserved > budget and in_flight and datetime.now(timezone.utc) < deadline:
                    budget_lock.wait(timeout=2)
                if accounted + reserved > budget or datetime.now(timezone.utc) >= deadline:
                    return case, None, ["budget or deadline reached"]
                accounted += reserved
                in_flight += 1
            attempt = {"attempt": number, "model": model_id, "requested_temperature": temperature,
                       "started_at_utc": stamp(), "accounted_usd": reserved}
            attempts.append(attempt)
            save(raw_path, attempts)  # reservation survives interruption
            ballot = None
            try:
                payload = {
                    "model": model_id, "max_tokens": max_output, "temperature": temperature,
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
                if search:
                    payload.update(search["payload"])
                    if model == "haiku":
                        # Allow the model to emit a tool call before drafting JSON.
                        payload.pop("response_format")
                        payload["tool_choice"] = "required"
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
                message = choice["message"]
                attempt["content"] = message["content"]
                if search:
                    tool_usage = (attempt["usage"].get("server_tool_use_details")
                                  or attempt["usage"].get("server_tool_use") or {})
                    attempt["web_search_requests"] = (
                        tool_usage.get("web_search_requests", 0)
                    )
                    attempt["source_annotations"] = message.get("annotations") or []
                    if not attempt["web_search_requests"]:
                        raise ValueError("Provider usage reports no completed web searches.")
                ballot = normalize_ballot(attempt["content"] or "", candidates, member,
                                           allow_search_preamble=bool(search))
            except (requests.RequestException, ValueError, TypeError, KeyError, IndexError) as exc:
                attempt["error"] = str(exc).replace(key, "[redacted]")[:280]
            attempt["finished_at_utc"] = stamp()
            save(raw_path, attempts)
            with budget_lock:
                accounted += attempt["accounted_usd"] - reserved
                in_flight -= 1
                budget_lock.notify_all()
            if ballot is not None:
                save(result_path, ballot)
                return case, ballot, attempts
            if attempt.get("http_status") in {401, 402, 403, 404}:
                break
        return case, None, attempts

    smoke = [next(case for case in expected if case[-1] == name) for name in models]
    with ThreadPoolExecutor(max_workers=min(6, concurrency)) as pool:
        for case, ballot, attempts in pool.map(lambda case: collect(case, one_attempt=True), smoke):
            detail = "" if ballot or not attempts else str(attempts[-1])[:420]
            print("Preflight", case[-1], "valid" if ballot else detail, flush=True)
    completed = {}
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
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
    usage = []
    for call in call_log:
        row = {key: value for key, value in call.items()
               if key not in {"content", "error", "completion_id", "source_annotations"}}
        if "source_annotations" in call:
            row["web_sources"] = [
                {"url": citation["url"], "title": citation.get("title")}
                for annotation in call["source_annotations"]
                if (citation := annotation.get("url_citation")) and citation.get("url")
            ]
        usage.append(row)
    save(root / "usage.json", usage)
    print(f"Complete: {len(ballots)} valid of {len(expected)} seats, {len(aggregates)}/{len(counts)} qualifying groups, ${result['cost_usd']:.4f} provider-reported.", flush=True)
    return result, ballots


if __name__ == "__main__":
    main()
