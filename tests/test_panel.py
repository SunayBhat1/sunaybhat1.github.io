from collections import Counter
import json

import pytest

from cfpllm.aggregate import BallotError
from cfpllm.panel import normalize_ballot, plan
from cfpllm.personas import DEFAULT_WEEKLY_PROFILE, WEEKLY_PROFILES, committee_mix, weekly_committee
from cfpllm.prompts import system_prompt


@pytest.mark.parametrize("profile", ("weekly-v1", "weekly-v2"))
def test_weekly_panel_has_the_intended_models_and_seats(profile):
    cases = list(plan(profile))
    assert len(cases) == 416
    assert set(Counter(case[0] for case in cases).values()) == {13}
    assert Counter(case[-1] for case in cases) == {"luna": 68, "haiku": 68, "gemini": 68,
                                                "deepseek": 68, "glm": 76, "minimax": 68}
    assert len({(case[0], case[3].agent_id) for case in cases}) == len(cases)


def test_head_to_head_has_two_seats_per_group_on_the_new_roster_only():
    assert "weekly-v2" in WEEKLY_PROFILES
    original = weekly_committee("weekly-v1")
    updated = weekly_committee("weekly-v2")
    assert original == committee_mix("balanced")
    assert [member.agent_id for member in updated] == [member.agent_id for member in original]
    changed = [(before.persona, after) for before, after in zip(original, updated) if before != after]
    assert [(before, after.persona) for before, after in changed] == [
        ("metrics_heavy", "head_to_head_first"), ("performatively_unbiased", "head_to_head_first"),
    ]
    cases = list(plan())
    assert Counter(group for group, _, _, member, _ in cases if member.persona == "head_to_head_first") == {
        group: 2 for group, *_ in cases
    }
    for _, member in changed:
        prompt = system_prompt(member, ordered_rationales=True)
        assert "Prefer the winner" in prompt
        assert "Resolve split series, cycles" in prompt


def test_new_weekly_profile_runs_only_mixed_committees():
    assert DEFAULT_WEEKLY_PROFILE == "weekly-v3"
    cases = list(plan())
    assert len(cases) == 112
    assert set(Counter(case[0] for case in cases).values()) == {14}
    assert all(case[0].startswith("mixed|") for case in cases)
    assert weekly_committee("weekly-v3")[:-1] == weekly_committee("weekly-v2")
    assert weekly_committee("weekly-v3")[-1].persona == "brand_bias"


def test_normalization_preserves_rank_order_and_requires_distinct_teams(packet):
    member = committee_mix("balanced")[0]
    ranking = packet["candidates"][:25]
    content = {"ranking": ranking.copy(), "rationales": [f"Evidence for {team}" for team in ranking]}
    ballot = normalize_ballot(json.dumps(content), packet["candidates"], member)
    assert ballot["ranking"] == ranking
    assert list(ballot["rationales"]) == ranking[:12]
    assert ballot["persona"] == member.persona
    content["ranking"][-1] = ranking[0]
    with pytest.raises(BallotError, match="duplicate"):
        normalize_ballot(json.dumps(content), packet["candidates"], member)
