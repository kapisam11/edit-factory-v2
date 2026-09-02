"""Production web dashboard for AI Video Factory.

Security model:
- Authentication is mandatory and requires FLASK_SECRET_KEY + AIVF_ADMIN_PASSWORD.
- State-changing requests require same-origin headers.
- API secrets are never returned and are redacted from the jobs database.
- Uploads use generated filenames and stay inside the upload directory.
- Package paths are resolved and constrained to OUTPUT_FOLDER.
- Admin cleanup is authenticated.
"""
import importlib.util
import json
import logging
import os
import re
import shutil
import sqlite3
import time
import uuid
from concurrent.futures import Future, ProcessPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, Response, jsonify, redirect, render_template, request, session, url_for, send_from_directory
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("AIVF_MAX_UPLOAD_MB", "500")) * 1024 * 1024
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("AIVF_COOKIE_SECURE", "0") == "1"

logger = logging.getLogger("web_app_v2")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
SECRET_SETTINGS = {"groq_key", "model_key", "elevenlabs_key"}
MUTABLE_SETTINGS = {"default_target_seconds", "default_workflow", "default_skip_qc", "default_use_groq", *SECRET_SETTINGS}
VALID_WORKFLOWS = {"default", "fast", "package_only"}

BASE_DIR = Path(__file__).parent.resolve()
UPLOAD_FOLDER = BASE_DIR / "uploads"
OUTPUT_FOLDER = BASE_DIR / "output"
DB_PATH = BASE_DIR / "jobs.db"
UPLOAD_FOLDER.mkdir(exist_ok=True)
OUTPUT_FOLDER.mkdir(exist_ok=True)

MAX_CONCURRENT_JOBS = max(1, int(os.environ.get("AIVF_WORKERS", "2")))
_executor = ProcessPoolExecutor(max_workers=MAX_CONCURRENT_JOBS)
_job_futures: Dict[str, Future] = {}


def _configured_security() -> bool:
    return bool(app.config.get("SECRET_KEY")) and bool(os.environ.get("AIVF_ADMIN_PASSWORD"))


def _require_auth() -> Optional[Response]:
    if not _configured_security():
        return jsonify({"error": "Server security is not configured."}), 503
    if not session.get("authenticated"):
        return jsonify({"error": "Authentication required"}), 401
    return None


def _same_origin_ok() -> bool:
    origin = request.headers.get("Origin")
    expected = f"{request.scheme}://{request.host}"
    if origin:
        return origin == expected
    referer = request.headers.get("Referer")
    return not referer or referer.startswith(expected + "/")


