"""Production web dashboard for AI Video Factory.

Security defaults:
- Session authentication backed by AIVF_ADMIN_PASSWORD.
- Same-origin protection for state-changing requests.
- API keys are write-only and never returned by settings endpoints.
- Uploaded filenames are sanitized and stored under generated names.
- Admin cleanup requires authentication.
- Package/file access is constrained to OUTPUT_FOLDER.
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

from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
    send_from_directory,
)
from werkzeug.security import check_password_hash, generate_password_hash
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
MUTABLE_SETTINGS = {
    "default_target_seconds",
    "default_workflow",
    "default_skip_qc",
    "default_use_groq",
    "groq_key",
    "model_key",
    "elevenlabs_key",
}
SECRET_SETTINGS = {"groq_key", "model_key", "elevenlabs_key"}
VALID_WORKFLOWS = {"director", "legacy"}

BASE_DIR = Path(__file__).parent.resolve()
UPLOAD_FOLDER = BASE_DIR / "uploads"
OUTPUT_FOLDER = BASE_DIR / "output"
DB_PATH = BASE_DIR / "jobs.db"
UPLOAD_FOLDER.mkdir(exist_ok=True)
OUTPUT_FOLDER.mkdir(exist_ok=True)

MAX_CONCURRENT_JOBS = max(1, int(os.environ.get("AIVF_WORKERS", "2")))
_executor = ProcessPoolExecutor(max_workers=MAX_CONCURRENT_JOBS)
_job_futures: Dict[str, Future] = {}


def _auth_password() -> Optional[str]:
    """Return the configured admin password, or None when misconfigured."""
    return os.environ.get("AIVF_ADMIN_PASSWORD")


def _configured_security() -> bool:
    return bool(app.config.get("SECRET_KEY")) and bool(_auth_password())


def _is_safe_next(path: str) -> bool:
    return bool(path) and path.startswith("/") and not path.startswith("//")


def _same_origin_ok() -> bool:
    origin = request.headers.get("Origin")
    if origin:
        expected = f"{request.scheme}://{request.host}"
        return origin == expected
    referer = request.headers.get("Referer")
    if referer:
        return referer.startswith(f"{request.scheme}://{request.host}/")
    # Non-browser clients may omit both. Authentication still protects the route.
    return True


def _require_auth() -> Optional[Response]:
    if not _configured_security():
        return jsonify({"error": "Server security is not configured. Set FLASK_SECRET_KEY and AIVF_ADMIN_PASSWORD."}), 503
    if not session.get("authenticated"):
        return jsonify({"error": "Authentication required"}), 401
    return None


def _validate_state_change() -> Optional[Response]:
    auth_error = _require_auth()
    if auth_error:
        return auth_error
    if not _same_origin_ok():
        return jsonify({"error": "Cross-origin request blocked"}), 403
    return None


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                topic TEXT NOT NULL,
                status TEXT DEFAULT 'queued',
                step TEXT DEFAULT 'waiting',
                params TEXT,
                pkg_dir TEXT,
                error TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                logs TEXT DEFAULT '[]'
            )"""
        )
        conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS rate_limits (client_ip TEXT NOT NULL, ts REAL NOT NULL)")
        conn.commit()


init_db()


def db_insert_job(job_id: str, topic: str, params: dict) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO jobs (id, topic, status, step, params) VALUES (?, ?, ?, ?, ?)",
            (job_id, topic, "queued", "waiting", json.dumps(params)),
        )
        conn.commit()


def db_update_job(job_id: str, **kwargs) -> None:
    allowed = {"status", "step", "pkg_dir", "error", "params", "logs"}
    clean = {k: v for k, v in kwargs.items() if k in allowed}
    if not clean:
        return
    fields = [f"{k} = ?" for k in clean]
    values = list(clean.values()) + [job_id]
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            f"UPDATE jobs SET {', '.join(fields)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            values,
        )
        conn.commit()


