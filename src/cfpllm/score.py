"""Post-release scoring. No model or network access is used here."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .names import resolve_name


def predicted_ranks(ranking: list[str], official_teams: list[str]) -> list[int]:
    positions = {team: index for index, team in enumerate(ranking, 1)}
    return [positions.get(team, 26) for team in official_teams]


def _pearson(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        return 0.0
    lm, rm = sum(left) / len(left), sum(right) / len(right)
    numerator = sum((a - lm) * (b - rm) for a, b in zip(left, right))
    divisor = math.sqrt(sum((a - lm) ** 2 for a in left) * sum((b - rm) ** 2 for b in right))
    return numerator / divisor if divisor else 0.0


def _average_ranks(values: list[int]) -> list[float]:
    ranked = [0.0] * len(values)
    ordered = sorted(enumerate(values), key=lambda pair: pair[1])
    start = 0
    while start < len(ordered):
        stop = start + 1
        while stop < len(ordered) and ordered[stop][1] == ordered[start][1]:
            stop += 1
        average_rank = (start + 1 + stop) / 2
        for index, _ in ordered[start:stop]:
            ranked[index] = average_rank
        start = stop
    return ranked


def spearman(official_ranks: list[int], predicted: list[int]) -> float:
    """Correlate sample ranks, assigning tied predictions their average rank."""
    return _pearson(_average_ranks(official_ranks), _average_ranks(predicted))


def kendall_tau_b(official_ranks: list[int], predicted: list[int]) -> float:
    concordant = discordant = tied_left = tied_right = 0
    for i in range(len(official_ranks)):
        for j in range(i + 1, len(official_ranks)):
            left_delta = official_ranks[i] - official_ranks[j]
            right_delta = predicted[i] - predicted[j]
            if left_delta == 0 and right_delta == 0:
                continue
            if left_delta == 0:
                tied_left += 1
            elif right_delta == 0:
                tied_right += 1
            elif (left_delta > 0) == (right_delta > 0):
                concordant += 1
            else:
                discordant += 1
    denominator = math.sqrt((concordant + discordant + tied_left) * (concordant + discordant + tied_right))
    return (concordant - discordant) / denominator if denominator else 0.0


def score_ranking(ranking: list[str], official: list[dict[str, Any]]) -> dict[str, float | str]:
    ordered_official = sorted(official, key=lambda item: int(item["rank"]))
    teams = [str(item["team"]) for item in ordered_official]
    ranks = [int(item["rank"]) for item in ordered_official]
    predicted = predicted_ranks(ranking, teams)
    official_top15 = list(zip(ranks, predicted))[:15]
    official_top12 = list(zip(ranks, predicted))[:12]
    return {
        "spearman": round(spearman(ranks, predicted), 6),
        "kendall_tau_b": round(kendall_tau_b(ranks, predicted), 6),
        "top_15_mae": round(sum(abs(pred - actual) for actual, pred in official_top15) / len(official_top15), 6),
        "top_12_overlap": f"{len(set(ranking[:12]) & set(teams[:12]))}/12",
        "seed_mae": round(sum(abs(pred - actual) for actual, pred in official_top12) / len(official_top12), 6),
    }


def load_official(path: str | Path, canonical_names: list[str]) -> tuple[str, list[dict[str, Any]]]:
    with Path(path).open(encoding="utf-8") as handle:
        raw = json.load(handle)
    rankings = raw.get("rankings")
    if not isinstance(rankings, list) or len(rankings) != 25:
        raise ValueError("official file must contain exactly 25 rankings")
    resolved = []
    for entry in rankings:
        if not isinstance(entry, dict) or "rank" not in entry or "team" not in entry:
            raise ValueError("each official ranking must contain rank and team")
        resolved.append({"rank": int(entry["rank"]), "team": resolve_name(str(entry["team"]), canonical_names)})
    if [item["rank"] for item in sorted(resolved, key=lambda item: item["rank"])] != list(range(1, 26)):
        raise ValueError("official ranks must be the integers 1 through 25")
    if len({item["team"] for item in resolved}) != 25:
        raise ValueError("official rankings resolve to duplicate teams")
    return str(raw.get("release_id") or "unknown"), resolved


def baselines(packet: dict[str, Any]) -> dict[str, list[str]]:
    candidates = set(packet["candidates"])
    output: dict[str, list[str]] = {}
    for key, label in (("ap", "AP poll"), ("cfp", "Prior CFP")):
        entries = packet.get("rankings", {}).get(key, {}).get("entries", [])
        if entries:
            output[label] = [entry["team"] for entry in sorted(entries, key=lambda item: item["rank"]) if entry["team"] in candidates]
    ratings = packet.get("ratings", {})
    for key, label in (("sp_plus", "SP+"), ("fpi", "FPI")):
        values = ratings.get(key)
        if isinstance(values, dict) and values:
            output[label] = [name for name, _ in sorted(values.items(), key=lambda item: (-float(item[1]), item[0])) if name in candidates]
    return output


def score_all(packet: dict[str, Any], aggregates: dict[str, Any], official: list[dict[str, Any]]) -> dict[str, Any]:
    run_scores = {
        key: score_ranking(value["ranking"], official)
        for key, value in aggregates.get("runs", {}).items()
    }
    baseline_scores = {name: score_ranking(ranking, official) for name, ranking in baselines(packet).items()}
    return {
        "release_id": aggregates.get("release_id"),
        "rank_26_convention": "A team unranked by a predictor is assigned rank 26 for all rank-error metrics.",
        "runs": run_scores,
        "baselines": baseline_scores,
    }
