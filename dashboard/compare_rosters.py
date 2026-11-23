"""Summarize matched seats and committee rankings without exporting source games."""

import json
from collections import defaultdict
from hashlib import sha256
from pathlib import Path
from statistics import mean, median

from cfpllm.aggregate import validate_ballot
from cfpllm.config import load_config
from cfpllm.lint import lint_packet
from cfpllm.packet import read_packet
from cfpllm.personas import weekly_committee
from cfpllm.score import kendall_tau_b, predicted_ranks


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def direct_matchups(packet):
    eligible = set(packet["candidates"])
    outcomes = defaultdict(set)
    for game in packet["games"]:
        home, away = game.get("home_team"), game.get("away_team")
        hp, ap = game.get("home_points"), game.get("away_points")
        if home != away and {home, away} <= eligible and isinstance(hp, int) and isinstance(ap, int) and hp != ap:
            winner = home if hp > ap else away
            outcomes[tuple(sorted((home, away)))].add(winner)
    matchups = []
    for teams, winners in sorted(outcomes.items()):
        if len(winners) == 1:
            winner = next(iter(winners))
            loser = teams[1] if teams[0] == winner else teams[0]
            matchups.append((winner, loser))
    return matchups


def comparable(packet, winner, loser):
    first, second = (packet["resumes"].get(team, {}) for team in (winner, loser))
    try:
        first_losses, second_losses = (int(r["record"]["overall"].split("-")[1]) for r in (first, second))
    except (KeyError, IndexError, ValueError, AttributeError, TypeError):
        return False
    a, b = first.get("fbs_sos_proxy"), second.get("fbs_sos_proxy")
    return a is not None and b is not None and abs(first_losses - second_losses) <= 1 and abs(a - b) <= .05 + 1e-9


def ranking_preference(ranking, matchups):
    positions = {team: rank for rank, team in enumerate(ranking, 1)}
    outcomes = []
    for winner, loser in matchups:
        a, b = positions.get(winner, 26), positions.get(loser, 26)
        outcomes.append(1 if a < b else .5 if a == b else 0)
    return mean(outcomes)


def ballot_lookup(directory, profile, candidates):
    roles = {member.agent_id: member.persona for member in weekly_committee(profile)}
    output = {}
    for ballot in read(directory / "valid-ballots.json"):
        seat = ballot["agent_id"]
        validate_ballot(ballot, candidates, seat, roles[seat])
        key = (ballot["group"], seat)
        assert key not in output
        output[key] = ballot
    return output


def compare_seats(left, right, keys, games):
    if not keys:
        return {"matched_ballots": 0, "old": None, "new": None, "delta": None}
    old = [ranking_preference(left[k]["ranking"], games) for k in keys]
    new = [ranking_preference(right[k]["ranking"], games) for k in keys]
    return {"matched_ballots": len(keys), "old": round(mean(old), 6), "new": round(mean(new), 6),
            "delta": round(mean(b - a for a, b in zip(old, new)), 6)}


def main():
    cfg = load_config()
    packet_path = cfg.packet_dir / "packet.json"
    lint_packet(packet_path, cfg)
    packet = read_packet(packet_path)
    source_hash = sha256(packet_path.read_bytes()).hexdigest()
    candidates = packet["candidates"]
    old_dir, new_dir = (cfg.ballot_dir / name for name in ("weekly-panel", "weekly-panel-v2"))
    direct = direct_matchups(packet)
    close = [(a, b) for a, b in direct if comparable(packet, a, b)]
    if not (new_dir / "aggregates.json").exists():
        print({"unique_direct_matchups": len(direct), "comparable_matchups": len(close)})
        return
    old, new = (read(d / "aggregates.json") for d in (old_dir, new_dir))
    assert old["packet_sha256"] == new["packet_sha256"] == source_hash
    assert old["profile"] == "weekly-v1" and new["profile"] == "weekly-v2"
    left = ballot_lookup(old_dir, "weekly-v1", candidates)
    right = ballot_lookup(new_dir, "weekly-v2", candidates)
    assert len(right) == new["valid_ballots"] and len(left) == old["valid_ballots"]
    shared = sorted(k for k in left.keys() & right.keys() if left[k]["model"] == right[k]["model"])
    changed = [k for k in shared if right[k]["persona"] == "head_to_head_first"]
    controls = [k for k in shared if right[k]["persona"] == left[k]["persona"]]
    group_comparison = {}
    for group in sorted(old["runs"].keys() & new["runs"].keys()):
        a, b = (run["runs"][group]["ranking"] for run in (old, new))
        group_comparison[group] = {
            "kendall_tau_b": round(kendall_tau_b(predicted_ranks(a, candidates), predicted_ranks(b, candidates)), 6),
            "top_12_overlap": len(set(a[:12]) & set(b[:12])),
            "top_12_in": [team for team in b[:12] if team not in a[:12]],
            "top_12_out": [team for team in a[:12] if team not in b[:12]],
            "old_top_12": a[:12], "new_top_12": b[:12],
        }
    summary = {
        "release_id": new["release_id"], "packet_sha256": source_hash,
        "run": {"profile": new["profile"], "requested_ballots": new["requested_ballots"],
                "valid_ballots": new["valid_ballots"], "qualified_groups": len(new["runs"]),
                "requested_groups": len(new["valid_by_group"]), "attempted_calls": new["attempted_calls"],
                "provider_reported_cost_usd": new["cost_usd"], "accounted_usd": new["accounted_usd"]},
        "head_to_head_ballots": sum(b["persona"] == "head_to_head_first" for b in right.values()),
        "winner_preference": {
            "definition": "Compare each ballot's winner and loser ranks across unique completed matchups between candidates. A split series is excluded. An unranked team gets rank 26 and a rank tie counts as half a preference.",
            "comparable_proxy": "The two teams differ by at most one overall loss and five percentage points on the frozen FBS schedule-strength proxy.",
        },
        "group_summary": {
            "matched_groups": len(group_comparison),
            "median_kendall_tau_b": (
                median(item["kendall_tau_b"] for item in group_comparison.values()) if group_comparison else None
            ),
            "same_top_12": sum(item["top_12_overlap"] == 12 for item in group_comparison.values()),
            "top_12_overlaps": {str(k): sum(item["top_12_overlap"] == k for item in group_comparison.values())
                                for k in range(13) if any(item["top_12_overlap"] == k for item in group_comparison.values())},
        },
        "groups": group_comparison,
        "notes": [
            "The two changed seats previously used Metrics Heavy and Performatively Neutral. Matched comparisons hold group, seat, and model fixed.",
            "The two runs used independent model calls. Remaining seats provide a descriptive check on variation. The comparison does not establish causal effects or forecast accuracy.",
            "Official target-release accuracy is evaluated separately.",
        ],
    }
    for label, games in (("all_direct_matchups", direct), ("comparable_matchups", close)):
        if games:
            summary["winner_preference"][label] = {
                "unique_matchups": len(games),
                "changed_seats": compare_seats(left, right, changed, games),
                "unchanged_seats": compare_seats(left, right, controls, games),
            }
    target = new_dir / "roster-comparison.json"
    target.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "groups"}, indent=2))
    print(json.dumps(group_comparison.get("mixed|cfp_on_ap_on|0.3"), indent=2))


if __name__ == "__main__":
    main()
