"""Packet canonicalisation and small packet access helpers."""

from __future__ import annotations

from datetime import date, datetime
from hashlib import sha256
import json
from pathlib import Path
from typing import Any


def canonical_bytes(value: Any) -> bytes:
    """The exact bytes that packet.sha256 authenticates: sorted, compact UTF-8 JSON."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def digest(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def write_packet(packet: dict[str, Any], directory: str | Path) -> tuple[Path, str]:
    """Write packet.json and its authoritative full-file SHA-256 sidecar.

    A digest cannot literally contain itself.  ``meta.content_sha256`` therefore
    records the digest before that informational field is inserted, while the
    sidecar authenticates the complete, committed packet bytes.
    """
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    meta = packet.setdefault("meta", {})
    meta["canonical_encoding"] = "UTF-8 JSON, sorted keys, compact separators, no newline"
    meta["content_sha256"] = digest(packet)
    raw = canonical_bytes(packet)
    full_hash = sha256(raw).hexdigest()
    (target / "packet.json").write_bytes(raw)
    (target / "packet.sha256").write_text(full_hash + "\n", encoding="ascii")
    return target / "packet.json", full_hash


def read_packet(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def default_packet_path(release_id: str) -> Path:
    return Path("data/packets") / release_id / "packet.json"


def local_date(value: object) -> date:
    """Interpret a CFBD kickoff in America/New_York before extracting its date."""
    text = str(value)
    if len(text) < 10:
        raise ValueError(f"not an ISO date: {value!r}")
    if "T" not in text:
        return date.fromisoformat(text[:10])
    instant = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if instant.tzinfo is None:
        return instant.date()
    from zoneinfo import ZoneInfo
    return instant.astimezone(ZoneInfo("America/New_York")).date()


def ranking_entries(packet: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    return list(packet.get("rankings", {}).get(kind, {}).get("entries", []))
