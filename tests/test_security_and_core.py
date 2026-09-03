import os
from io import BytesIO
from pathlib import Path

import pytest
from werkzeug.datastructures import FileStorage

os.environ.setdefault("FLASK_SECRET_KEY", "unit-test-secret")
os.environ.setdefault("AIVF_ADMIN_PASSWORD", "unit-test-password")

from ai_video_factory.config import AIVFConfig, APIKeys, PipelineConfig, StyleProfile
from ai_video_factory.pipeline import Pipeline, PipelineContext, PipelineStage
from web_app_v2 import app
import web_app_v2


class FailingStage(PipelineStage):
    name = "failing"
    skippable = True
    retryable = False
    max_retries = 5

    def __init__(self):
        self.calls = 0

    def run(self, ctx):
        self.calls += 1
        raise RuntimeError("boom")


def test_config_load_restores_dataclasses(tmp_path):
    path = tmp_path / "config.json"
    config = AIVFConfig()
    config.save(str(path))
    loaded = AIVFConfig.load(str(path))
    assert isinstance(loaded.pipelines["default"], PipelineConfig)
    assert isinstance(loaded.style_profiles["gaming_fast"], StyleProfile)
    assert isinstance(loaded.api_keys, APIKeys)
    assert loaded.get_pipeline("fast").stages == ["plan", "script", "auto_edit", "metadata"]


def test_pipeline_honors_retryable_flag():
    stage = FailingStage()
    ctx = PipelineContext(topic="test", target_seconds=45)
    result = Pipeline([stage], verbose=False).run(ctx)
    assert stage.calls == 1
    assert result.stage_results["failing"]["status"] == "skipped"
    assert result.stage_results["failing"]["attempts"] if "attempts" in result.stage_results["failing"] else True


def test_pipeline_rejects_invalid_duration():
    with pytest.raises(ValueError):
        PipelineContext(topic="test", target_seconds=10)


def test_dashboard_requires_authentication():
    client = app.test_client()
    with client.session_transaction() as sess:
        sess.clear()
    response = client.get("/api/settings")
    assert response.status_code == 401


def test_dashboard_login_and_secret_redaction():
    client = app.test_client()
    response = client.post("/login", data={"password": "unit-test-password"}, base_url="http://localhost")
    assert response.status_code == 302

    response = client.get("/api/settings", base_url="http://localhost")
    assert response.status_code == 200
    payload = response.get_json()
    assert "groq_key" not in payload
    assert "model_key" not in payload
    assert "elevenlabs_key" not in payload

    response = client.post(
        "/api/settings",
        json={"groq_key": "secret-value", "default_target_seconds": 50},
        headers={"Origin": "http://localhost"},
        base_url="http://localhost",
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert "groq_key" not in payload
    assert payload["has_groq_key"] is True


def test_settings_reject_unknown_key():
    client = app.test_client()
    client.post("/login", data={"password": "unit-test-password"}, base_url="http://localhost")
    response = client.post(
        "/api/settings",
        json={"admin_password": "should-not-be-written"},
        headers={"Origin": "http://localhost"},
        base_url="http://localhost",
    )
    assert response.status_code == 400


def test_cross_origin_state_change_is_blocked():
    client = app.test_client()
    client.post("/login", data={"password": "unit-test-password"}, base_url="http://localhost")
    response = client.post(
        "/api/settings",
        json={"default_target_seconds": 50},
        headers={"Origin": "https://evil.example"},
        base_url="http://localhost",
    )
    assert response.status_code == 403


def test_admin_cleanup_requires_authentication():
    client = app.test_client()
    response = client.post("/api/admin/cleanup", base_url="http://localhost")
    assert response.status_code == 401


def test_upload_filename_is_generated_and_confined(tmp_path, monkeypatch):
    monkeypatch.setattr(web_app_v2, "UPLOAD_FOLDER", Path(tmp_path))
    Path(tmp_path).mkdir(parents=True, exist_ok=True)
    upload = FileStorage(stream=BytesIO(b"not-a-real-video"), filename="../../evil.mp4")
    with app.test_request_context("/api/run", base_url="http://localhost"):
        params, raw_path = web_app_v2._build_params({"topic": "test", "target_seconds": 45}, upload)
    assert raw_path is not None
    assert Path(raw_path).parent.resolve() == Path(tmp_path).resolve()
    assert Path(raw_path).name.endswith(".mp4")
    assert ".." not in Path(raw_path).name
    assert params["raw_video"] == raw_path


def test_upload_rejects_disallowed_extension(tmp_path, monkeypatch):
    monkeypatch.setattr(web_app_v2, "UPLOAD_FOLDER", Path(tmp_path))
    upload = FileStorage(stream=BytesIO(b"not-a-real-file"), filename="evil.exe")
    with app.test_request_context("/api/run", base_url="http://localhost"):
        with pytest.raises(ValueError, match="Invalid video file type"):
            web_app_v2._build_params({"topic": "test", "target_seconds": 45}, upload)


def test_package_path_confined_to_output_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(web_app_v2, "OUTPUT_FOLDER", Path(tmp_path))
    safe = Path(tmp_path) / "safe"
    safe.mkdir()
    assert web_app_v2._safe_package_path("safe") == safe.resolve()
    assert web_app_v2._safe_package_path("../safe") is None
    assert web_app_v2._safe_package_path("safe/../safe") is None
