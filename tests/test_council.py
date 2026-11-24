import pytest

from cfpllm.aggregate import BallotError
from cfpllm.council import tally, validate_review


def test_review_must_match_order_and_direct_result():
    ranking = ["Alabama", "Tennessee", *(f"Team {i}" for i in range(23))]
    agenda = [{"id": "P1", "teams": ["Alabama", "Tennessee"], "winner": "Tennessee"}]
    decision = {"id": "P1", "higher": "Tennessee", "winner": "Tennessee",
                "basis": "direct_game", "evidence": "Tennessee won 26–10."}
    review = {"ranking": ranking, "pair_decisions": [decision], "review_note": "Close résumés."}
    with pytest.raises(BallotError, match="agree with your ranking"):
        validate_review(review, set(ranking), agenda)
    decision["higher"] = "Alabama"
    with pytest.raises(BallotError, match="only the direct winner"):
        validate_review(review, set(ranking), agenda)
    decision.update(basis="overall_resume", evidence="Alabama had stronger results across its schedule.")
    assert validate_review(review, set(ranking), agenda) == review


def test_tally_preserves_unanimous_order_and_resolves_cycles():
    reviews = [{"ranking": order} for order in (["A", "B", "C", "D"], ["B", "C", "A", "D"], ["C", "A", "B", "D"])]
    assert tally(reviews, ["B", "A", "C", "D"]) == ["A", "B", "C", "D"]
    assert tally(reviews[::-1], ["B", "A", "C", "D"]) == tally(reviews, ["B", "A", "C", "D"])
