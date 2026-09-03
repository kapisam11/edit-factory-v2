import json
import os
from io import BytesIO
from pathlib import Path

import pytest
from werkzeug.datastructures import FileStorage
from werkzeug.security import generate_password_hash

os.environ.setdefault("FLASK_SECRET_KEY", "unit-test-secret")
os.environ.setdefault("AIVF_ADMIN_PASSWORD", "unit-test-password")

from ai_video_factory.config import AIVFConfig, APIKeys, PipelineConfig, StyleProfile
from ai_video_factory.pipeline import Pipeline, PipelineContext, PipelineStage
from ai_video_factory.validation import normalize_workflow, validate_target_seconds
from web_app_v2 import app
import web_app_v2
import cli


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


def login(client):
    response = client.post("/login", data={"password": "unit-test-password"}, base_url="http://localhost")
    assert response.status_code == 302


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
    assert "elapsed_seconds" in result.stage_results["failing"]
    assert any("Skipped due to error" in warning for warning in result.warnings)


def test_pipeline_progress_callback_reports_percent_and_eta():
    events = []

    class NoopStage(PipelineStage):
        name = "noop"

        def run(self, ctx):
            return ctx

    ctx = Pipeline([NoopStage()], verbose=False, progress_callback=lambda *args: events.append(args)).run(
        PipelineContext(topic="test", target_seconds=45)
    )
    assert events
    completed, total, name, elapsed, eta = events[0]
    assert (completed, total, name) == (1, 1, "noop")
    assert elapsed >= 0
    assert eta == 0
    assert ctx.stage_results["noop"]["status"] == "completed"


def test_pipeline_rejects_invalid_duration_and_non_finite_values():
    with pytest.raises(ValueError):
        PipelineContext(topic="test", target_seconds=10)
    with pytest.raises(ValueError):
        validate_target_seconds(float("nan"))


def test_shared_workflow_validator_matches_web_aliases():
    assert normalize_workflow("director") == "default"
    assert normalize_workflow("legacy") == "default"
    assert normalize_workflow("FAST") == "fast"
    with pytest.raises(ValueError):
        normalize_workflow("nope")
    params, _ = web_app_v2._build_params({"topic": "test", "target_seconds": 45, "workflow": "director"})
    assert params["workflow"] == "default"


def test_dashboard_requires_authentication():
    client = app.test_client()
    with client.session_transaction() as sess:
        sess.clear()
    for path in ("/api/settings", "/api/jobs", "/api/packages"):
        response = client.get(path, base_url="http://localhost")
        assert response.status_code == 401


def test_dashboard_login_and_secret_redaction():
    client = app.test_client()
    login(client)

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

    conn = web_app_v2.sqlite3.connect(web_app_v2.DB_PATH)
    try:
        rows = conn.execute("SELECT params FROM jobs").fetchall()
    finally:
        conn.close()
    assert all("secret-value" not in (row[0] or "") for row in rows)


def test_settings_reject_unknown_key():
    client = app.test_client()
    login(client)
    response = client.post(
        "/api/settings",
        json={"admin_password": "should-not-be-written"},
        headers={"Origin": "http://localhost"},
        base_url="http://localhost",
    )
    assert response.status_code == 400


def test_cross_origin_state_change_is_blocked():
    client = app.test_client()
    login(client)
    response = client.post(
        "/api/settings",
        json={"default_target_seconds": 50},
        headers={"Origin": "https://evil.example"},
        base_url="http://localhost",
    )
    assert response.status_code == 403


def test_state_change_without_origin_or_referer_is_blocked():
    client = app.test_client()
    login(client)
    response = client.post(
        "/api/settings",
        json={"default_target_seconds": 50},
        base_url="http://localhost",
    )
    assert response.status_code == 403


def test_security_headers_are_set():
    response = app.test_client().get("/api/health", base_url="http://localhost")
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


def test_timing_safe_legacy_password_check():
    assert web_app_v2._verify_login("admin", "unit-test-password") is True
    assert web_app_v2._verify_login("admin", "wrong-password") is False


def test_multi_user_authentication(monkeypatch):
    hashed = generate_password_hash("editor-password", method="scrypt")
    monkeypatch.setenv("AIVF_ADMIN_USERS_JSON", json.dumps({"editor": hashed}))
    assert web_app_v2._verify_login("editor", "editor-password") is True
    assert web_app_v2._verify_login("editor", "wrong") is False
    assert web_app_v2._verify_login("admin", "unit-test-password") is False
    monkeypatch.delenv("AIVF_ADMIN_USERS_JSON", raising=False)


def test_sqlite_uses_wal_and_busy_timeout(tmp_path):
    path = Path(tmp_path) / "jobs.db"
    conn = web_app_v2._db_connect(path)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 30000
    finally:
        conn.close()


def test_busy_poll_slot_gate_removed():
    assert not hasattr(web_app_v2, "_wait_for_slot")


def test_batch_loader_supports_csv_and_json(tmp_path):
    csv_path = Path(tmp_path) / "jobs.csv"
    csv_path.write_text("topic,target_seconds\nMinecraft,45\nCOD,30\n", encoding="utf-8")
    assert [row["topic"] for row in cli._load_batch(str(csv_path))] == ["Minecraft", "COD"]
    json_path = Path(tmp_path) / "jobs.json"
    json_path.write_text(json.dumps(["Roblox", {"topic": "Valorant", "target_seconds": 60}]), encoding="utf-8")
    items = cli._load_batch(str(json_path))
    assert items[0]["topic"] == "Roblox"
    assert items[1]["target_seconds"] == 60


def test_dashboard_api_includes_thumbnail_variant(tmp_path, monkeypatch):
    monkeypatch.setattr(web_app_v2, "OUTPUT_FOLDER", Path(tmp_path))
    params, _ = web_app_v2._build_params({"topic": "test", "target_seconds": 45, "thumbnail_variant": 3})
    assert params["thumbnail_variant"] == 3


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
