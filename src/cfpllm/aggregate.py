"""Ballot validation and transparent Borda aggregation."""

from __future__ import annotations

from collections import defaultdict
import json
import re
from typing import Any, Iterable


class BallotError(ValueError):
    pass


def parse_ballot(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", stripped, flags=re.IGNORECASE)
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise BallotError(f"invalid JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise BallotError("ballot must be a JSON object")
    return value


def validate_ballot(ballot: dict[str, Any], candidates: Iterable[str], agent_id: str | None = None, persona: str | None = None) -> None:
    allowed = set(candidates)
    ranking = ballot.get("ranking")
    if not isinstance(ranking, list):
        raise BallotError("ranking must be a list")
    if len(ranking) != 25:
        raise BallotError(f"ranking must contain exactly 25 teams, got {len(ranking)}")
    if len(set(ranking)) != 25:
        raise BallotError("ranking contains duplicate teams")
    unknown = [team for team in ranking if team not in allowed]
    if unknown:
        raise BallotError(f"ranking includes non-candidate team(s): {', '.join(map(str, unknown))}")
    rationales = ballot.get("rationales")
    if not isinstance(rationales, dict):
        raise BallotError("rationales must be an object")
    if set(rationales) != set(ranking[:12]):
        raise BallotError("rationale keys must be exactly the first 12 ranked teams")
    if any(not isinstance(value, str) or not value.strip() for value in rationales.values()):
        raise BallotError("each rationale must be a nonempty string")
    if agent_id is not None and ballot.get("agent_id") != agent_id:
        raise BallotError(f"agent_id must be {agent_id}")
    if persona is not None and ballot.get("persona") != persona:
        raise BallotError(f"persona must be {persona}")


def aggregate_ballots(ballots: Iterable[dict[str, Any]], candidates: Iterable[str], sp_ratings: dict[str, float] | None = None) -> dict[str, Any]:
    """Apply 25..1 Borda. Unranked candidates receive no points."""
    candidate_list = list(candidates)
    points: dict[str, int] = defaultdict(int)
    valid = list(ballots)
    for ballot in valid:
        validate_ballot(ballot, candidate_list)
        for position, team in enumerate(ballot["ranking"], 1):
            points[team] += 26 - position
    sp = sp_ratings or {}
    ranking = sorted(candidate_list, key=lambda team: (-points[team], -float(sp.get(team, float("-inf"))), team))
    return {
        "ranking": ranking[:25],
        "top_12_seeds": ranking[:12],
        "points": {team: points[team] for team in ranking[:25]},
        "valid_ballots": len(valid),
        "tie_break": "higher SP+ where present, then alphabetical",
    }
