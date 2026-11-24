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


def test_rich_packet_never_leaks_withheld_opponent_ranks(packet):
    game = packet["games"][0]
    game["id"] = 421
    packet["meta"]["resume_schema"] = 2
    packet["opening_spreads"] = {"421": -7.0}
    packet["resumes"]["Team 01"]["ranked_opponents"] = {
        "ap": [["2026-11-21", "Team 02", "31-24", "H", 12, 6]],
        "cfp": [["2026-11-21", "Team 02", "31-24", "H", 8, 8]],
    }
    ap_only = packet_slice(packet, "cfp_off_ap_on")
    assert set(ap_only["resumes"]["Team 01"]["ranked_opponents"]) == {"ap"}
    hidden = packet_slice(packet, "cfp_off_ap_off")
    assert "ranked_opponents" not in hidden["resumes"]["Team 01"]
    prompt = user_prompt(packet, "cfp_off_ap_off")
    games = json.loads(prompt.splitlines()[-1])["games"]
    assert games["columns"][-1] == "opening_home_spread"
    assert games["rows"][0][-1] == -7.0
    assert "opening_home_spread" not in user_prompt(packet, "cfp_off_ap_off", include_packet_odds=False)
