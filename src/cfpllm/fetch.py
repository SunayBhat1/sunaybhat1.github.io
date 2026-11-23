"""CollegeFootballData-only acquisition and compact resume construction."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timezone
import os
from pathlib import Path
from typing import Any

import requests

from .config import Config
from .packet import local_date, write_packet


API_BASE = "https://api.collegefootballdata.com"


class FetchError(RuntimeError):
    pass


def _get(session: requests.Session, endpoint: str, params: dict[str, Any], timeout: int) -> Any:
    try:
        response = session.get(f"{API_BASE}{endpoint}", params=params, timeout=timeout)
    except requests.RequestException as exc:
        raise FetchError(f"CFBD GET {endpoint} failed: {exc}") from exc
    if response.status_code >= 400:
        raise FetchError(f"CFBD GET {endpoint} returned HTTP {response.status_code}: {response.text[:300]}")
    try:
        return response.json()
    except ValueError as exc:
        raise FetchError(f"CFBD GET {endpoint} did not return JSON") from exc


def _optional_get(session: requests.Session, endpoint: str, config: Config, notes: list[str], endpoints: list[str]) -> Any:
    try:
        value = _get(session, endpoint, {"year": config.season}, config.timeout_s)
        endpoints.append(endpoint)
        return value
    except FetchError as exc:
        notes.append(f"Optional {endpoint} omitted: {exc}")
        return []


def _field(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in row and row[name] is not None:
            return row[name]
    return None


def _rankings(raw: list[dict[str, Any]], poll_fragment: str, requested_week: int | None = None) -> dict[str, Any] | None:
    """Normalise CFBD's week/polls response without retaining unselected polls."""
    choices: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    for snapshot in raw:
        week = int(snapshot.get("week", 0) or 0)
        for poll in snapshot.get("polls", []):
            name = str(poll.get("poll") or poll.get("name") or "")
            if poll_fragment.lower() in name.lower():
                choices.append((week, snapshot, poll))
    if not choices:
        return None
    if requested_week is not None:
        exact = [choice for choice in choices if choice[0] == requested_week]
        if not exact:
            return None
        choices = exact
    week, snapshot, poll = max(choices, key=lambda item: item[0])
    entries = []
    for rank in poll.get("ranks", []):
        team = _field(rank, "school", "team")
        position = _field(rank, "rank")
        if team and position:
            entries.append({"rank": int(position), "team": str(team), "points": _field(rank, "points")})
    entries.sort(key=lambda item: item["rank"])
    return {
        "week": week,
        "published_on": _field(poll, "date", "publishedOn") or _field(snapshot, "date", "publishedOn"),
        "source_poll": poll.get("poll") or poll.get("name"),
        "entries": entries,
    }


def _game(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": _field(row, "id"),
        "week": _field(row, "week"),
        "start_date": _field(row, "startDate", "start_date", "date"),
        "home_team": _field(row, "homeTeam", "home_team"),
        "away_team": _field(row, "awayTeam", "away_team"),
        "home_points": _field(row, "homePoints", "home_points"),
        "away_points": _field(row, "awayPoints", "away_points"),
        "neutral_site": bool(_field(row, "neutralSite", "neutral_site") or False),
        "home_conference": _field(row, "homeConference", "home_conference"),
        "away_conference": _field(row, "awayConference", "away_conference"),
        "home_classification": _field(row, "homeClassification", "home_classification"),
        "away_classification": _field(row, "awayClassification", "away_classification"),
    }


def _is_fbs_game(game: dict[str, Any]) -> bool:
    values = {str(game.get("home_classification") or "").lower(), str(game.get("away_classification") or "").lower()}
    # Old CFBD responses omit classification; retain rather than silently discard all games.
    return not values - {"", "fbs"}


