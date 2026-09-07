"""Small contract checks for the REST-only Director Console adapter."""

from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import api_app
from services.voice_project_operations import OperationStatus, VoiceProjectOperation


def test_human_gate_approval_maps_public_state_to_command_contract():
    source = (Path(__file__).parents[1] / "webui/js/director-console.js").read_text(encoding="utf-8")

    assert "narration_acceptance:'approve_narration'" in source
    assert "final_audio_approval:'approve_final_audio'" in source
    assert "gate.items?.[0]" in source
    assert "artifact_id:artifact.artifact_id" in source
    assert "artifact_sha256:artifact.sha256" in source


def test_console_contract_has_drawer_server_impact_and_refresh_safe_jobs():
    source = (Path(__file__).parents[1] / "webui/js/director-console.js").read_text(encoding="utf-8")

    assert "prompt(" not in source
    assert "required_reproduction_steps" in source
    assert "/api/v1/voice-projects/${directorActive.project_id}/revisions" in source
    assert "/api/v1/voice-project-jobs?project_id=" in source
    assert "human_action.items?.[0]" in source


def test_operation_list_api_exposes_persisted_project_jobs():
    operation = VoiceProjectOperation(
        id="vp_op_console",
        project_id="console_project",
        operation="render_beat_B03",
        status=OperationStatus.RUNNING,
        stage="rendering",
        beat_id="B03",
        progress_percent=78,
    )
    with patch("routers.voice_projects.get_voice_project_operation_manager") as get_manager:
        get_manager.return_value.list_operations.return_value = [operation]
        with TestClient(api_app.app) as client:
            response = client.get("/api/v1/voice-project-jobs?project_id=console_project&limit=5")

    assert response.status_code == 200
    assert response.json()[0]["progress_percent"] == 78
    get_manager.return_value.list_operations.assert_called_once_with(project_id="console_project", limit=5)
