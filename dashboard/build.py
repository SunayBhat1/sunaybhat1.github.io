"""Build the static CFP dashboard and its allowlisted derived-data downloads."""

from argparse import ArgumentParser
from collections import Counter
from csv import DictWriter
from hashlib import sha256
from itertools import combinations
import json
from pathlib import Path
from shutil import copyfile
from statistics import mean
from zipfile import ZIP_DEFLATED, ZipFile

from cfpllm.aggregate import validate_ballot
from cfpllm.personas import PERSONA_TEXT, weekly_committee
from cfpllm.score import kendall_tau_b, load_official, predicted_ranks, score_ranking, spearman

MODEL_NAMES = {
    "luna": "GPT‑6 Luna", "haiku": "Claude Haiku 5.5", "gemini": "Gemini 3.8 Flash",
    "deepseek": "DeepSeek V4.1 Flash", "glm": "GLM 5.3 Flash", "minimax": "MiniMax M3.1 Flash",
}
PERSONA_NAMES = {
    "metrics_heavy": "Metrics heavy", "sec_tilt": "SEC tilt", "big_ten_tilt": "Big Ten tilt",
    "performatively_unbiased": "Performatively neutral", "eye_test": "Eye test", "ap_anchored": "AP anchored",
    "head_to_head_first": "Head-to-Head First",
}
CONDITION_NAMES = {
    "cfp_on_ap_on": "Previous CFP + AP", "cfp_on_ap_off": "Previous CFP only",
    "cfp_off_ap_on": "AP only", "cfp_off_ap_off": "Neither poll",
}
SWITCHES = {
    "ap": [("cfp_on_ap_on", "cfp_on_ap_off"), ("cfp_off_ap_on", "cfp_off_ap_off")],
    "cfp": [("cfp_on_ap_on", "cfp_off_ap_on"), ("cfp_on_ap_off", "cfp_off_ap_off")],
}


def read(path):
    return json.loads(path.read_text())