def db_get_job(job_id: str) -> Optional[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None


def db_list_jobs() -> list:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT 100").fetchall()
        return [dict(r) for r in rows]


def db_append_log(job_id: str, level: str, msg: str) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT logs FROM jobs WHERE id = ?", (job_id,)).fetchone()
        logs = json.loads(row[0]) if row and row[0] else []
        logs.append({"time": datetime.now().strftime("%H:%M:%S"), "level": level, "msg": msg})
        conn.execute("UPDATE jobs SET logs = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (json.dumps(logs[-500:]), job_id))
        conn.commit()


def get_settings() -> dict:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        stored = {k: json.loads(v) for k, v in rows}
    defaults = {
        "default_target_seconds": 45.0,
        "default_workflow": "director",
        "default_skip_qc": False,
        "default_use_groq": False,
        "output_folder": str(OUTPUT_FOLDER),
        "max_upload_mb": app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024),
        "max_concurrent_jobs": MAX_CONCURRENT_JOBS,
    }
    defaults.update({k: v for k, v in stored.items() if k not in SECRET_SETTINGS})
    for name in SECRET_SETTINGS:
        defaults[f"has_{name}"] = bool(stored.get(name))
    return defaults


def set_setting(key: str, value: Any) -> None:
    if key not in MUTABLE_SETTINGS:
        raise ValueError(f"Setting '{key}' is not writable")
    if key == "default_target_seconds":
        value = float(value)
        if not 15 <= value <= 120:
            raise ValueError("default_target_seconds must be between 15 and 120")
    elif key in {"default_skip_qc", "default_use_groq"}:
        value = bool(value)
    elif key == "default_workflow":
        value = str(value)
        if value not in VALID_WORKFLOWS:
            raise ValueError("Unsupported workflow")
    elif key in SECRET_SETTINGS:
        value = str(value).strip()
        if not value:
            return
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, json.dumps(value)))
        conn.commit()


def get_setting_value(key: str, default: Any = None) -> Any:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if not row:
        return default
    try:
        return json.loads(row[0])
    except json.JSONDecodeError:
        return default


def check_rate_limit(client_ip: str, max_requests: int = 10, window_seconds: int = 60) -> bool:
    now = time.time()
    cutoff = now - window_seconds
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM rate_limits WHERE client_ip = ? AND ts < ?", (client_ip, cutoff))
        count = conn.execute("SELECT COUNT(*) FROM rate_limits WHERE client_ip = ?", (client_ip,)).fetchone()[0]
        if count >= max_requests:
            return False
        conn.execute("INSERT INTO rate_limits (client_ip, ts) VALUES (?, ?)", (client_ip, now))
        conn.commit()
    return True


def _read_job_snapshot(db_path: str, job_id: str) -> Optional[dict]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None


def _worker_max_jobs(db_path: str) -> int:
    value = get_setting_value_from_db(db_path, "max_concurrent_jobs", MAX_CONCURRENT_JOBS)
    try:
        return max(1, min(MAX_CONCURRENT_JOBS, int(value)))
    except (TypeError, ValueError):
        return MAX_CONCURRENT_JOBS


def get_setting_value_from_db(db_path: str, key: str, default: Any = None) -> Any:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if not row:
        return default
    try:
        return json.loads(row[0])
    except json.JSONDecodeError:
        return default


def _wait_for_slot(db_path: str, job_id: str) -> bool:
    while True:
        job = _read_job_snapshot(db_path, job_id)
        if not job or job.get("status") == "cancelled":
            return False
        max_jobs = _worker_max_jobs(db_path)
        with sqlite3.connect(db_path) as conn:
            running = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'running'").fetchone()[0]
        if running < max_jobs:
            return True
        time.sleep(0.5)


