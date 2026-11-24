"""Fail-closed checks protecting the frozen packet from post-cutoff leakage."""

from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterator

from .config import Config
from .packet import canonical_bytes, local_date


class PacketLintError(ValueError):
    pass


def _walk(value: Any, trail: str = "") -> Iterator[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            next_trail = f"{trail}.{key}" if trail else str(key)
            yield from _walk(child, next_trail)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, f"{trail}[{index}]")
    else:
        yield trail, value


def _poll_date(poll: dict[str, Any]) -> str | None:
    for name in ("published_on", "date", "poll_date", "release_date"):
        if poll.get(name):
            return str(poll[name])
    return None


def lint_errors(packet_path: str | Path, config: Config) -> list[str]:
    path = Path(packet_path)
    errors: list[str] = []
    if not path.exists():
        return [f"packet not found: {path}"]
    try:
        raw = path.read_bytes()
        packet = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [f"packet is not valid UTF-8 JSON: {exc}"]
    canonical = canonical_bytes(packet)
    if raw != canonical:
        errors.append("packet.json is not canonical JSON (sorted compact UTF-8 bytes required)")
    sidecar = path.with_name("packet.sha256")
    if not sidecar.exists():
        errors.append(f"missing SHA-256 sidecar: {sidecar}")
    else:
        contents = sidecar.read_text(encoding="ascii").strip()
        expected = contents.split()[0] if contents else ""
        actual = sha256(raw).hexdigest()
        if expected != actual:
            errors.append(f"SHA-256 mismatch: sidecar has {expected or '<empty>'}, packet hashes to {actual}")

    games_cutoff = date.fromisoformat(config.games_through)
    for index, game in enumerate(packet.get("games", [])):
        try:
            played = local_date(game.get("start_date") or game.get("date"))
        except (ValueError, TypeError):
            errors.append(f"games[{index}] has no parseable date")
            continue
        if played > games_cutoff:
            errors.append(f"games[{index}] date {played} is after games_through {games_cutoff}")

    rankings = packet.get("rankings", {})
    prior_cutoff = date.fromisoformat(config.prior_cfp_release)
    meta = packet.get("meta", {})
    rich = meta.get("resume_schema") == 2
    evidence_cutoff = games_cutoff
    if rich:
        try:
            evidence_cutoff = local_date(meta["evidence_through"])
            if (str(evidence_cutoff) != config.evidence_through
                    or not max(games_cutoff, prior_cutoff) <= evidence_cutoff < date.fromisoformat(config.release_id)):
                errors.append("Packet evidence cutoff differs from config or falls outside the pre-release window")
            for kind, ceiling in (("ap", evidence_cutoff), ("cfp", prior_cutoff)):
                dates = [local_date(value) for value in meta["poll_history_dates"][kind]]
                if not dates or max(dates) > ceiling:
                    errors.append(f"{kind} poll history is empty or extends past its cutoff")
        except (KeyError, TypeError, ValueError):
            errors.append("The résumé packet needs valid evidence and poll history dates")
    cfp = rankings.get("cfp", {})
    if cfp:
        published = _poll_date(cfp)
        if not published:
            errors.append("CFP rankings have no publication date")
        else:
            try:
                cfp_date = local_date(published)
                if cfp_date > prior_cutoff:
                    errors.append(f"CFP poll date {cfp_date} is after prior_cfp_release {prior_cutoff}")
            except ValueError:
                errors.append(f"CFP poll has invalid date {published!r}")
    ap = rankings.get("ap", {})
    if ap:
        published = _poll_date(ap)
        if published:
            try:
                ap_date = local_date(published)
                if ap_date > evidence_cutoff:
                    errors.append(f"AP poll date {ap_date} is after the evidence cutoff {evidence_cutoff}")
            except ValueError:
                errors.append(f"AP poll has invalid date {published!r}")
        if config.ap_week is not None and ap.get("week") != config.ap_week:
            errors.append(f"AP poll week {ap.get('week')!r} does not equal configured ap_week {config.ap_week}")
        expected_week = packet.get("meta", {}).get("ap_week_tied_to_games")
        if not rich and expected_week is not None and ap.get("week") != expected_week:
            errors.append(f"AP poll week {ap.get('week')!r} is not the packet's games-through week {expected_week!r}")
        if rich and not published:
            errors.append("The résumé packet needs a dated AP poll")

    # Catch an accidentally retained raw ranking response even if its shape changed.
    for trail, node in _walk(packet.get("rankings", {}), "rankings"):
        if isinstance(node, str) and "current week cfp" in node.lower():
            errors.append(f"{trail} contains forbidden current week CFP text")
    candidates = packet.get("candidates", [])
    if len(candidates) != len(set(candidates)):
        errors.append("candidate names are not unique")
    candidate_set = set(candidates)
    for team in packet.get("resumes", {}):
        if team not in candidate_set:
            errors.append(f"resume team {team!r} is absent from candidates")
    if "opening_spreads" in packet:
        game_ids = {str(row["id"]) for row in packet["games"] if row.get("id") is not None}
        if not isinstance(packet["opening_spreads"], dict) or not packet["opening_spreads"].keys() <= game_ids:
            errors.append("Opening spreads include IDs outside the frozen games")
    for key in ("games_through", "prior_cfp_release", "release_id", "fetched_at_utc", "endpoints_used", "notes"):
        if key not in meta:
            errors.append(f"packet meta is missing {key}")
    if meta.get("games_through") and str(meta["games_through"]) != config.games_through:
        errors.append("packet meta games_through differs from config")
    if meta.get("prior_cfp_release") and str(meta["prior_cfp_release"]) != config.prior_cfp_release:
        errors.append("packet meta prior_cfp_release differs from config")
    return errors


def lint_packet(packet_path: str | Path, config: Config) -> None:
    errors = lint_errors(packet_path, config)
    if errors:
        raise PacketLintError("Packet lint failed:\n- " + "\n- ".join(errors))
