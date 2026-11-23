from __future__ import annotations

from dataclasses import replace
import json

from cfpllm import run
from conftest import ballot


def test_compact_run_does_not_reuse_a_different_model_or_legacy_ballot(
    config, packet, packet_path, tmp_path, monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    sent = []

    class FakeClient:
        provider = "fake"

        def __init__(self, config):
            self.model = config.model

        def complete(self, system, user, temperature):
            from cfpllm.personas import committee_mix

            member = next(member for member in committee_mix("balanced") if f"id is {member.agent_id};" in system)
            sent.append(self.model)
            return json.dumps(ballot(packet["candidates"], member.agent_id, member.persona)), {}

    monkeypatch.setattr(run, "ChatClient", FakeClient)
    legacy = run._ballot_path(config.ballot_dir, "balanced", "cfp_on_ap_on", 0.3, "M01")
    run._write_json(legacy, ballot(list(reversed(packet["candidates"]))))
    scope = {"mix_names": ("balanced",), "condition_names": ("cfp_on_ap_on",), "seeds": (0.3,)}

    first = run.run_committee(config, packet_path, **scope)
    assert len(sent) == 13
    assert run.run_committee(config, packet_path, **scope)["artifact_dir"] == first["artifact_dir"]
    assert len(sent) == 13
    alternate = run.run_committee(replace(config, model="fake-alternate"), packet_path, **scope)
    assert len(sent) == 26
    assert alternate["artifact_dir"] != first["artifact_dir"]
    assert run._read_json(legacy)["ranking"][0] == packet["candidates"][-1]