def _records_from_games(games: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, set[str]]]:
    records: dict[str, dict[str, Any]] = defaultdict(lambda: {"wins": 0, "losses": 0, "conference": None})
    opponents: dict[str, set[str]] = defaultdict(set)
    for game in games:
        home, away = game["home_team"], game["away_team"]
        if not home or not away:
            continue
        records[home]["conference"] = records[home]["conference"] or game.get("home_conference")
        records[away]["conference"] = records[away]["conference"] or game.get("away_conference")
        opponents[home].add(away)
        opponents[away].add(home)
        hp, ap = game.get("home_points"), game.get("away_points")
        if hp is None or ap is None:
            continue
        if hp > ap:
            records[home]["wins"] += 1
            records[away]["losses"] += 1
        elif ap > hp:
            records[away]["wins"] += 1
            records[home]["losses"] += 1
    return dict(records), opponents


def _ratings_by_team(rows: list[dict[str, Any]]) -> dict[str, float]:
    values: dict[str, float] = {}
    for row in rows if isinstance(rows, list) else []:
        team = _field(row, "team", "school")
        rating = _field(row, "rating", "spRating", "fpi")
        if team is not None and rating is not None:
            try:
                values[str(team)] = float(rating)
            except (TypeError, ValueError):
                pass
    return values


def _resume(
    team: str, candidates: set[str], games: list[dict[str, Any]], records: dict[str, dict[str, Any]],
    opponents: dict[str, set[str]], sp: dict[str, float], fpi: dict[str, float], ap: dict[str, int], cfp: dict[str, int],
) -> dict[str, Any]:
    record = records.get(team, {"wins": 0, "losses": 0, "conference": None})
    opps = opponents.get(team, set())
    rates = []
    for opponent in opps:
        other = records.get(opponent, {})
        w, l = int(other.get("wins", 0)), int(other.get("losses", 0))
        if w + l:
            rates.append(w / (w + l))
    sos = round(sum(rates) / len(rates), 4) if rates else None
    notable_wins, notable_losses, h2h = [], [], []
    for game in games:
        if team not in (game.get("home_team"), game.get("away_team")):
            continue
        opponent = game["away_team"] if game["home_team"] == team else game["home_team"]
        ours = game["home_points"] if game["home_team"] == team else game["away_points"]
        theirs = game["away_points"] if game["home_team"] == team else game["home_points"]
        if ours is None or theirs is None:
            continue
        site = "neutral" if game["neutral_site"] else ("home" if game["home_team"] == team else "away")
        result = {"opponent": opponent, "score": f"{ours}-{theirs}", "site": site}
        if ours > theirs:
            notable_wins.append(result)
        elif theirs > ours:
            notable_losses.append(result)
        if opponent in candidates:
            h2h.append({**result, "result": "win" if ours > theirs else "loss" if ours < theirs else "tie"})
    quality = lambda item: records.get(item["opponent"], {}).get("wins", 0)
    notable_wins.sort(key=quality, reverse=True)
    notable_losses.sort(key=quality, reverse=True)
    common: list[dict[str, Any]] = []
    for peer in sorted(candidates - {team}):
        shared = sorted(opps & opponents.get(peer, set()))
        if shared:
            common.append({"team": peer, "opponents": shared[:4]})
    return {
        "record": {"overall": f"{record['wins']}-{record['losses']}", "conference": record.get("conference")},
        "fbs_sos_proxy": sos,
        "notable_wins": notable_wins[:8],
        "notable_losses": notable_losses[:8],
        "head_to_head_among_candidates": h2h,
        "common_opponent_notes": common[:12],
        "sp_plus": sp.get(team),
        "fpi": fpi.get(team),
        "ap_rank": ap.get(team),
        "prior_cfp_rank": cfp.get(team),
    }


