"""Command line entry point for the experiment."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from .config import load_config
from .fetch import FetchError, fetch_packet
from .lint import PacketLintError, lint_packet
from .lock import LockError, git_lock, write_manifest
from .packet import default_packet_path, read_packet
from .report import write_report
from .run import RunError, estimate, run_committee, _read_json, _write_json
from .score import load_official, score_all


def _config(args: argparse.Namespace):
    return load_config(args.config)


def _packet_path(args: argparse.Namespace, config) -> Path:
    return Path(getattr(args, "packet", None) or default_packet_path(config.release_id))


def _print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def _open_pr(release_id: str) -> str:
    """Use gh only after artifacts are pushed; returns a useful command on failure."""
    current = subprocess.run(["git", "branch", "--show-current"], text=True, capture_output=True, check=False).stdout.strip()
    existing = subprocess.run(["gh", "pr", "list", "--head", current, "--base", "main", "--json", "url", "--limit", "1"], text=True, capture_output=True, check=False)
    if existing.returncode == 0:
        try:
            rows = json.loads(existing.stdout)
            if rows:
                return f"PR already open: {rows[0]['url']}"
        except (ValueError, KeyError):
            pass
    made = subprocess.run(["gh", "pr", "create", "--base", "main", "--head", current, "--title", f"CFP LLM committee {release_id}", "--body", f"Frozen packet and locked committee ballots for {release_id}."], text=True, capture_output=True, check=False)
    if made.returncode:
        return f"PR was not opened: {made.stderr.strip()}\nRun: gh pr create --base main --head {current} --title 'CFP LLM committee {release_id}'"
    return f"PR opened: {made.stdout.strip()}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cfpllm", description="Frozen-packet CFP LLM committee experiment")
    parser.add_argument("--config", default="config.yaml", help="YAML configuration path")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("fetch", help="pull a frozen CFBD packet")
    lint_cmd = commands.add_parser("lint", help="fail closed on packet leakage or integrity")
    lint_cmd.add_argument("packet", nargs="?", default=None)
    estimate_cmd = commands.add_parser("estimate", help="estimate model calls/tokens/cost without spend")
    estimate_cmd.add_argument("--packet", default=None)
    run_cmd = commands.add_parser("run", help="run all committee treatments with cache/retries")
    run_cmd.add_argument("--packet", default=None)
    lock_cmd = commands.add_parser("lock", help="write manifest, commit/tag/push a completed run")
    lock_cmd.add_argument("--packet", default=None)
    lock_cmd.add_argument("--no-git", action="store_true", help="write manifest only (not a timestamp proof)")
    score_cmd = commands.add_parser("score", help="score aggregates against official rankings")
    score_cmd.add_argument("--official", required=True)
    score_cmd.add_argument("--aggregates", help="score a specific run, such as a pilot")
    report_cmd = commands.add_parser("report", help="write a Markdown report from an existing score")
    report_cmd.add_argument("--scores", default=None)

    args = parser.parse_args(argv)
    try:
        config = _config(args)
        if args.command == "fetch":
            packet, digest = fetch_packet(config)
            print(f"Wrote {packet}\\nSHA-256 {digest}")
        elif args.command == "lint":
            packet = Path(args.packet or default_packet_path(config.release_id))
            lint_packet(packet, config)
            print(f"PASS {packet}")
        elif args.command == "estimate":
            packet = _packet_path(args, config)
            lint_packet(packet, config)
            _print_json(estimate(config, read_packet(packet)))
        elif args.command == "run":
            result = run_committee(config, _packet_path(args, config))
            _print_json(result["estimate"])
            print(f"Wrote {config.ballot_dir / 'aggregates.json'}")
        elif args.command == "lock":
            _, manifest = write_manifest(config, _packet_path(args, config))
            if args.no_git:
                print("Manifest written only; --no-git is not a completed timestamp proof.")
            else:
                tag = git_lock(config, manifest["packet_sha256"])
                print(f"Pushed lock tag {tag}")
                print(_open_pr(config.release_id))
        elif args.command == "score":
            packet_path = default_packet_path(config.release_id)
            lint_packet(packet_path, config)
            packet = read_packet(packet_path)
            packet_hash = sha256(packet_path.read_bytes()).hexdigest()
            aggregate_path = Path(args.aggregates) if args.aggregates else config.ballot_dir / "aggregates.json"
            aggregates = _read_json(aggregate_path)
            if aggregates.get("release_id") != config.release_id:
                raise ValueError("Aggregates do not match the configured release.")
            if aggregates.get("packet_sha256", packet_hash) != packet_hash:
                raise ValueError("Aggregates do not match the frozen packet.")
            canonical_names = set(packet["candidates"])
            for game in packet["games"]:
                canonical_names.update(game[key] for key in ("home_team", "away_team") if game.get(key))
            official_release, official = load_official(args.official, sorted(canonical_names))
            if official_release != config.release_id:
                raise ValueError(f"Official release {official_release!r} does not match {config.release_id!r}.")
            scores = score_all(packet, aggregates, official)
            score_path = aggregate_path.parent / "scores.json"
            _write_json(score_path, scores)
            manifest_path = aggregate_path.parent / "manifest.json"
            manifest = _read_json(manifest_path) if manifest_path.exists() else {}
            report_path = aggregate_path.parent / "report.md" if args.aggregates else Path("reports") / f"{config.release_id}.md"
            report = write_report(report_path, packet_hash, manifest.get("lock_tag"), aggregates.get("model", manifest.get("model", config.model)), scores)
            print(f"Wrote {score_path} and {report}")
        elif args.command == "report":
            score_path = Path(args.scores or config.ballot_dir / "scores.json")
            scores = _read_json(score_path)
            manifest = _read_json(config.ballot_dir / "manifest.json") if (config.ballot_dir / "manifest.json").exists() else {}
            report = write_report(Path("reports") / f"{config.release_id}.md", manifest.get("packet_sha256", "not locked"), manifest.get("lock_tag"), manifest.get("model", config.model), scores)
            print(f"Wrote {report}")
        return 0
    except (FetchError, PacketLintError, RunError, LockError, ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2 if args.command in {"estimate", "run"} and "exceeds max_budget" in str(exc) else 1


if __name__ == "__main__":
    raise SystemExit(main())
