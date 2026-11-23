from __future__ import annotations

from copy import deepcopy
import json

import pytest

from cfpllm.prompts import CONDITIONS, GAME_COLUMNS, packet_slice, user_prompt


def test_information_conditions_strip_ranking_fields_from_every_resume(packet):
    sliced = packet_slice(packet, "cfp_off_ap_off")
    assert "rankings" not in sliced
    assert all("ap_rank" not in resume and "prior_cfp_rank" not in resume for resume in sliced["resumes"].values())
    rendered = user_prompt(packet, "cfp_off_ap_off")
    assert "prior_cfp_rank" not in rendered
    assert "ap_rank" not in rendered


def test_information_conditions_preserve_requested_ranking_fields(packet):
    sliced = packet_slice(packet, "cfp_on_ap_on")
    assert set(sliced["rankings"]) == {"ap", "cfp"}
    assert sliced["resumes"]["Team 01"]["ap_rank"] == 1
    assert sliced["resumes"]["Team 01"]["prior_cfp_rank"] == 1


@pytest.mark.parametrize("condition", CONDITIONS)
def test_compact_prompt_preserves_evidence_and_respects_condition(packet, condition):
    packet["candidates"].reverse()
    packet["games"][0].update(
        id=420001, week=13, home_points=31, away_points=24, neutral_site=True,
        home_conference="ACC", away_conference="Big Ten",
        home_classification="fbs", away_classification="fbs",
    )
    original = deepcopy(packet)
    payload = json.loads(user_prompt(packet, condition).split("\n", 1)[1])
    games = payload.pop("games")
    assert games["columns"] == list(GAME_COLUMNS)
    assert [dict(zip(games["columns"], row, strict=True)) for row in games["rows"]] == [
        {key: value for key, value in game.items() if key != "id"} for game in original["games"]
    ]
    assert payload["candidates"] == sorted(original["candidates"])
    assert set(payload.get("rankings", {})) == {key for key, enabled in CONDITIONS[condition].items() if enabled}
    for team, resume in payload["resumes"].items():
        expected = original["resumes"][team].copy()
        for poll, field in (("ap", "ap_rank"), ("cfp", "prior_cfp_rank")):
            if not CONDITIONS[condition][poll]:
                expected.pop(field)
        assert resume == expected
    assert payload["ratings"] == original["ratings"]
    assert packet == original
