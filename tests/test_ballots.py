from __future__ import annotations

import pytest

from cfpllm.aggregate import BallotError, parse_ballot, validate_ballot
from conftest import ballot, teams


def test_valid_ballot_is_accepted():
    value = ballot(teams())
    validate_ballot(value, teams(), "M01", "metrics_heavy")


def test_duplicate_team_is_rejected():
    value = ballot(teams())
    value["ranking"][24] = value["ranking"][0]
    with pytest.raises(BallotError, match="duplicate"):
        validate_ballot(value, teams())


def test_rationale_keys_must_match_top_twelve():
    value = ballot(teams())
    value["rationales"].pop(value["ranking"][0])
    with pytest.raises(BallotError, match="exactly"):
        validate_ballot(value, teams())


def test_parser_accepts_a_markdown_fence_for_recovery():
    value = ballot(teams())
    parsed = parse_ballot("```json\n" + __import__("json").dumps(value) + "\n```")
    assert parsed["ranking"][0] == "Team 01"
