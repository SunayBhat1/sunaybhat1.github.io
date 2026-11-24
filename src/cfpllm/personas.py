"""Stable committee compositions and deliberately explicit treatment prompts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Member:
    agent_id: str
    persona: str


PERSONA_TEXT: dict[str, str] = {
    "metrics_heavy": (
        "Weight SP+, FPI, efficiency-style ratings, schedule strength, and measurable resume facts heavily. "
        "Distrust brand, reputation, and unsupported claims about how a team looked."
    ),
    "sec_tilt": (
        "Give SEC teams a systematic benefit of the doubt when the packet's schedule and quality-win facts support it. "
        "Do not invent conference strength or facts absent from the packet."
    ),
    "big_ten_tilt": (
        "Give Big Ten teams a systematic benefit of the doubt when the packet's schedule and quality-win facts support it. "
        "Do not invent conference strength or facts absent from the packet."
    ),
    "performatively_unbiased": (
        "Present yourself as scrupulously neutral and explicitly note uncertainty where appropriate, but still make a decisive full ranking. "
        "This is a treatment; follow the packet rather than outside assumptions."
    ),
    "eye_test": (
        "Emphasize margins, styles of wins and losses, and how games were won only when those box-score facts are in the packet. "
        "Do not invent pundit views, television commentary, or facts not supplied."
    ),
    "ap_anchored": (
        "When an AP poll is supplied, begin from it and adjust using the packet's resume evidence. "
        "When no AP data is supplied, fall back to resumes and make that clear in rationales."
    ),
    "head_to_head_first": (
        "Give completed head-to-head results the most weight when two teams have comparable resumes. "
        "Prefer the winner when overall record, schedule strength, and quality of wins are broadly similar. "
        "If resumes differ substantially, explain which resume evidence outweighs the direct result. "
        "Resolve split series, cycles, and matchups without a clear direct winner using overall record, "
        "schedule strength, and quality of wins. Do not infer a head-to-head result from common opponents. "
        "Cite the direct game when it drives a rationale."
    ),
    "brand_bias": (
        "When two teams have closely comparable resumes, give a modest benefit of the doubt to "
        "an eligible member of this fixed treatment list: Alabama, Michigan, Nebraska, Notre Dame, "
        "Ohio State, Oklahoma, Texas, and USC. Use on-field evidence for clear resume differences. "
        "If the brand preference breaks a tie in your top 12, say so alongside the relevant packet facts. "
        "Treat this list as a voting preference only and do not add any historical facts."
    ),
    "neutral_protocol": (
        "Apply the official criteria as written: body of work, strength of schedule, head-to-head, common opponents, "
        "and other relevant on-field factors. Do not apply conference preference, AP loyalty, or performed neutrality."
    ),
}


def committee_mix(name: str) -> list[Member]:
    if name == "balanced":
        personas = [
            "metrics_heavy", "metrics_heavy", "metrics_heavy", "sec_tilt", "sec_tilt",
            "big_ten_tilt", "big_ten_tilt", "performatively_unbiased", "performatively_unbiased",
            "eye_test", "eye_test", "ap_anchored", "ap_anchored",
        ]
        return [Member(f"M{index:02d}", persona) for index, persona in enumerate(personas, 1)]
    if name == "all_neutral":
        return [Member(f"N{index:02d}", "neutral_protocol") for index in range(1, 14)]
    raise ValueError(f"unknown committee mix: {name}")


WEEKLY_PROFILES = ("weekly-v1", "weekly-v2", "weekly-v3")
DEFAULT_WEEKLY_PROFILE = WEEKLY_PROFILES[-1]
BRAND_SEAT = Member("M14", "brand_bias")


def weekly_committee(profile: str) -> list[Member]:
    """Resolve the historical seat assignments for a weekly panel."""
    if profile not in WEEKLY_PROFILES:
        raise ValueError(f"unknown weekly panel profile: {profile}")
    members = committee_mix("balanced")
    if profile == "weekly-v1":
        return members
    updated = [
        Member(member.agent_id, "head_to_head_first") if member.agent_id in {"M03", "M09"} else member
        for member in members
    ]
    if profile == "weekly-v3":
        updated.append(BRAND_SEAT)
    return updated


def mixes() -> tuple[str, ...]:
    return ("balanced", "all_neutral")


def mix_map() -> dict[str, list[dict[str, str]]]:
    return {name: [member.__dict__ for member in committee_mix(name)] for name in mixes()}
