"""Exact, tool-free prompts. Condition slices remove fields rather than asking agents to ignore them."""

from __future__ import annotations

from copy import deepcopy
import json
from typing import Any

from .packet import local_date
from .personas import Member, PERSONA_TEXT


CONDITIONS: dict[str, dict[str, bool]] = {
    "cfp_on_ap_on": {"cfp": True, "ap": True},
    "cfp_on_ap_off": {"cfp": True, "ap": False},
    "cfp_off_ap_on": {"cfp": False, "ap": True},
    "cfp_off_ap_off": {"cfp": False, "ap": False},
}

SCHEMA = {
    "agent_id": "M01",
    "persona": "metrics_heavy",
    "ranking": ["School A", "... exactly 25 candidate names ..."],
    "rationales": {"School A": "packet-fact rationale for rank 1 through 12"},
}

# Repeat the field names once for the entire slate. The upstream game ID has
# no ranking meaning, so it stays in the frozen packet for provenance.
GAME_COLUMNS = (
    "week", "start_date", "home_team", "away_team", "home_points", "away_points",
    "neutral_site", "home_conference", "away_conference",
    "home_classification", "away_classification",
)


def packet_slice(packet: dict[str, Any], condition: str) -> dict[str, Any]:
    """Return only the information condition permits, including in each resume."""
    if condition not in CONDITIONS:
        raise ValueError(f"unknown condition: {condition}")
    permitted = CONDITIONS[condition]
    output = deepcopy(packet)
    output.pop("meta", None)
    # Candidate membership is fixed across treatments. The original ordering
    # starts with the AP poll, so use a common alphabetical order for all four.
    output["candidates"] = sorted(output["candidates"])
    rankings = output.get("rankings", {})
    if not permitted["ap"]:
        rankings.pop("ap", None)
    if not permitted["cfp"]:
        rankings.pop("cfp", None)
    if not rankings:
        output.pop("rankings", None)
    for resume in output.get("resumes", {}).values():
        if not permitted["ap"]:
            resume.pop("ap_rank", None)
        if not permitted["cfp"]:
            resume.pop("prior_cfp_rank", None)
        if "ranked_opponents" in resume:
            resume["ranked_opponents"] = {kind: rows for kind, rows in resume["ranked_opponents"].items()
                                           if permitted[kind]}
            if not resume["ranked_opponents"]:
                del resume["ranked_opponents"]
    return output


def system_prompt(member: Member, *, ordered_rationales: bool = False, reassess_polls: bool = False) -> str:
    schema = SCHEMA
    if ordered_rationales:
        schema = {
            "agent_id": member.agent_id, "persona": member.persona,
            "ranking": ["exactly 25 canonical school names"],
            "rationales": ["exactly 12 brief justifications, in ranking order"],
        }
    rationale_instruction = (
        "Return rationales as an array of 12 short, original, packet-based sentences in top-12 ranking order."
        if ordered_rationales else
        "For exactly the first 12, give a 1-3 sentence rationale citing packet facts only."
    )
    reassess = (
        "Produce a new CFP top 25 accounting for all results through the supplied game cutoff. "
        "Treat any visible polls as dated reference points. Identify major results since those polls "
        "and explain how they change a team's case when relevant.",
    ) if reassess_polls else ()
    return "\n".join((
        "You are one member of the 2026-27 College Football Playoff Selection Committee.",
        "The playoff has 12 teams, straight seeding, and byes for the top four.",
        "Use only the supplied frozen packet. If it disagrees with your memory, the packet wins.",
        *reassess,
        "Use body of work, strength of schedule, head-to-head, common opponents, and other relevant on-field factors.",
        "Evaluate teams rather than conferences, though packet schedule context may matter.",
        "Do not infer or use withheld ranking information, web knowledge, tools, or outside facts.",
        "Rank exactly 25 provided candidates: no ties, duplicates, or write-ins.",
        rationale_instruction,
        "Return only a JSON object matching this schema; no Markdown fences.",
        json.dumps(schema, separators=(",", ":")),
        f"Your stable agent id is {member.agent_id}; your persona is {member.persona}.",
        PERSONA_TEXT[member.persona],
    ))


def user_prompt(
    packet: dict[str, Any], condition: str, *, opening_spreads: dict[int, float] | None = None,
    include_packet_odds: bool = True,
) -> str:
    evidence = packet_slice(packet, condition)
    games = evidence.pop("games", [])
    packet_spreads = evidence.pop("opening_spreads", None)
    if include_packet_odds and opening_spreads is None and packet_spreads is not None:
        opening_spreads = {int(game_id): spread for game_id, spread in packet_spreads.items()}
    columns = GAME_COLUMNS
    resume_note = ""
    if packet["meta"].get("resume_schema") == 2:
        # Conferences repeat hundreds of times in the old game table.
        columns = ("week", "start_date", "home_team", "away_team", "home_points", "away_points", "neutral_site",
                   "home_classification", "away_classification")
        evidence["games_through"] = packet["meta"]["games_through"]
        resume_note = (
            "Game dates are Eastern. Overall records include FCS and FBS opponents. FBS records, schedule "
            "strength, and scoring summaries use games between FBS teams. Ranked-opponent rows contain game "
            "date, opponent, candidate score first, venue (H/A/N), reference-poll rank, and kickoff rank. "
            "A null kickoff rank means either unranked or no dated poll available before the game.\n"
        )
    rows = [[local_date(game[column]).isoformat() if column == "start_date" and resume_note else game.get(column)
             for column in columns] for game in games]
    odds_note = ""
    if opening_spreads is not None:
        columns += ("opening_home_spread",)
        for row, game in zip(rows, games, strict=True):
            row.append(opening_spreads.get(game["id"]))
        odds_note = (
            "Opening_home_spread is the median available pregame opening spread for the home team. "
            "A negative value means the home team was favored. For example, with a spread of -7, "
            "a home win by 17 beat opening expectations by 10 points.\n"
        )
    evidence["games"] = {"columns": columns, "rows": rows}
    return (
        "Frozen packet (this is all the evidence you may use). Each games row follows games.columns in order. "
        "The home and away labels identify score columns; neutral_site takes precedence for venue. "
        "Null means unavailable. Candidates are listed alphabetically.\n"
        + resume_note + odds_note + json.dumps(evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    )
