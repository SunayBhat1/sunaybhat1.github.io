"""Run the paired CFP opening-spread experiment on a frozen release packet."""

from argparse import ArgumentParser
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from statistics import median
from zoneinfo import ZoneInfo

import requests

from .config import load_config
from .fetch import fetch_opening_quotes
from .lint import lint_packet
from .packet import read_packet
from .panel import MAX_ATTEMPTS, MAX_OUTPUT, describe_models, run_panel, save, stamp
from .personas import BRAND_SEAT, weekly_committee
from .prompts import CONDITIONS, system_prompt, user_prompt


MODELS = ("luna", "haiku")
POLL_SETTINGS = ("cfp_on_ap_on", "cfp_off_ap_off")
ARMS = ("no_odds", "opening_spreads")
PROFILE = "odds-pilot-v1"


def opening_spreads(config, packet, packet_hash):
    cache = config.packet_dir / "opening-spreads.json"
    game_ids = {int(game["id"]) for game in packet["games"]}
    if cache.is_file():
        evidence = read_packet(cache)
        if evidence["packet_sha256"] != packet_hash:
            raise ValueError("Stored spreads belong to a different frozen packet.")
    else:
        with requests.Session() as session:
            session.headers["Authorization"] = "Bearer " + os.environ["CFBD_API_KEY"]
            market = fetch_opening_quotes(session, config, game_ids)
        evidence = {
            "packet_sha256": packet_hash, "fetched_at_utc": stamp(), "endpoint": "/lines",
            "providers_by_game": market,
        }
        save(cache, evidence)
    quotes_by_game = evidence["providers_by_game"]
    spreads = {int(game_id): median(quotes.values()) for game_id, quotes in quotes_by_game.items()}
    if not spreads or not spreads.keys() <= game_ids:
        raise ValueError("No usable opening spreads or unexpected game IDs.")
    metadata = {
        "source": "CollegeFootballData /lines",
        "fetched_at_utc": evidence["fetched_at_utc"],
        "snapshot_sha256": sha256(cache.read_bytes()).hexdigest(),
        "games": len(game_ids), "games_with_opening_spread": len(spreads),
        "providers": sorted({provider for quotes in quotes_by_game.values() for provider in quotes}),
        "selection": "Median of available provider spreadOpen values, signed from the home team's perspective.",
    }
    return spreads, metadata


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true", help="Freeze and validate inputs without model calls.")
    args = parser.parse_args()
    config = load_config()
    deadline = datetime.fromisoformat(f"{config.release_id}T16:00:00").replace(tzinfo=ZoneInfo("America/New_York"))
    if datetime.now(timezone.utc) >= deadline:
        raise SystemExit("The pre-release lock deadline has passed.")
    packet_file = config.packet_dir / "packet.json"
    lint_packet(packet_file, config)
    packet = read_packet(packet_file)
    packet_hash = sha256(packet_file.read_bytes()).hexdigest()
    spreads, odds_source = opening_spreads(config, packet, packet_hash)
    members = [*weekly_committee("weekly-v2"), BRAND_SEAT]
    conditions = {}
    prompts = {}
    for poll in POLL_SETTINGS:
        for arm in ARMS:
            condition = f"{poll}|{arm}"
            conditions[condition] = dict(CONDITIONS[poll], opening_spreads=arm == "opening_spreads")
            prompts[condition] = user_prompt(packet, poll, opening_spreads=spreads if arm == "opening_spreads" else None,
                                             include_packet_odds=False)
    cases = [
        (f"{model}|{condition}", condition, 0.3, member, model)
        for member in members for condition in conditions for model in MODELS
    ]
    experiment = {
        "profile": PROFILE, "release_id": config.release_id, "packet_sha256": packet_hash,
        "lock_deadline": deadline.isoformat(), "requested_ballots": len(cases), "max_model_cost_usd": 2.0,
        "conditions": conditions, "model_settings": describe_models(MODELS),
        "max_attempts_per_ballot": MAX_ATTEMPTS, "max_output_tokens": MAX_OUTPUT,
        "system_prompts": {member.agent_id: system_prompt(member, ordered_rationales=True) for member in members},
        "user_prompt_sha256": {key: sha256(value.encode()).hexdigest() for key, value in prompts.items()},
        "odds_source": odds_source,
        "output_schema": "Top 25 canonical names and 12 short rationales, using the weekly ballot schema.",
    }
    print(json.dumps({"ballots": len(cases), "models": list(MODELS), "odds_source": odds_source,
                      "prompt_bytes": {key: len(value.encode()) for key, value in prompts.items()}}, indent=2), flush=True)
    if not args.prepare_only:
        run_panel(config.ballot_dir / PROFILE, packet, cases, prompts, experiment)


if __name__ == "__main__":
    main()
