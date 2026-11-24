"""Compare matched odds-pilot seats and score them after the official release."""

from argparse import ArgumentParser
from hashlib import sha256
from pathlib import Path

from .aggregate import aggregate_ballots
from .config import load_config
from .odds_pilot import ARMS, BRAND_SEAT, MODELS, POLL_SETTINGS, PROFILE
from .packet import read_packet
from .panel import save
from .score import kendall_tau_b, load_official, predicted_ranks, score_ranking


def rank_changes(before, after, teams):
    original = predicted_ranks(before, teams)
    updated = predicted_ranks(after, teams)
    return {
        "top_12_in": [team for team in after[:12] if team not in before[:12]],
        "top_12_out": [team for team in before[:12] if team not in after[:12]],
        "kendall_tau_b": round(kendall_tau_b(original, updated), 6),
        "places_gained": {t: a - b for t, a, b in zip(teams, original, updated, strict=True) if a != b},
    }


def report(packet, result, ballots, official):
    candidates = packet["candidates"]
    sp_plus = packet["ratings"].get("sp_plus")
    groups = {}
    for ballot in ballots:
        groups.setdefault(ballot["group"], {})[ballot["agent_id"]] = ballot
    comparisons, brands = {}, {}
    for model in MODELS:
        for poll in POLL_SETTINGS:
            pair = f"{model}|{poll}"
            control, treatment = (groups.get(f"{pair}|{arm}", {}) for arm in ARMS)
            seats = sorted(control.keys() & treatment.keys())
            match = {"matched_seats": len(seats)}
            comparisons[pair] = match
            if len(seats) >= 10:
                before, after = (aggregate_ballots([arm[seat] for seat in seats], candidates, sp_plus)["ranking"]
                                 for arm in (control, treatment))
                match.update(rank_changes(before, after, candidates),
                             ranking_without_spreads=before, ranking_with_spreads=after)
                if official:
                    match["official_scores"] = {
                        "without_spreads": score_ranking(before, official),
                        "with_spreads": score_ranking(after, official),
                    }
            for arm in ARMS:
                key = f"{pair}|{arm}"
                group = groups.get(key, {})
                brand_vote = group.get(BRAND_SEAT.agent_id)
                others = [ballot for seat, ballot in group.items() if seat != BRAND_SEAT.agent_id]
                if not brand_vote or len(others) < 10:
                    continue
                without = aggregate_ballots(others, candidates, sp_plus)["ranking"]
                with_brand = result["runs"][key]["ranking"]
                brands[key] = {
                    **rank_changes(without, with_brand, candidates),
                    "other_valid_seats": len(others), "brand_ballot": brand_vote["ranking"],
                }
    return {
        "release_id": result["release_id"], "profile": result["profile"], "packet_sha256": result["packet_sha256"],
        "requested_ballots": result["requested_ballots"], "valid_ballots": result["valid_ballots"],
        "provider_cost_usd": result["cost_usd"], "official_status": "available" if official else "pending_release",
        "opening_spread_comparisons": comparisons, "brand_vote_comparisons": brands,
    }


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--official", type=Path)
    args = parser.parse_args()
    config = load_config()
    root = config.ballot_dir / PROFILE
    packet_path = config.packet_dir / "packet.json"
    packet = read_packet(packet_path)
    result = read_packet(root / "aggregates.json")
    if result["packet_sha256"] != sha256(packet_path.read_bytes()).hexdigest():
        raise ValueError("The odds pilot was run on a different packet.")
    official = None
    if args.official:
        teams = sorted(set(packet["candidates"]) | {game[side] for game in packet["games"]
                                                    for side in ("home_team", "away_team")})
        release, official = load_official(args.official, teams)
        if release != result["release_id"]:
            raise ValueError("The official ranking belongs to a different release.")
    name = "official-comparison.json" if official else "comparison.json"
    save(root / name, report(packet, result, read_packet(root / "valid-ballots.json"), official))
    print(root / name)


if __name__ == "__main__":
    main()