def _require_state_change_auth() -> Optional[Response]:
    error = _require_auth()
    if error:
        return error
    if not _same_origin_ok():
        return jsonify({"error": "Cross-origin request blocked"}), 403
    return None


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, topic TEXT NOT NULL, status TEXT DEFAULT 'queued',
            step TEXT DEFAULT 'waiting', params TEXT, pkg_dir TEXT, error TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, logs TEXT DEFAULT '[]'
        )""")
        conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS rate_limits (client_ip TEXT NOT NULL, ts REAL NOT NULL)")
        conn.commit()


init_db()


def _redact_params(params: dict) -> dict:
    result = dict(params)
    for key in SECRET_SETTINGS:
        if key in result:
            result[key] = "<redacted>" if result[key] else ""
    return result


def _public_job(job: dict) -> dict:
    result = dict(job)
    try:
        result["params"] = _redact_params(json.loads(result.get("params", "{}")))
    except (TypeError, json.JSONDecodeError):
        result["params"] = {}
    try:
        result["logs"] = json.loads(result.get("logs", "[]"))[-100:]
    except (TypeError, json.JSONDecodeError):
        result["logs"] = []
    return result


def db_insert_job(job_id: str, topic: str, params: dict) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO jobs (id, topic, status, step, params) VALUES (?, ?, ?, ?, ?)",
            (job_id, topic, "queued", "waiting", json.dumps(_redact_params(params))),
        )
        conn.commit()


def db_update_job(job_id: str, **kwargs) -> None:
    allowed = {"status", "step", "pkg_dir", "error", "params", "logs"}
    clean = {k: v for k, v in kwargs.items() if k in allowed}
    if not clean:
        return
    with sqlite3.connect(DB_PATH) as conn:
        fields = [f"{k} = ?" for k in clean]
        values = list(clean.values()) + [job_id]
        conn.execute(f"UPDATE jobs SET {', '.join(fields)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", values)
        conn.commit()


def db_get_job(job_id: str) -> Optional[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None


def db_list_jobs() -> List[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT 100").fetchall()]


def _read_job(db_path: str, job_id: str) -> Optional[dict]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None


def _append_worker_log(db_path: str, job_id: str, level: str, msg: str) -> None:
    job = _read_job(db_path, job_id)
    if not job or job.get("status") == "cancelled":
        return
    try:
        logs = json.loads(job.get("logs", "[]") or "[]")
    except json.JSONDecodeError:
        logs = []
    logs.append({"time": datetime.now().strftime("%H:%M:%S"), "level": level, "msg": msg})
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE jobs SET logs = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND status != 'cancelled'",
            (json.dumps(logs[-500:]), job_id),
        )
        conn.commit()


def _worker_update(db_path: str, job_id: str, **kwargs) -> None:
    allowed = {"status", "step", "pkg_dir", "error"}
    clean = {k: v for k, v in kwargs.items() if k in allowed}
    if not clean:
        return
    with sqlite3.connect(db_path) as conn:
        fields = [f"{k} = ?" for k in clean]
        values = list(clean.values()) + [job_id]
        conn.execute(
            f"UPDATE jobs SET {', '.join(fields)}, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND status != 'cancelled'",
            values,
        )
        conn.commit()


def _active_running(db_path: str) -> int:
    with sqlite3.connect(db_path) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'running'").fetchone()[0])


def _max_jobs(db_path: str) -> int:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = 'max_concurrent_jobs'").fetchone()
    try:
        return max(1, min(MAX_CONCURRENT_JOBS, int(json.loads(row[0]))) if row else MAX_CONCURRENT_JOBS)
    except (TypeError, ValueError, json.JSONDecodeError):
        return MAX_CONCURRENT_JOBS


def _wait_for_slot(db_path: str, job_id: str) -> bool:
    while True:
        job = _read_job(db_path, job_id)
        if not job or job.get("status") == "cancelled":
            return False
        if _active_running(db_path) < _max_jobs(db_path):
            return True
        time.sleep(0.25)


def _pipeline_skips(workflow: str) -> List[str]:
    configured = {
        "default": {"research", "plan", "script", "thumbnail", "auto_edit", "voiceover", "music", "quality_control", "metadata", "metrics"},
        "fast": {"plan", "script", "auto_edit", "metadata"},
        "package_only": {"research", "plan", "script", "thumbnail", "metadata"},
    }[workflow]
    all_stages = {"research", "plan", "script", "thumbnail", "auto_edit", "voiceover", "music", "quality_control", "metadata", "metrics"}
    return sorted(all_stages - configured)


def _run_job_worker(job_id: str, params: dict, output_root: str, db_path: str) -> None:
    try:
        if not _wait_for_slot(db_path, job_id):
            return
        _worker_update(db_path, job_id, status="running", step="Initializing")
        _append_worker_log(db_path, job_id, "INFO", "Initializing")

        from ai_video_factory.pipeline import PipelineContext, build_director_pipeline

        topic = params["topic"]
        ctx = PipelineContext(
            topic=topic,
            raw_video=params.get("raw_video"),
            target_seconds=params.get("target_seconds", 45.0),
            skip_qc=params.get("skip_qc", False),
            use_groq=params.get("use_groq", False),
            model_key=params.get("model_key") or None,
            groq_key=params.get("groq_key") or None,
        )
        safe_topic = re.sub(r"[^A-Za-z0-9_-]", "_", topic)[:40].strip("_") or "job"
        pkg_dir = os.path.join(output_root, f"{safe_topic}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{job_id[-6:]}")
        os.makedirs(pkg_dir, exist_ok=True)
        ctx.package_dir = pkg_dir

        workflow = params.get("workflow", "default")
        pipeline = build_director_pipeline(skip_stages=_pipeline_skips(workflow))
        _worker_update(db_path, job_id, step=f"Pipeline: {workflow}")
        _append_worker_log(db_path, job_id, "INFO", f"Running pipeline: {workflow}")
        ctx = pipeline.run(ctx)

        current = _read_job(db_path, job_id)
        if not current or current.get("status") == "cancelled":
            return
        if ctx.errors:
            _worker_update(db_path, job_id, status="error", error="; ".join(ctx.errors), pkg_dir=pkg_dir)
            for error in ctx.errors:
                _append_worker_log(db_path, job_id, "ERROR", error)
        else:
            _worker_update(db_path, job_id, status="done", step="Complete", pkg_dir=pkg_dir)
            _append_worker_log(db_path, job_id, "INFO", "Job complete")
    except Exception as exc:
        _append_worker_log(db_path, job_id, "ERROR", f"Job failed: {exc}")
        _worker_update(db_path, job_id, status="error", error=str(exc))


def _rate_limit(key: str, max_requests: int, window_seconds: int) -> bool:
    now = time.time()
    cutoff = now - window_seconds
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM rate_limits WHERE client_ip = ? AND ts < ?", (key, cutoff))
        count = conn.execute("SELECT COUNT(*) FROM rate_limits WHERE client_ip = ?", (key,)).fetchone()[0]
        if count >= max_requests:
            return False
        conn.execute("INSERT INTO rate_limits (client_ip, ts) VALUES (?, ?)", (key, now))
        conn.commit()
    return True


def get_settings() -> dict:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    stored = {}
    for key, value in rows:
        try:
            stored[key] = json.loads(value)
        except json.JSONDecodeError:
            continue
    result = {
        "default_target_seconds": 45.0,
        "default_workflow": "default",
        "default_skip_qc": False,
        "default_use_groq": False,
        "output_folder": str(OUTPUT_FOLDER),
        "max_upload_mb": app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024),
        "max_concurrent_jobs": MAX_CONCURRENT_JOBS,
    }
    result.update({k: v for k, v in stored.items() if k not in SECRET_SETTINGS})
    for key in SECRET_SETTINGS:
        result[f"has_{key}"] = bool(os.environ.get({"groq_key": "GROQ_API_KEY", "model_key": "OPENAI_API_KEY", "elevenlabs_key": "ELEVENLABS_API_KEY"}[key])) or bool(stored.get(key))
    return result


def set_setting(key: str, value: Any) -> None:
    if key not in MUTABLE_SETTINGS:
        raise ValueError(f"Setting '{key}' is not writable")
    if key == "default_target_seconds":
        value = float(value)
        if not 15 <= value <= 120:
            raise ValueError("default_target_seconds must be between 15 and 120")
    elif key == "default_workflow":
        value = str(value)
        if value not in VALID_WORKFLOWS:
            raise ValueError("Unsupported workflow")
    elif key in {"default_skip_qc", "default_use_groq"}:
        value = bool(value)
    elif key in SECRET_SETTINGS:
        value = str(value).strip()
        if not value:
            return
        env_name = {"groq_key": "GROQ_API_KEY", "model_key": "OPENAI_API_KEY", "elevenlabs_key": "ELEVENLABS_API_KEY"}[key]
        os.environ[env_name] = value
        return
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, json.dumps(value)))
        conn.commit()


def _validate_video_upload(filename: str) -> bool:
    return bool(filename) and Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


def _build_job_params(data: dict, upload=None) -> Tuple[dict, Optional[str]]:
    settings = get_settings()
    topic = str(data.get("topic", "")).strip()
    if not 2 <= len(topic) <= 200:
        raise ValueError("Topic must be between 2 and 200 characters")
    target = float(data.get("target_seconds", settings["default_target_seconds"]))
    if not 15 <= target <= 120:
        raise ValueError("target_seconds must be between 15 and 120")
    workflow = str(data.get("workflow", settings["default_workflow"]))
    if workflow not in VALID_WORKFLOWS:
        raise ValueError("Unsupported workflow")

    params = {
        "topic": topic,
        "target_seconds": target,
        "workflow": workflow,
        "use_groq": bool(data.get("use_groq", settings["default_use_groq"])),
        "groq_key": str(data.get("groq_key", "")).strip() or os.environ.get("GROQ_API_KEY", ""),
        "model_key": str(data.get("model_key", "")).strip() or os.environ.get("OPENAI_API_KEY", ""),
        "skip_qc": bool(data.get("skip_qc", settings["default_skip_qc"])),
    }

    raw_path = None
    if upload:
        clean = secure_filename(upload.filename or "")
        if not clean or not _validate_video_upload(clean):
            raise ValueError("Invalid video file type")
        raw_path = str(UPLOAD_FOLDER / f"{uuid.uuid4().hex}{Path(clean).suffix.lower()}")
        upload.save(raw_path)
        params["raw_video"] = raw_path
    return params, raw_path


def _queue_job(data: dict, upload=None):
    client_ip = request.remote_addr or "unknown"
    if not _rate_limit(f"api:{client_ip}", 10, 60):
        return jsonify({"error": "Rate limit exceeded. Try again in a minute."}), 429
    try:
        params, _ = _build_job_params(data, upload)
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    try:
        free_mb = os.statvfs(str(UPLOAD_FOLDER)).f_bavail * os.statvfs(str(UPLOAD_FOLDER)).f_frsize / (1024 * 1024)
    except OSError:
        free_mb = 0
    if free_mb < 1000:
        return jsonify({"error": "Server disk space low. Cannot accept new jobs."}), 503
    job_id = f"job_{uuid.uuid4().hex[:12]}"
    db_insert_job(job_id, params["topic"], params)
    try:
        _job_futures[job_id] = _executor.submit(_run_job_worker, job_id, params, str(OUTPUT_FOLDER), str(DB_PATH))
    except Exception:
        db_update_job(job_id, status="error", error="Could not queue job")
        return jsonify({"error": "Could not queue job"}), 503
    return jsonify({"job_id": job_id, "status": "queued"})


@app.route("/login", methods=["GET", "POST"])
def login():
    if not _configured_security():
        return render_template("login.html", error="Set FLASK_SECRET_KEY and AIVF_ADMIN_PASSWORD."), 503
    if request.method == "POST":
        ip = request.remote_addr or "unknown"
        if not _rate_limit(f"login:{ip}", 5, 300):
            return render_template("login.html", error="Too many login attempts. Try again later."), 429
        password = request.form.get("password", "")
        expected = os.environ.get("AIVF_ADMIN_PASSWORD", "")
        valid = check_password_hash(expected, password) if expected.startswith(("scrypt:", "pbkdf2:")) else password == expected
        if valid:
            session.clear()
            session["authenticated"] = True
            return redirect(url_for("index"))
        return render_template("login.html", error="Invalid password."), 401
    return render_template("login.html", error=None, next=request.args.get("next", ""))


@app.post("/logout")
def logout():
    error = _require_state_change_auth()
    if error:
        return error
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
def index():
    if not _configured_security() or not session.get("authenticated"):
        return redirect(url_for("login", next="/"))
    return render_template("index.html")


@app.route("/api/health")
def health():
    try:
        st = os.statvfs(str(UPLOAD_FOLDER))
        free_mb = st.f_bavail * st.f_frsize / (1024 * 1024)
    except OSError:
        free_mb = 0
    return jsonify({
        "status": "ok" if _configured_security() else "misconfigured",
        "authenticated": bool(session.get("authenticated")),
        "disk_free_mb": round(free_mb, 1),
        "max_content_length_mb": app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024),
        "ffmpeg_available": shutil.which("ffmpeg") is not None,
        "tts_available": any(importlib.util.find_spec(name) is not None for name in ("edge_tts", "pyttsx3", "elevenlabs")),
    })


@app.route("/api/settings", methods=["GET", "POST"])
def settings():
    if request.method == "GET":
        error = _require_auth()
        if error:
            return error
        return jsonify(get_settings())
    error = _require_state_change_auth()
    if error:
        return error
    try:
        for key, value in (request.get_json(silent=True) or {}).items():
            set_setting(key, value)
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(get_settings())


@app.route("/api/run", methods=["POST"])
def run_api():
    error = _require_state_change_auth()
    if error:
        return error
    data = request.form.to_dict() if request.form else (request.get_json(silent=True) or {})
    upload = request.files.get("raw_video") if request.files else None
    return _queue_job(data, upload)


@app.route("/api/jobs", methods=["GET", "POST"])
def jobs_api():
    if request.method == "GET":
        error = _require_auth()
        if error:
            return error
        return jsonify([_public_job(job) for job in db_list_jobs()])
    error = _require_state_change_auth()
    if error:
        return error
    return _queue_job(request.get_json(silent=True) or {})


@app.route("/api/jobs/<job_id>")
def get_job(job_id: str):
    error = _require_auth()
    if error:
        return error
    job = db_get_job(job_id)
    return jsonify(_public_job(job)) if job else (jsonify({"error": "Job not found"}), 404)


@app.route("/api/jobs/<job_id>/status")
def job_status(job_id: str):
    error = _require_auth()
    if error:
        return error
    job = db_get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({"job_id": job_id, "status": job["status"], "step": job["step"], "error": job["error"], "pkg_dir": job["pkg_dir"]})


@app.route("/api/jobs/<job_id>/cancel", methods=["POST"])
def cancel_job(job_id: str):
    error = _require_state_change_auth()
    if error:
        return error
    job = db_get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    if job["status"] not in {"queued", "running"}:
        return jsonify({"job_id": job_id, "status": job["status"]})
    future = _job_futures.get(job_id)
    if future and future.cancel():
        db_update_job(job_id, status="cancelled", step="cancelled")
    else:
        db_update_job(job_id, status="cancelled", step="cancelled")
    return jsonify({"job_id": job_id, "status": "cancelled"})


@app.route("/api/jobs/<job_id>/logs")
@app.route("/api/jobs/<job_id>/logs/stream")
def job_logs(job_id: str):
    error = _require_auth()
    if error:
        return error
    if not db_get_job(job_id):
        return jsonify({"error": "Job not found"}), 404
    job = db_get_job(job_id)
    return jsonify({"job_id": job_id, "logs": _public_job(job)["logs"]})


@app.route("/api/queue/status")
def queue_status():
    error = _require_auth()
    if error:
        return error
    jobs = db_list_jobs()
    return jsonify({"running": sum(j["status"] == "running" for j in jobs), "queued": sum(j["status"] == "queued" for j in jobs), "done": sum(j["status"] == "done" for j in jobs), "error": sum(j["status"] == "error" for j in jobs), "cancelled": sum(j["status"] == "cancelled" for j in jobs), "max_concurrent_jobs": MAX_CONCURRENT_JOBS})


def _safe_package_path(name: str) -> Optional[Path]:
    if not name or Path(name).name != name:
        return None
    root = OUTPUT_FOLDER.resolve()
    candidate = (root / name).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_dir() else None


@app.route("/api/packages")
def packages():
    error = _require_auth()
    if error:
        return error
    items = []
    for pkg in sorted((p for p in OUTPUT_FOLDER.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True):
        thumb = next((t for t in ("thumbnail.png", "thumbnail_vertical.png") if (pkg / t).is_file()), None)
        items.append({"name": pkg.name, "created": datetime.fromtimestamp(pkg.stat().st_mtime).isoformat(), "thumbnail": f"/api/package/{pkg.name}/file/{thumb}" if thumb else None, "has_video": any((pkg / n).is_file() for n in ("final_short.mp4", "final_with_music.mp4", "final_short_vo.mp4"))})
    return jsonify(items)


@app.route("/api/package/<name>/script", methods=["GET", "POST"])
def package_script(name: str):
    error = _require_state_change_auth() if request.method == "POST" else _require_auth()
    if error:
        return error
    pkg = _safe_package_path(name)
    if not pkg:
        return jsonify({"error": "Package not found"}), 404
    path = pkg / "script.txt"
    if request.method == "GET":
        return jsonify({"script": path.read_text(encoding="utf-8") if path.exists() else ""})
    script = str((request.get_json(silent=True) or {}).get("script", ""))
    if len(script) > 50000:
        return jsonify({"error": "Script is too long"}), 400
    path.write_text(script, encoding="utf-8")
    return jsonify({"ok": True})


@app.route("/api/package/<name>/file/<path:filename>")
def package_file(name: str, filename: str):
    error = _require_auth()
    if error:
        return error
    pkg = _safe_package_path(name)
    if not pkg:
        return jsonify({"error": "Package not found"}), 404
    target = (pkg / filename).resolve()
    try:
        target.relative_to(pkg)
    except ValueError:
        return jsonify({"error": "Invalid file path"}), 400
    if not target.is_file():
        return jsonify({"error": "File not found"}), 404
    return send_from_directory(pkg, filename, conditional=True)


@app.route("/api/package/<name>/files")
def package_files(name: str):
    error = _require_auth()
    if error:
        return error
    pkg = _safe_package_path(name)
    if not pkg:
        return jsonify({"error": "Package not found"}), 404
    return jsonify([{ "path": p.relative_to(pkg).as_posix(), "size": p.stat().st_size } for p in pkg.rglob("*") if p.is_file()])


@app.route("/api/presets", methods=["GET", "POST"])
def presets():
    error = _require_state_change_auth() if request.method == "POST" else _require_auth()
    if error:
        return error
    if request.method == "GET":
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute("SELECT key, value FROM settings WHERE key LIKE 'preset:%'").fetchall()
        result = {}
        for key, value in rows:
            try:
                result[key.split(":", 1)[1]] = json.loads(value)
            except json.JSONDecodeError:
                pass
        return jsonify(result)
    data = request.get_json(silent=True) or {}
    name = re.sub(r"[^A-Za-z0-9_-]", "_", str(data.get("name", "")).strip())[:50]
    config = data.get("config")
    if not name or not isinstance(config, dict):
        return jsonify({"error": "Invalid preset"}), 400
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (f"preset:{name}", json.dumps(config)))
        conn.commit()
    return jsonify({"ok": True, "name": name})


@app.route("/api/admin/cleanup", methods=["POST"])
def cleanup_packages_admin():
    error = _require_state_change_auth()
    if error:
        return error
    try:
        days = float(request.args.get("max_age_days", "7"))
        if not 0 < days <= 3650:
            raise ValueError("max_age_days must be between 0 and 3650")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    cutoff = time.time() - days * 86400
    removed = []
    for child in OUTPUT_FOLDER.iterdir():
        if child.is_dir() and child.stat().st_mtime < cutoff:
            shutil.rmtree(child, ignore_errors=True)
            removed.append(child.name)
    return jsonify({"removed": removed, "count": len(removed)})


if __name__ == "__main__":
    if not _configured_security():
        raise SystemExit("Set FLASK_SECRET_KEY and AIVF_ADMIN_PASSWORD before starting the dashboard.")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
