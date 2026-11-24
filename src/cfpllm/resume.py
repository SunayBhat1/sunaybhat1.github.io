"""Describe a candidate's schedule with pre-release, time-aware opponent context."""

from datetime import date
from statistics import mean

from .packet import local_date


def dated_polls(polls, cutoff, dates):
    """Select polls with an explicit publication date within the evidence window."""
    dated = []
    for poll in polls:
        publication = poll.get("published_on") or dates.get(poll["week"])
        if publication and local_date(publication) <= cutoff and len(poll["entries"]) == 25:
            dated.append({
                **poll, "published_on": str(publication),
                "publication_date_source": "CFBD" if poll.get("published_on") else "verified release calendar",
            })
    return sorted(dated, key=lambda poll: local_date(poll["published_on"]))


def team_game_results(team, games):
    results = []
    for game in games:
        if team not in (game["home_team"], game["away_team"]):
            continue
        home = game["home_team"] == team
        ours = game["home_points"] if home else game["away_points"]
        theirs = game["away_points"] if home else game["home_points"]
        if not isinstance(ours, int) or not isinstance(theirs, int):
            continue
        opponent = game["away_team"] if home else game["home_team"]
        site = "N" if game["neutral_site"] else ("H" if home else "A")
        played = local_date(game["start_date"])
        results.append((played, opponent, ours, theirs, site))
    return sorted(results)


def enrich_resume(team, resume, overall_record, games, fbs_games, history):
    overall = team_game_results(team, games)
    fbs = team_game_results(team, fbs_games)
    margins = [ours - theirs for _, _, ours, theirs, _ in fbs]
    resume["record"] = {
        **resume["record"], "fbs": resume["record"]["overall"],
        "overall": f"{overall_record['wins']}-{overall_record['losses']}",
    }
    resume["fbs_scoring"] = {
        "mean_point_margin": round(mean(margins), 1) if margins else None,
        "one_score_wins": sum(0 < margin <= 8 for margin in margins),
        "one_score_losses": sum(-8 <= margin < 0 for margin in margins),
        "road_or_neutral_wins": sum(ours > theirs and site in ("A", "N") for _, _, ours, theirs, site in fbs),
    }
    resume["ranked_opponents"] = {}
    for kind, polls in history.items():
        snapshots = [
            (local_date(poll["published_on"]), {r["team"]: r["rank"] for r in poll["entries"]})
            for poll in polls
        ]
        if not snapshots:
            continue
        current = snapshots[-1][1]
        rows = []
        for played, opponent, ours, theirs, site in overall:
            kickoff = next((ranks for published, ranks in reversed(snapshots)
                            if 0 < (played - published).days <= 7), {})
            now_rank, then_rank = current.get(opponent), kickoff.get(opponent)
            if now_rank is not None or then_rank is not None:
                rows.append([played.isoformat(), opponent, f"{ours}-{theirs}", site, now_rank, then_rank])
        resume["ranked_opponents"][kind] = rows
    return resume