def _run_job_worker(job_id: str, params: dict, output_root: str, db_path: str):
    """Run a job in a worker process. Cancellation is cooperative."""
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    def update(**kwargs):
        allowed = {"status", "step", "pkg_dir", "error", "params", "logs"}
        clean = {k: v for k, v in kwargs.items() if k in allowed}
        if not clean:
            return
        fields = [f"{k} = ?" for k in clean]
        values = list(clean.values()) + [job_id]
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                f"UPDATE jobs SET {', '.join(fields)}, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND status != 'cancelled'",
                values,
            )
            conn.commit()

    def log(level: str, msg: str) -> None:
        job = _read_job_snapshot(db_path, job_id)
        if job and job.get("status") != "cancelled":
            with sqlite3.connect(db_path) as conn:
                logs = json.loads(job.get("logs", "[]") or "[]")
                logs.append({"time": datetime.now().strftime("%H:%M:%S"), "level": level, "msg": msg})
                conn.execute("UPDATE jobs SET logs = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND status != 'cancelled'", (json.dumps(logs[-500:]), job_id))
                conn.commit()

    try:
        if not _wait_for_slot(db_path, job_id):
            return
        update(status="running", step="Initializing")
        log("INFO", "→ Initializing")
        topic = params["topic"]

        from ai_video_factory.pipeline import PipelineContext, build_director_pipeline

        ctx = PipelineContext(
            topic=topic,
            raw_video=params.get("raw_video"),
            target_seconds=params.get("target_seconds", 45.0),
            skip_qc=params.get("skip_qc", False),
            use_groq=params.get("use_groq", False),
            model_key=params.get("model_key"),
            groq_key=params.get("groq_key"),
        )

        safe_topic = re.sub(r"[^A-Za-z0-9_-]", "_", topic)[:40].strip("_") or "job"
        pkg_dir = os.path.join(output_root, f"{safe_topic}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{job_id[-6:]}")
        os.makedirs(pkg_dir, exist_ok=True)
        ctx.package_dir = pkg_dir

        update(step="Running Pipeline")
        log("INFO", "→ Running Pipeline")
        pipeline = build_director_pipeline()
        ctx = pipeline.run(ctx)

        if _read_job_snapshot(db_path, job_id) and _read_job_snapshot(db_path, job_id).get("status") == "cancelled":
            return
        if ctx.errors:
            for err in ctx.errors:
                log("ERROR", err)
            update(status="error", error="; ".join(ctx.errors), pkg_dir=pkg_dir)
        else:
            update(status="done", pkg_dir=pkg_dir, step="Complete")
            log("INFO", "Job complete!")
    except Exception as exc:
        log("ERROR", f"Job failed: {exc}")
        update(status="error", error=str(exc))


@app.route("/login", methods=["GET", "POST"])
def login():
    if not _configured_security():
        return render_template("login.html", error="Set FLASK_SECRET_KEY and AIVF_ADMIN_PASSWORD before starting the dashboard."), 503
    if request.method == "POST":
        password = request.form.get("password", "")
        expected = _auth_password() or ""
        valid = check_password_hash(expected, password) if expected.startswith("scrypt:") or expected.startswith("pbkdf2:") else password == expected
        if valid:
            session.clear()
            session["authenticated"] = True
            next_url = request.form.get("next", "")
            return redirect(next_url if _is_safe_next(next_url) else url_for("index"))
        return render_template("login.html", error="Invalid password."), 401
    return render_template("login.html", error=None, next=request.args.get("next", ""))


@app.post("/logout")
def logout():
    error = _validate_state_change()
    if error:
        return error
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
def index():
    if not _configured_security() or not session.get("authenticated"):
        return redirect(url_for("login", next="/"))
    return render_template("index.html")


@app.route("/api/settings", methods=["GET", "POST"])
def settings():
    if request.method == "GET":
        error = _require_auth()
        if error:
            return error
        return jsonify(get_settings())
    error = _validate_state_change()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    try:
        for key, value in data.items():
            set_setting(key, value)
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(get_settings())


def _validate_video_upload(filename: str) -> bool:
    return bool(filename) and Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


