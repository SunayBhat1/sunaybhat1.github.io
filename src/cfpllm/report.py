"""A deliberately modest Markdown report from locked aggregates and later scores."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any


METRICS = ("spearman", "kendall_tau_b", "top_15_mae", "top_12_overlap", "seed_mae")


def _number(value: object) -> float:
    if isinstance(value, str) and "/" in value:
        return float(value.split("/", 1)[0])
    return float(value)


def _summary(values: list[object], metric: str) -> str:
    numbers = [_number(value) for value in values]
    suffix = "/12" if metric == "top_12_overlap" else ""
    return f"{mean(numbers):.3f} ({min(numbers):.3f}–{max(numbers):.3f}){suffix}"


def write_report(path: str | Path, packet_hash: str, lock_tag: str | None, model: str | None, score_data: dict[str, Any]) -> Path:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for key, result in score_data.get("runs", {}).items():
        # key is mix|condition|temperature; seed summaries are intentionally grouped.
        parts = key.split("|")
        groups[" / ".join(parts[:2])].append(result)
    lines = [
        f"# CFP LLM Committee — {score_data.get('release_id', 'unknown')}",
        "",
        f"- Packet SHA-256: `{packet_hash}`",
        f"- Lock tag: `{lock_tag or 'not recorded'}`",
        f"- Model: `{model or 'not recorded'}`",
        "- Unranked predictor teams receive rank 26 for rank-error metrics.",
        "",
        "## Committee results (mean; range across temperatures)",
        "",
        "| Mix / condition | Spearman | Kendall tau-b | Top-15 MAE | Top-12 overlap | Seed MAE |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for group, results in sorted(groups.items()):
        lines.append("| " + group + " | " + " | ".join(_summary([item[key] for item in results], key) for key in METRICS) + " |")
    lines += ["", "## Baselines", "", "| Baseline | Spearman | Kendall tau-b | Top-15 MAE | Top-12 overlap | Seed MAE |", "|---|---:|---:|---:|---:|---:|"]
    for name, result in score_data.get("baselines", {}).items():
        lines.append("| " + name + " | " + " | ".join(str(result[key]) for key in METRICS) + " |")
    if score_data.get("runs"):
        best = max(score_data["runs"].items(), key=lambda item: float(item[1]["spearman"]))[0]
        lines += ["", f"Closest committee result by Spearman correlation: `{best}`. This is a descriptive comparison, not evidence of causal accuracy."]
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target
