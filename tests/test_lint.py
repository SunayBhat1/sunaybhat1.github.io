from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from cfpllm.lint import lint_errors, lint_packet
from cfpllm.packet import canonical_bytes, digest, read_packet, write_packet


def test_fixture_packet_passes_lint(config, packet_path):
    lint_packet(packet_path, config)


def test_lint_rejects_november_22_eastern_game(config, packet, tmp_path):
    bad = deepcopy(packet)
    # 06:00Z is after midnight in New York on Nov. 22.
    bad["games"][0]["start_date"] = "2026-11-22T06:00:00+00:00"
    path, _ = write_packet(bad, tmp_path)
    assert "after games_through" in "\n".join(lint_errors(path, config))


def test_lint_allows_november_21_night_game_in_eastern(config, packet, tmp_path):
    good = deepcopy(packet)
    # 01:00Z is 8pm ET on Nov. 21.
    good["games"][0]["start_date"] = "2026-11-22T01:00:00+00:00"
    path, _ = write_packet(good, tmp_path)
    lint_packet(path, config)


def test_lint_rejects_later_cfp_poll(config, packet, tmp_path):
    bad = deepcopy(packet)
    bad["rankings"]["cfp"]["published_on"] = "2026-11-24"
    path, _ = write_packet(bad, tmp_path)
    assert "CFP poll date 2026-11-24" in "\n".join(lint_errors(path, config))


def test_packet_bytes_and_hash_are_deterministic(packet, tmp_path):
    first, first_hash = write_packet(deepcopy(packet), tmp_path / "one")
    second, second_hash = write_packet(deepcopy(packet), tmp_path / "two")
    assert first.read_bytes() == second.read_bytes()
    assert first_hash == second_hash
    assert first.read_bytes() == canonical_bytes(read_packet(first))
