"""Measure how two auditable web research packets affect the same mixed committee."""

from argparse import ArgumentParser
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import load_config
from .lint import lint_packet
from .odds_report import rank_changes
from .packet import local_date, read_packet
from .panel import MAX_ATTEMPTS, MAX_OUTPUT, describe_models, plan, run_panel, save
from .prompts import system_prompt, user_prompt
from .aggregate import aggregate_ballots


CONFIGURATION = "mixed|cfp_on_ap_on|0.3"
PROFILE = "research-pilot-v1"
ARMS = ("packet_only", "statistical_research", "pundit_research")
FOCUS = {
    "metrics_heavy": "Look for opponent-adjusted efficiency and strength of record, and say when they disagree.",
    "sec_tilt": "Check SEC contenders against similarly situated teams, including outcome and schedule difficulty.",
    "big_ten_tilt": "Compare Big Ten bubble teams using quality wins, road performance and shared opponents.",
    "eye_test": "Look for game flow, margins in meaningful minutes and late-game context.",
    "ap_anchored": "Identify fresh evidence that warrants moving a team from its dated AP ranking.",
    "head_to_head_first": "Verify direct results and compare the teams' broader records before using them as a tiebreak.",
    "performatively_unbiased": "Find the strongest evidence on each side of disputed bubble placements.",
    "brand_bias": "Check whether reputation explains disagreement and require game evidence for a large ranking difference.",
}


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--research", required=True, type=Path)
    args = parser.parse_args()
    config = load_config(args.config)
    packet_path = config.packet_dir / "packet.json"
    lint_packet(packet_path, config)
    packet = read_packet(packet_path)
    deadline = datetime.fromisoformat(f"{config.release_id}T16:00:00").replace(tzinfo=ZoneInfo("America/New_York"))
    sources = read_packet(args.research)
    for arm in ARMS[1:]:
        if len(sources[arm]) < 2 or any(local_date(item["published"]) >= deadline.date() for item in sources[arm]):
            raise ValueError("Each research arm needs at least two sources dated before the target release day.")
    base = user_prompt(packet, "cfp_on_ap_on")
    prompts = {ARMS[0]: base}
    for arm in ARMS[1:]:
        prompts[arm] = base + "\nFrozen research notes, with dates and sources:\n" + json.dumps(sources[arm], ensure_ascii=False)
    cases, members, model_names = [], {}, {}
    for group, _, temp, seat, model in plan("weekly-v3"):
        if group == CONFIGURATION:
            for arm in ARMS:
                cases.append((f"mixed|{arm}|{temp:g}", arm, temp, seat, model))
            members[seat.agent_id] = seat
            model_names[model] = None
    systems = {seat: system_prompt(member, ordered_rationales=True, reassess_polls=True)
               for seat, member in members.items()}
    instructions = {
        "statistical_research": (
            "The attached notes are authorized research evidence. Use only verifiable statistics and factual "
            "game context from these notes. Separate performance metrics from résumé metrics."
        ),
        "pundit_research": (
            "The attached notes are authorized research evidence. Treat the analyst rankings and bracket "
            "projections as opinions. Weigh their football reasoning and keep projected seeds distinct from ranks."
        ),
    }
    variants = {
        arm: {seat: systems[seat] + "\n" + guidance + " " + FOCUS[member.persona]
              + " If a research note changes a placement, identify its source in the explanation."
              for seat, member in members.items()}
        for arm, guidance in instructions.items()
    }
    meta = {
        "release_id": config.release_id, "profile": PROFILE, "packet_sha256": sha256(packet_path.read_bytes()).hexdigest(),
        "lock_deadline": deadline.isoformat(), "requested_ballots": len(cases), "max_model_cost_usd": 2.0,
        "max_attempts_per_ballot": MAX_ATTEMPTS, "max_output_tokens": MAX_OUTPUT,
        "conditions": {arm: {"ap": True, "cfp": True, "opening_spreads": True} for arm in ARMS},
        "model_settings": describe_models(model_names), "system_prompts": systems, "arm_system_prompts": variants,
        "user_prompt_sha256": {arm: sha256(prompt.encode()).hexdigest() for arm, prompt in prompts.items()},
        "research_sources": sources,
    }
    folder = config.ballot_dir / PROFILE
    results, ballots = run_panel(folder, packet, cases, prompts, meta)
    groups = {
        arm: {b["agent_id"]: b for b in ballots if b["group"] == f"mixed|{arm}|0.3"}
        for arm in ARMS
    }
    matched = sorted(set.intersection(*(set(g) for g in groups.values())))
    candidates = packet["candidates"]
    comparisons = {"matched_seats": len(matched), "provider_cost_usd": results["cost_usd"], "comparisons": {}}
    if len(matched) >= 10:
        rankings = {arm: aggregate_ballots([group[seat] for seat in matched], candidates,
                                           packet["ratings"].get("sp_plus"))["ranking"]
                    for arm, group in groups.items()}
        comparisons["rankings"] = rankings
        comparisons["comparisons"] = {
            arm: rank_changes(rankings["packet_only"], rankings[arm], candidates)
            for arm in ARMS[1:]
        }
    save(folder / "comparison.json", comparisons)
    print(json.dumps(comparisons, indent=2))


if __name__ == "__main__":
    main()
