from __future__ import annotations

from pathlib import Path

import pytest

from cfpllm.config import Config
from cfpllm.packet import write_packet


def teams() -> list[str]:
    return [f"Team {number:02d}" for number in range(1, 31)]


@pytest.fixture
def config() -> Config:
    return Config(
        season=2026,
        release_id="2026-11-24",
        games_through="2026-11-21",
        prior_cfp_release="2026-11-17",
        ap_week=None,
        candidate_cap=40,
        model="openai/gpt-4.1-mini",
        temperature_seeds=(0.3, 0.7, 1.0),
        max_budget_usd=40,
        timeout_s=120,
        max_retries=3,
        pricing_usd_per_million={"input": 0.4, "output": 1.6},
        assumed_output_tokens=1000,
    )


@pytest.fixture
def packet() -> dict:
    candidate_list = teams()
    return {
        "meta": {
            "release_id": "2026-11-24",
            "games_through": "2026-11-21",
            "prior_cfp_release": "2026-11-17",
            "fetched_at_utc": "2026-11-22T01:00:00+00:00",
            "endpoints_used": ["/games"],
            "notes": ["fixture"],
        },
        "games": [{"start_date": "2026-11-22T01:00:00+00:00", "home_team": "Team 01", "away_team": "Team 02"}],
        "rankings": {
            "ap": {"week": 13, "published_on": "2026-11-15", "entries": [{"rank": i, "team": t} for i, t in enumerate(candidate_list[:25], 1)]},
            "cfp": {"week": 13, "published_on": "2026-11-17", "entries": [{"rank": i, "team": t} for i, t in enumerate(candidate_list[:25], 1)]},
        },
        "ratings": {"sp_plus": {team: 100 - i for i, team in enumerate(candidate_list)}, "fpi": None, "sor": None},
        "candidates": candidate_list,
        "resumes": {team: {"record": {"overall": "10-1"}, "ap_rank": i + 1, "prior_cfp_rank": i + 1} for i, team in enumerate(candidate_list)},
    }


@pytest.fixture
def packet_path(tmp_path: Path, packet: dict) -> Path:
    path, _ = write_packet(packet, tmp_path)
    return path


def ballot(candidate_list: list[str], agent_id: str = "M01", persona: str = "metrics_heavy") -> dict:
    ranking = candidate_list[:25]
    return {"agent_id": agent_id, "persona": persona, "ranking": ranking, "rationales": {team: f"Fact about {team}" for team in ranking[:12]}}
