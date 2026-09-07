"""Small contract checks for the REST-only Director Console adapter."""

from pathlib import Path


def test_human_gate_approval_maps_public_state_to_command_contract():
    source = (Path(__file__).parents[1] / "webui/js/director-console.js").read_text(encoding="utf-8")

    assert "narration_acceptance:'approve_narration'" in source
    assert "final_audio_approval:'approve_final_audio'" in source
    assert "gate.items?.[0]" in source
    assert "artifact_id:artifact.artifact_id" in source
    assert "artifact_sha256:artifact.sha256" in source