def _build_job_params(data: dict, upload) -> Tuple[dict, Optional[str]]:
    settings = get_settings()
    topic = str(data.get("topic", "")).strip()
    if not topic or len(topic) < 2 or len(topic) > 200:
        raise ValueError("Topic must be between 2 and 200 characters")
    target = float(data.get("target_seconds", settings.get("default_target_seconds", 45)))
    if not 15 <= target <= 120:
        raise ValueError("target_seconds must be between 15 and 120")
    workflow = str(data.get("workflow", settings.get("default_workflow", "director")))
    if workflow not in VALID_WORKFLOWS:
        raise ValueError("Unsupported workflow")

    params = {
        "topic": topic,
        "target_seconds": target,
        "workflow": workflow,
        "use_groq": bool(data.get("use_groq", False)),
        "groq_key": str(data.get("groq_key", "")).strip() or get_setting_value("groq_key", ""),
        "model_key": str(data.get("model_key", "")).strip() or get_setting_value("model_key", ""),
        "skip_qc": bool(data.get("skip_qc", settings.get("default_skip_qc", False))),
    }

    raw_path = None
    if upload:
        filename = secure_filename(upload.filename or "")
        if not filename or not _validate_video_upload(filename):
            raise ValueError("Invalid video file type")
        generated = f"{uuid.uuid4().hex}{Path(filename).suffix.lower()}"
        raw_path = str(UPLOAD_FOLDER / generated)
        upload.save(raw_path)
        params["raw_video"] = raw_path
    return params, raw_path


def _queue_job(data: dict, upload=None):
    client_ip = request.remote_addr or "unknown"
    if not check_rate_limit(client_ip):
        return jsonify({"error": "Rate limit exceeded. Try again in a minute."}), 429
    try:
        params, _ = _build_job_params(data, upload)
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        stat = os.statvfs(str(UPLOAD_FOLDER))
        free_mb = (stat.f_bavail * stat.f_frsize) / (1024 * 1024)
    except OSError:
        free_mb = 0
    if free_mb < 1000:
        return jsonify({"error": "Server disk space low. Cannot accept new jobs."}), 503

    job_id = f"job_{uuid.uuid4().hex[:12]}"
    db_insert_job(job_id, params["topic"], params)
    try:
        _job_futures[job_id] = _executor.submit(_run_job_worker, job_id, params, str(OUTPUT_FOLDER), str(DB_PATH))
    except Exception as exc:
        db_update_job(job_id, status="error", error=f"Could not queue job: {exc}")
        return jsonify({"error": "Could not queue job"}), 503
    return jsonify({"job_id": job_id, "status": "queued"})


@app.route("/api/run", methods=["POST"])
def run_api():
    error = _validate_state_change()
    if error:
        return error
    data = request.form.to_dict() if request.form else (request.get_json(silent=True) or {})
    upload = request.files.get("raw_video") if request.files else None
    return _queue_job(data, upload)


@app.route("/api/jobs", methods=["POST", "GET"])
def jobs_api():
    if request.method == "GET":
        error = _require_auth()
        if error:
            return error
        jobs = db_list_jobs()
        for job in jobs:
            try:
                job["params"] = json.loads(job.get("params", "{}"))
                job["logs"] = json.loads(job.get("logs", "[]"))[-50:]
            except (TypeError, json.JSONDecodeError):
                job["params"] = {}
                job["logs"] = []
        return jsonify(jobs)
    error = _validate_state_change()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    return _queue_job(data)


@app.route("/api/jobs/<job_id>", methods=["GET"])
def get_job(job_id: str):
    error = _require_auth()
    if error:
        return error
    job = db_get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    try:
        job["params"] = json.loads(job.get("params", "{}"))
        job["logs"] = json.loads(job.get("logs", "[]"))[-100:]
    except (TypeError, json.JSONDecodeError):
        job["params"] = {}
        job["logs"] = []
    return jsonify(job)


@app.route("/api/jobs/<job_id>/status", methods=["GET"])
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
    error = _validate_state_change()
    if error:
        return error
    job = db_get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    if job["status"] in {"done", "error", "cancelled"}:
        return jsonify({"job_id": job_id, "status": job["status"]})
    future = _job_futures.get(job_id)
    if future and future.cancel():
        db_update_job(job_id, status="cancelled", step="cancelled")
    else:
        # Running worker will notice this state and will not overwrite it.
        db_update_job(job_id, status="cancelled", step="cancelled")
    return jsonify({"job_id": job_id, "status": "cancelled"})


