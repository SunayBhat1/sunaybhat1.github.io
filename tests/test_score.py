from __future__ import annotations

import json

from cfpllm import cli
from cfpllm.packet import write_packet
from cfpllm.run import _write_json
from cfpllm.score import kendall_tau_b, score_ranking, spearman


def _official():
    return [{"rank": rank, "team": f"Team {rank:02d}"} for rank in range(1, 26)]


def test_all_five_metrics_for_perfect_ranking():
    result = score_ranking([item["team"] for item in _official()], _official())
    assert result == {"spearman": 1.0, "kendall_tau_b": 1.0, "top_15_mae": 0.0, "top_12_overlap": "12/12", "seed_mae": 0.0}


def test_rank_correlations_for_reverse_ranking():
    official = list(range(1, 26))
    predicted = list(reversed(official))
    assert spearman(official, predicted) == -1.0
    assert kendall_tau_b(official, predicted) == -1.0


def test_missing_team_uses_rank_26_for_mae():
    ranking = [f"Team {rank:02d}" for rank in range(2, 26)]
    result = score_ranking(ranking, _official())
    assert result["top_15_mae"] == 2.6  # Team 01 contributes |26-1|; other top-15 teams move up one.
    assert result["seed_mae"] == 3.0


def test_spearman_reranks_with_average_ties_and_gaps():
    assert round(spearman([1, 2, 3, 4], [1, 4, 26, 26]), 6) == 0.948683


def test_score_accepts_pilot_and_an_official_team_outside_candidates(
    config, packet, tmp_path, monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_config", lambda args: config)
    packet["games"][0]["home_team"] = "Example State"
    _, packet_hash = write_packet(packet, config.packet_dir)
    directory = tmp_path / "pilot"
    _write_json(directory / "aggregates.json", {
        "release_id": config.release_id,
        "packet_sha256": packet_hash,
        "model": "fixture-model",
        "runs": {"balanced|cfp_off_ap_off|default": {"ranking": packet["candidates"][:25]}},
    })
    official = _official()
    official[0]["team"] = "Example State"
    _write_json(directory / "fixture-actuals.json", {"release_id": config.release_id, "rankings": official})

    assert cli.main([
        "score", "--official", str(directory / "fixture-actuals.json"),
        "--aggregates", str(directory / "aggregates.json"),
    ]) == 0
    result = json.loads((directory / "scores.json").read_text())
    assert result["runs"]["balanced|cfp_off_ap_off|default"]["seed_mae"] == 2.083333
    assert (directory / "report.md").exists()
