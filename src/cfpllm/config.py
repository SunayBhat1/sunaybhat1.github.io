"""Configuration loading; all paths are relative to the repository root."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os
from typing import Any

import yaml


@dataclass(frozen=True)
class Config:
    season: int
    release_id: str
    games_through: str
    prior_cfp_release: str
    ap_week: int | None
    candidate_cap: int
    model: str
    temperature_seeds: tuple[float, ...]
    max_budget_usd: float
    timeout_s: int
    max_retries: int
    pricing_usd_per_million: dict[str, float]
    assumed_output_tokens: int
    evidence_through: str | None = None
    poll_dates: dict[str, dict[int, str]] = field(default_factory=dict)

    @property
    def packet_dir(self) -> Path:
        return Path("data/packets") / self.release_id

    @property
    def ballot_dir(self) -> Path:
        return Path("data/ballots") / self.release_id


def load_config(path: str | Path = "config.yaml") -> Config:
    with Path(path).open(encoding="utf-8") as handle:
        raw: dict[str, Any] = yaml.safe_load(handle) or {}
    required = {
        "season", "release_id", "games_through", "prior_cfp_release", "candidate_cap",
        "model", "temperature_seeds", "max_budget_usd", "timeout_s", "max_retries",
    }
    missing = sorted(required - raw.keys())
    if missing:
        raise ValueError(f"config is missing: {', '.join(missing)}")
    price = raw.get("pricing_usd_per_million", {"input": 0.40, "output": 1.60})
    return Config(
        season=int(raw["season"]),
        release_id=str(raw["release_id"]),
        games_through=str(raw["games_through"]),
        prior_cfp_release=str(raw["prior_cfp_release"]),
        ap_week=None if raw.get("ap_week") is None else int(raw["ap_week"]),
        candidate_cap=int(raw["candidate_cap"]),
        model=os.getenv("CFPLLM_MODEL") or os.getenv("OPENAI_MODEL") or str(raw["model"]),
        temperature_seeds=tuple(float(value) for value in raw["temperature_seeds"]),
        max_budget_usd=float(raw["max_budget_usd"]),
        timeout_s=int(raw["timeout_s"]),
        max_retries=int(raw["max_retries"]),
        pricing_usd_per_million={"input": float(price["input"]), "output": float(price["output"])},
        assumed_output_tokens=int(raw.get("assumed_output_tokens", 1700)),
        evidence_through=str(raw["evidence_through"]) if raw.get("evidence_through") else None,
        poll_dates={
            kind: {int(week): str(published) for week, published in dates.items()}
            for kind, dates in (raw.get("poll_dates") or {}).items()
        },
    )


def provider_from_environment() -> tuple[str, str, str]:
    """Return provider, base URL and key; OpenRouter deliberately wins if both exist."""
    if key := os.getenv("OPENROUTER_API_KEY"):
        return "openrouter", "https://openrouter.ai/api/v1", key
    if key := os.getenv("OPENAI_API_KEY"):
        return "openai", "https://api.openai.com/v1", key
    raise RuntimeError("No model key: set OPENROUTER_API_KEY or OPENAI_API_KEY in the environment.")
