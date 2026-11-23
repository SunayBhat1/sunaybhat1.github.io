"""Small explicit aliases for human-entered official rankings."""

from __future__ import annotations

import re


ALIASES = {
    "Miami (FL)": "Miami",
    "Miami (Florida)": "Miami",
    "Ole Miss": "Mississippi",
    "UConn": "Connecticut",
    "USC": "USC",
    "UTSA": "UT San Antonio",
    "UCF": "UCF",
}


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def resolve_name(name: str, canonical_names: list[str] | set[str]) -> str:
    available = set(canonical_names)
    if name in available:
        return name
    target = ALIASES.get(name, name)
    if target in available:
        return target
    matches = [item for item in available if _key(item) == _key(target)]
    if len(matches) == 1:
        return matches[0]
    raise ValueError(f"Could not resolve official team name {name!r} to a packet canonical name")