@app.route("/api/jobs/<job_id>/logs")
@app.route("/api/jobs/<job_id>/logs/stream")
def job_logs_stream(job_id: str):
    error = _require_auth()
    if error:
        return error

    def stream():
        last_len = 0
        while True:
            job = db_get_job(job_id)
            if not job:
                yield f"data: {json.dumps({'level': 'ERROR', 'msg': 'Job not found'})}\n\n"
                return
            try:
                logs = json.loads(job.get("logs", "[]") or "[]")
            except json.JSONDecodeError:
                logs = []
            for entry in logs[last_len:]:
                yield f"data: {json.dumps(entry)}\n\n"
            last_len = len(logs)
            if job.get("status") in {"done", "error", "cancelled"}:
                break
            time.sleep(0.5)

    return Response(stream(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/queue/status")
def queue_status():
    error = _require_auth()
    if error:
        return error
    jobs = db_list_jobs()
    return jsonify({
        "running": sum(j["status"] == "running" for j in jobs),
        "queued": sum(j["status"] == "queued" for j in jobs),
        "done": sum(j["status"] == "done" for j in jobs),
        "error": sum(j["status"] == "error" for j in jobs),
        "cancelled": sum(j["status"] == "cancelled" for j in jobs),
        "max_concurrent_jobs": MAX_CONCURRENT_JOBS,
    })


@app.route("/api/packages")
def list_packages():
    error = _require_auth()
    if error:
        return error
    packages = []
    if OUTPUT_FOLDER.exists():
        for pkg_path in sorted((p for p in OUTPUT_FOLDER.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True):
            thumbnails = []
            for t in ["thumbnail.png", "thumbnail_vertical.png"]:
                if (pkg_path / t).exists():
                    thumbnails.append(f"/api/package/{pkg_path.name}/file/{t}")
            thumbs_dir = pkg_path / "thumbnails"
            if thumbs_dir.is_dir():
                thumbnails.extend(f"/api/package/{pkg_path.name}/file/thumbnails/{p.name}" for p in sorted(thumbs_dir.iterdir()) if p.is_file())
            script_preview = ""
            script_file = pkg_path / "script.txt"
            if script_file.exists():
                try:
                    script_preview = script_file.read_text(encoding="utf-8")[:200]
                except OSError:
                    script_preview = ""
            has_video = any((pkg_path / v).exists() for v in ["final_short.mp4", "final_with_music.mp4", "final_short_vo.mp4"])
            packages.append({
                "name": pkg_path.name,
                "created": datetime.fromtimestamp(pkg_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                "thumbnail": thumbnails[0] if thumbnails else None,
                "thumbnails": thumbnails,
                "script_preview": script_preview,
                "has_video": has_video,
            })
    return jsonify(packages)


def _safe_package_path(name: str) -> Optional[Path]:
    if not name or Path(name).name != name:
        return None
    pkg_dir = (OUTPUT_FOLDER / name).resolve()
    try:
        pkg_dir.relative_to(OUTPUT_FOLDER.resolve())
    except ValueError:
        return None
    return pkg_dir if pkg_dir.is_dir() else None


@app.route("/api/package/<name>/script", methods=["GET", "POST"])
def package_script(name: str):
    error = _validate_state_change() if request.method == "POST" else _require_auth()
    if error:
        return error
    pkg_dir = _safe_package_path(name)
    if not pkg_dir:
        return jsonify({"error": "Package not found"}), 404
    path = pkg_dir / "script.txt"
    if request.method == "GET":
        try:
            return jsonify({"script": path.read_text(encoding="utf-8") if path.exists() else ""})
        except OSError as exc:
            return jsonify({"error": str(exc)}), 500
    data = request.get_json(silent=True) or {}
    script = str(data.get("script", ""))
    if len(script) > 50000:
        return jsonify({"error": "Script is too long"}), 400
    path.write_text(script, encoding="utf-8")
    return jsonify({"ok": True})


@app.route("/api/package/<name>/files")
def package_files(name: str):
    error = _require_auth()
    if error:
        return error
    pkg_dir = _safe_package_path(name)
    if not pkg_dir:
        return jsonify({"error": "Package not found"}), 404
    files = []
    for path in sorted(pkg_dir.rglob("*")):
        if path.is_file():
            rel = path.relative_to(pkg_dir).as_posix()
            files.append({"path": rel, "size": path.stat().st_size})
    return jsonify(files)


@app.route("/api/package/<name>/file/<path:filename>")
def package_file(name: str, filename: str):
    error = _require_auth()
    if error:
        return error
    pkg_dir = _safe_package_path(name)
    if not pkg_dir:
        return jsonify({"error": "Package not found"}), 404
    target = (pkg_dir / filename).resolve()
    try:
        target.relative_to(pkg_dir)
    except ValueError:
        return jsonify({"error": "Invalid file path"}), 400
    if not target.is_file():
        return jsonify({"error": "File not found"}), 404
    return send_from_directory(pkg_dir, filename, conditional=True)


@app.route("/api/presets", methods=["GET", "POST"])
def presets():
    if request.method == "GET":
        error = _require_auth()
        if error:
            return error
        result = {}
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute("SELECT key, value FROM settings WHERE key LIKE 'preset:%'").fetchall()
        for key, value in rows:
            try:
                result[key.split(":", 1)[1]] = json.loads(value)
            except json.JSONDecodeError:
                continue
        return jsonify(result)
    error = _validate_state_change()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    name = re.sub(r"[^A-Za-z0-9_-]", "_", str(data.get("name", "")).strip())[:50]
    config = data.get("config")
    if not name or not isinstance(config, dict):
        return jsonify({"error": "Invalid preset"}), 400
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (f"preset:{name}", json.dumps(config)))
        conn.commit()
    return jsonify({"ok": True, "name": name})


@app.before_request
def startup_and_security():
    if not app.config.get("_health_checked"):
        health_check()
        app.config["_health_checked"] = True


def health_check() -> None:
    if not shutil.which("ffmpeg"):
        logger.warning("FFmpeg is not installed or not on PATH; video jobs may fail.")
    tts_available = any(importlib.util.find_spec(name) is not None for name in ("edge_tts", "pyttsx3", "elevenlabs"))
    if not tts_available:
        logger.warning("No TTS provider detected; voiceover generation may be unavailable.")


@app.route("/api/health")
def health():
    try:
        stat = os.statvfs(str(UPLOAD_FOLDER))
        free_mb = (stat.f_bavail * stat.f_frsize) / (1024 * 1024)
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


def cleanup_old_packages(max_age_days: float = 7.0) -> List[str]:
    if not 0 < max_age_days <= 3650:
        raise ValueError("max_age_days must be between 0 and 3650")
    cutoff = time.time() - (max_age_days * 86400)
    removed: List[str] = []
    if not OUTPUT_FOLDER.exists():
        return removed
    for child in OUTPUT_FOLDER.iterdir():
        if child.is_dir() and child.stat().st_mtime < cutoff:
            shutil.rmtree(child, ignore_errors=True)
            removed.append(child.name)
    return removed


@app.route("/api/admin/cleanup", methods=["POST"])
def cleanup_packages_admin():
    error = _validate_state_change()
    if error:
        return error
    try:
        days = float(request.args.get("max_age_days", "7"))
        removed = cleanup_old_packages(days)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"removed": removed, "count": len(removed)})


if __name__ == "__main__":
    if not _configured_security():
        raise SystemExit("Set FLASK_SECRET_KEY and AIVF_ADMIN_PASSWORD before starting the dashboard.")
    logger.info("AI VIDEO FACTORY — Production Web Dashboard v2")
    logger.info("Database: %s", DB_PATH)
    logger.info("Output: %s", OUTPUT_FOLDER)
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