def json_file(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def analysis(packet, runs, ballots, official, members, persona_ids):
    teams = packet["candidates"]
    grouped = {}
    for b in ballots:
        grouped.setdefault(b["group"], []).append(b)
    reports = {}
    conference_of = {team: resume.get("record", {}).get("conference")
                     for team, resume in packet.get("resumes", {}).items()}
    counts = Counter(conf for conf in conference_of.values() if conf)
    conferences = sorted(counts, key=lambda conf: (-counts[conf], conf))
    references = {}
    for key, name in (("ap", "AP"), ("cfp", "Prior CFP")):
        entries = packet["rankings"].get(key, {}).get("entries", [])
        if len(entries) == 25:
            references[name] = entries
    if official:
        references["Official CFP"] = official
    keyed_ballots = {(b["group"], b["agent_id"]): b for b in ballots}
    for condition in CONDITION_NAMES:
        available = {m: runs[f"{m}|{condition}|0.3"]["ranking"] for m in MODEL_NAMES
                     if f"{m}|{condition}|0.3" in runs}
        agreement = {}
        for a, b in combinations(available, 2):
            left, right = available[a], available[b]
            v1, v2 = predicted_ranks(left, teams), predicted_ranks(right, teams)
            agreement[f"{a}|{b}"] = {
                "rho": round(spearman(v1, v2), 4), "tau": round(kendall_tau_b(v1, v2), 4),
                "overlap": len(set(left[:12]) & set(right[:12])),
            }
        tilt = {}
        for persona in persona_ids:
            for conference in conferences:
                deltas = []
                school_indices = [i for i, team in enumerate(teams) if conference_of.get(team) == conference]
                for model in MODEL_NAMES:
                    group = grouped.get(f"{model}|{condition}|0.3", [])
                    treatment = [predicted_ranks(b["ranking"], teams) for b in group if b["persona"] == persona]
                    others = [predicted_ranks(b["ranking"], teams) for b in group if b["persona"] != persona]
                    if treatment and others:
                        deltas.extend(mean(row[i] for row in others) - mean(row[i] for row in treatment)
                                      for i in school_indices)
                if deltas:
                    tilt[f"{persona}|{conference}"] = {"delta": round(mean(deltas), 2), "n": len(deltas)}
        consensus = Counter(team for ranking in available.values() for team in ranking[:12])
        reports[condition] = {
            "models": list(available), "agreement": agreement, "tilt": tilt, "conferences": conferences,
            "consensus": [{"team": team, "count": count} for team, count in
                          sorted(consensus.items(), key=lambda pair: (-pair[1], pair[0]))],
            "reference_scores": {model: {name: score_ranking(ranking, source) for name, source in references.items()}
                                 for model, ranking in available.items()},
        }
    sensitivity = {}
    for model in MODEL_NAMES:
        sensitivity[model] = {}
        for poll, pairs in SWITCHES.items():
            distances = []
            for condition_a, condition_b in pairs:
                for member in members:
                    a = keyed_ballots.get((f"{model}|{condition_a}|0.3", member.agent_id))
                    b = keyed_ballots.get((f"{model}|{condition_b}|0.3", member.agent_id))
                    if a and b:
                        distances.append(1 - kendall_tau_b(predicted_ranks(a["ranking"], teams),
                                                            predicted_ranks(b["ranking"], teams)))
            if distances:
                sensitivity[model][poll] = {"distance": round(mean(distances), 4), "n": len(distances)}
    return reports, sensitivity


def main():
    parser = ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--packet", required=True, type=Path)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--lock", type=Path)
    parser.add_argument("--official", type=Path)
    parser.add_argument("--unlisted", action="store_true", help="Request that search engines skip the page.")
    args = parser.parse_args()
    packet = read(args.packet)
    result = read(args.run / "aggregates.json")
    ballots = read(args.run / "valid-ballots.json")
    packet_hash = sha256(args.packet.read_bytes()).hexdigest()
    if result["packet_sha256"] != packet_hash:
        raise ValueError("Dashboard input packet and panel fingerprint differ.")
    members = weekly_committee(result.get("profile", "weekly-v1"))
    roles = {member.agent_id: member.persona for member in members}
    seats = Counter(roles.values())
    personas = {
        code: {"name": name, "description": PERSONA_TEXT[code], "seats": seats[code]}
        for code, name in PERSONA_NAMES.items() if code in seats
    }
    for b in ballots:
        validate_ballot(b, packet["candidates"], b["agent_id"], roles[b["agent_id"]])
    official = None
    if args.official:
        known = set(packet["candidates"]) | {g[key] for g in packet["games"] for key in ("home_team", "away_team")}
        date, official = load_official(args.official, sorted(known))
        if date != result["release_id"]:
            raise ValueError("Official rankings use a different release ID.")
    lock = read(args.lock) if args.lock else {"status": "local_artifacts"}
    if lock.get("packet_sha256", packet_hash) != packet_hash:
        raise ValueError("Lock fingerprint differs from the frozen packet.")
    meta = packet["meta"]
    source = {
        "site": "CollegeFootballData.com", "terms_url": "https://collegefootballdata.com/terms",
        "games_through": meta["games_through"], "prior_cfp_release": meta["prior_cfp_release"],
        "ap_week": meta.get("ap_week_tied_to_games"), "fetched_at_utc": meta["fetched_at_utc"],
        "game_count": len(packet["games"]), "candidate_count": len(packet["candidates"]),
        "source_data_distribution": "Source records omitted from the downloadable derived-data bundle.",
    }
    provenance = {key: val for key, val in result.items() if key != "runs"}
    provenance.update(source=source, lock=lock, official_status="available" if official else "pending_release")
    reports, sensitivity = analysis(packet, result["runs"], ballots, official, members, personas)
    model_names = dict(MODEL_NAMES)
    if result["model_settings"]["glm"]["id"].endswith("flashx"):
        model_names["glm"] = "GLM 5.3 FlashX"
    results = {
        "provenance": provenance, "model_names": model_names, "condition_names": CONDITION_NAMES,
        "personas": personas,
        "runs": result["runs"], "analysis": reports, "sensitivity": sensitivity,
    }
    comparison_path = args.run / "roster-comparison.json"
    if comparison_path.is_file():
        comparison = read(comparison_path)
        if (comparison["packet_sha256"] != packet_hash or comparison["release_id"] != result["release_id"]
                or comparison["run"]["profile"] != result.get("profile")):
            raise ValueError("The roster comparison belongs to a different run.")
        results["roster_comparison"] = comparison
    root = args.output
    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)
    source_dir = Path(__file__).resolve().parent
    for name in ("index.html", "app.js", "style.css", "mark.svg", "SKILL.md"):
        copyfile(source_dir / name, root / name)
    if args.unlisted:
        index = root / "index.html"
        html = index.read_text(encoding="utf-8")
        index.write_text(html.replace("<head>", '<head>\n  <meta name="robots" content="noindex, nofollow">', 1),
                         encoding="utf-8")
    usage = read(args.run / "usage.json")
    json_file(data / "provenance.json", provenance)
    json_file(data / "results.json", {**results, "ballots": ballots, "usage": usage})
    json_file(data / "valid-ballots.json", ballots)
    json_file(data / "usage.json", usage)
    with (data / "rankings.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = DictWriter(stream, fieldnames=["committee", "condition", "temperature_label", "rank", "team", "borda_points", "valid_ballots"])
        writer.writeheader()
        for name, run in result["runs"].items():
            model, condition, temperature = name.split("|")
            for n, team in enumerate(run["ranking"], 1):
                writer.writerow(dict(committee=model, condition=condition, temperature_label=temperature,
                                     rank=n, team=team, borda_points=run["points"][team], valid_ballots=run["valid_ballots"]))
    with ZipFile(data / "cfp-data.zip", "w", compression=ZIP_DEFLATED) as archive:
        for file in ("provenance.json", "results.json", "valid-ballots.json", "usage.json", "rankings.csv"):
            archive.write(data / file, file)
        archive.write(root / "SKILL.md", "SKILL.md")
    download_sizes = {path: (root / path).stat().st_size for path in ("SKILL.md", "data/results.json")}
    embedded = json.dumps({"results": results, "ballots": ballots, "download_sizes": download_sizes},
                          ensure_ascii=True, separators=(",", ":"))
    (root / "dataset.js").write_text("window.CFP_DATA = " + embedded + ";\n", encoding="utf-8")
    print(f"Built {root} from {len(ballots)} validated ballots.")


if __name__ == "__main__":
    main()
