from __future__ import annotations

from cfpllm.aggregate import aggregate_ballots
from conftest import ballot, teams


def test_borda_assigns_25_through_1_points():
    result = aggregate_ballots([ballot(teams())], teams())
    assert result["points"]["Team 01"] == 25
    assert result["points"]["Team 25"] == 1


def test_tied_borda_uses_sp_then_alphabetical():
    candidate_list = teams()
    forward = ballot(candidate_list, "M01")
    reverse = ballot(list(reversed(candidate_list[:25])), "M02")
    result = aggregate_ballots([forward, reverse], candidate_list, {"Team 02": 99.0, "Team 01": 98.0})
    assert result["ranking"][:2] == ["Team 02", "Team 01"]
    assert result["tie_break"] == "higher SP+ where present, then alphabetical"