def fetch_packet(config: Config) -> tuple[Path, str]:
    key = os.getenv("CFBD_API_KEY")
    if not key:
        raise FetchError("CFBD_API_KEY is required for fetch; it was not set.")
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {key}", "Accept": "application/json"})
    endpoints = ["/games", "/records", "/rankings"]
    raw_games = _get(session, "/games", {"year": config.season, "seasonType": "regular", "classification": "fbs"}, config.timeout_s)
    _get(session, "/records", {"year": config.season}, config.timeout_s)  # endpoint is retained in provenance; games are canonical records
    raw_rankings = _get(session, "/rankings", {"year": config.season, "seasonType": "regular"}, config.timeout_s)
    notes: list[str] = [
        "FBS SOS proxy is the mean final-to-cutoff win percentage of each FBS opponent in this packet; SOR is null.",
        "Only selected AP and prior CFP poll entries are retained; raw rankings responses are never copied into the packet.",
    ]
    sp_rows = _optional_get(session, "/ratings/sp", config, notes, endpoints)
    fpi_rows = _optional_get(session, "/ratings/fpi", config, notes, endpoints)
    games = [_game(row) for row in raw_games if isinstance(row, dict)]
    games = [game for game in games if _is_fbs_game(game) and local_date(game["start_date"]) <= date.fromisoformat(config.games_through)]
    if not games:
        raise FetchError("CFBD returned no FBS games through the configured cutoff; packet not written.")
    game_week = max(int(game.get("week") or 0) for game in games)
    ap_poll = _rankings(raw_rankings, "AP", config.ap_week or game_week)
    if not ap_poll or len(ap_poll["entries"]) < 25:
        raise FetchError(f"Could not find a 25-team AP poll for CFBD week {config.ap_week or game_week}; packet not written.")
    # CFBD currently calls this poll "Playoff Committee Rankings"; older payloads used
    # "College Football Playoff" or "CFP", so match the stable shared term.
    cfp_poll = _rankings(raw_rankings, "Playoff", config.ap_week or game_week) or _rankings(raw_rankings, "CFP", config.ap_week or game_week)
    if cfp_poll is None:
        raise FetchError(f"Could not find the prior CFP poll for CFBD week {config.ap_week or game_week}; packet not written.")
    # CFBD ranking payloads historically expose week but not publication date. The configured date is an asserted selection cutoff,
    # never a fetched result; the API week is recorded separately for audit.
    if not cfp_poll.get("published_on"):
        cfp_poll["published_on"] = config.prior_cfp_release
        cfp_poll["publication_date_source"] = "configured prior_cfp_release (CFBD response had no date)"
    if not ap_poll.get("published_on"):
        ap_poll["publication_date_source"] = "CFBD week association (CFBD response had no date)"
    records, opponents = _records_from_games(games)
    sp, fpi = _ratings_by_team(sp_rows), _ratings_by_team(fpi_rows)
    ap_names = [entry["team"] for entry in ap_poll["entries"]]
    extra = [name for name, row in records.items() if int(row.get("losses", 0)) <= 2 and name not in ap_names]
    extra.sort(key=lambda name: (records[name]["losses"], -(0 if records[name].get("wins") is None else records[name]["wins"] / max(1, records[name]["wins"] + records[name]["losses"])), -(sp.get(name, float("-inf"))), name))
    candidates = (ap_names + extra)[: config.candidate_cap]
    if len(candidates) < 25:
        raise FetchError("Candidate construction produced fewer than 25 teams; packet not written.")
    ap_map = {entry["team"]: entry["rank"] for entry in ap_poll["entries"]}
    cfp_map = {entry["team"]: entry["rank"] for entry in cfp_poll["entries"]}
    candidate_set = set(candidates)
    packet = {
        "meta": {
            "release_id": config.release_id,
            "season": config.season,
            "games_through": config.games_through,
            "prior_cfp_release": config.prior_cfp_release,
            "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
            "endpoints_used": endpoints,
            "notes": notes,
            "ap_week_tied_to_games": game_week,
            "candidate_rule": "AP top 25, then FBS teams with <=2 losses; overflow ordered by fewest losses, better FBS SOS proxy, SP+ and alphabetically.",
        },
        "games": games,
        "rankings": {"ap": ap_poll, "cfp": cfp_poll},
        "ratings": {"sp_plus": sp, "fpi": fpi if fpi else None, "sor": None},
        "candidates": candidates,
        "resumes": {name: _resume(name, candidate_set, games, records, opponents, sp, fpi, ap_map, cfp_map) for name in candidates},
    }
    return write_packet(packet, config.packet_dir)
