"""AI Video Factory production dashboard.

Single-host architecture: Flask + SQLite + one spawned process per active job.
Secrets stay in process memory and are never persisted in job records.
"""
import json
import logging
import multiprocessing
import os
import re
import shutil
import sqlite3
import subprocess
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from flask import Flask, Response, abort, jsonify, render_template, request, send_from_directory
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("AIVF_STATE_DIR", BASE_DIR / "state")).resolve()
UPLOAD_FOLDER = Path(os.environ.get("AIVF_UPLOAD_DIR", BASE_DIR / "uploads")).resolve()
OUTPUT_FOLDER = Path(os.environ.get("AIVF_OUTPUT_DIR", BASE_DIR / "output")).resolve()
DB_PATH = STATE_DIR / "jobs.db"
for directory in (STATE_DIR, UPLOAD_FOLDER, OUTPUT_FOLDER):
    directory.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config.update(
    MAX_CONTENT_LENGTH=int(os.environ.get("AIVF_MAX_UPLOAD_MB", "500")) * 1024 * 1024,
    SECRET_KEY=os.environ.get("FLASK_SECRET_KEY", os.urandom(32).hex()),
)

logger = logging.getLogger("web_app_v2")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
SECRET_PARAM_KEYS = {"groq_key", "model_key", "elevenlabs_key"}
TERMINAL_STATUSES = {"done", "error", "cancelled", "interrupted"}
_runtime_secrets: Dict[str, Dict[str, str]] = {}
_runtime_default_secrets: Dict[str, str] = {key: "" for key in SECRET_PARAM_KEYS}
_active_processes: Dict[str, multiprocessing.Process] = {}


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def init_db() -> None:
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                topic TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                step TEXT NOT NULL DEFAULT 'waiting',
                params TEXT NOT NULL DEFAULT '{}',
                pkg_dir TEXT,
                error TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS job_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                level TEXT NOT NULL,
                message TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_job_logs_job_id_id ON job_logs(job_id, id)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rate_limits (
                client_ip TEXT NOT NULL,
                ts REAL NOT NULL
            )
        """)
        if os.environ.get("AIVF_WORKER_PROCESS") != "1":
            conn.execute(
                "UPDATE jobs SET status='interrupted', step='interrupted', updated_at=CURRENT_TIMESTAMP "
                "WHERE status IN ('queued','running','cancelling')"
            )


def db_insert_job(job_id: str, topic: str, params: dict) -> None:
    with get_db() as conn:
        conn.execute("INSERT INTO jobs (id, topic, params) VALUES (?, ?, ?)",
                     (job_id, topic, json.dumps(params)))


def db_update_job(job_id: str, **kwargs: Any) -> int:
    if not kwargs:
        return 0
    allowed = {"status", "step", "params", "pkg_dir", "error"}
    invalid = set(kwargs) - allowed
    if invalid:
        raise ValueError(f"Invalid job fields: {sorted(invalid)}")
    fields = ", ".join(f"{key}=?" for key in kwargs)
    with get_db() as conn:
        cursor = conn.execute(
            f"UPDATE jobs SET {fields}, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            list(kwargs.values()) + [job_id],
        )
        return cursor.rowcount


def db_get_job(job_id: str) -> Optional[dict]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None


def db_list_jobs() -> list:
    with get_db() as conn:
        return [dict(row) for row in conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT 100"
        ).fetchall()]


def db_append_log(job_id: str, level: str, message: str) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT INTO job_logs (job_id, level, message) VALUES (?, ?, ?)",
            (job_id, level.upper(), str(message)[:10000]),
        )


def db_logs_since(job_id: str, last_id: int = 0) -> list:
    with get_db() as conn:
        return [dict(row) for row in conn.execute(
            "SELECT id, created_at, level, message FROM job_logs WHERE job_id=? AND id>? ORDER BY id ASC",
            (job_id, last_id),
        ).fetchall()]


def get_settings() -> dict:
    with get_db() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    values = {row["key"]: json.loads(row["value"]) for row in rows}
    defaults = {
        "default_target_seconds": 45.0,
        "default_workflow": "director",
        "default_skip_qc": False,
        "default_use_groq": False,
        "max_upload_mb": app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024),
        "max_concurrent_jobs": int(os.environ.get("AIVF_MAX_CONCURRENT_JOBS", "2")),
    }
    defaults.update({k: v for k, v in values.items() if k not in SECRET_PARAM_KEYS})
    return defaults


def set_setting(key: str, value: Any) -> None:
    if key in SECRET_PARAM_KEYS:
        raise ValueError("API credentials must not be persisted as dashboard settings")
    with get_db() as conn:
        conn.execute(
            "INSERT INTO settings (key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )


def set_runtime_default_secret(key: str, value: str) -> None:
    if key not in SECRET_PARAM_KEYS:
        raise ValueError(f"Unsupported runtime secret: {key}")
    _runtime_default_secrets[key] = str(value or "").strip()


def get_runtime_default_secrets() -> dict:
    return dict(_runtime_default_secrets)


def check_rate_limit(client_ip: str, max_requests: int = 10, window_seconds: int = 60) -> bool:
    now = time.time()
    cutoff = now - window_seconds
    with get_db() as conn:
        conn.execute("DELETE FROM rate_limits WHERE ts<?", (cutoff,))
        count = conn.execute("SELECT COUNT(*) FROM rate_limits WHERE client_ip=?", (client_ip,)).fetchone()[0]
        if count >= max_requests:
            return False
        conn.execute("INSERT INTO rate_limits (client_ip,ts) VALUES (?,?)", (client_ip, now))
    return True


def _safe_topic_slug(topic: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", topic).strip("._-")[:60]
    return slug or "job"


def _safe_package_dir(topic: str, output_root: str) -> Path:
    root = Path(output_root).resolve()
    path = (root / f"{_safe_topic_slug(topic)}_{uuid.uuid4().hex[:10]}").resolve()
    if root not in path.parents:
        raise ValueError("Package path escaped output root")
    path.mkdir(parents=True, exist_ok=False)
    return path


def _probe_video(path: Path) -> bool:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return False
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_type", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=20, check=False,
        )
        data = json.loads(result.stdout or "{}")
        return result.returncode == 0 and bool(data.get("streams"))
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return False


def _redact_job(job: dict, include_logs: bool = False) -> dict:
    result = dict(job)
    try:
        params = json.loads(result.get("params") or "{}")
    except json.JSONDecodeError:
        params = {}
    for key in SECRET_PARAM_KEYS:
        params.pop(key, None)
    result["params"] = params
    if include_logs:
        result["logs"] = [
            {"id": row["id"], "time": row["created_at"], "level": row["level"], "msg": row["message"]}
            for row in db_logs_since(result["id"])
        ]
    return result


def _run_job_worker_impl(job_id: str, params: dict, secrets: dict, output_root: str, db_path: str) -> None:
    def update(**kwargs: Any) -> bool:
        allowed = {"status", "step", "params", "pkg_dir", "error"}
        if set(kwargs) - allowed:
            raise ValueError("Invalid worker update")
        fields = ", ".join(f"{key}=?" for key in kwargs)
        with sqlite3.connect(db_path, timeout=10) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=10000")
            rowcount = conn.execute(
                f"UPDATE jobs SET {fields}, updated_at=CURRENT_TIMESTAMP "
                "WHERE id=? AND status NOT IN ('cancelling','cancelled','interrupted')",
                list(kwargs.values()) + [job_id],
            ).rowcount
            return rowcount > 0

    def log(level: str, message: str) -> None:
        with sqlite3.connect(db_path, timeout=10) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=10000")
            conn.execute("INSERT INTO job_logs (job_id, level, message) VALUES (?, ?, ?)",
                         (job_id, level.upper(), str(message)[:10000]))

    try:
        if not update(status="running", step="Initializing"):
            return
        log("INFO", "→ Initializing")
        from ai_video_factory.pipeline import PipelineContext, build_director_pipeline
        pkg_dir = _safe_package_dir(params["topic"], output_root)
        ctx = PipelineContext(
            topic=params["topic"], raw_video=params.get("raw_video"),
            target_seconds=params.get("target_seconds", 45.0),
            skip_qc=params.get("skip_qc", False), use_groq=params.get("use_groq", False),
            model_key=secrets.get("model_key"), groq_key=secrets.get("groq_key"),
        )
        ctx.package_dir = str(pkg_dir)
        if not update(step="Running Pipeline", pkg_dir=str(pkg_dir)):
            return
        log("INFO", "→ Running Pipeline")
        ctx = build_director_pipeline().run(ctx)
        if ctx.errors:
            message = "; ".join(str(error) for error in ctx.errors)
            if update(status="error", step="failed", error=message, pkg_dir=str(pkg_dir)):
                log("ERROR", message)
        else:
            if update(status="done", step="Complete", pkg_dir=str(pkg_dir)):
                log("INFO", "Job complete!")
    except Exception as exc:
        try:
            if update(status="error", step="failed", error=str(exc)):
                log("ERROR", f"Job failed: {exc}")
        except Exception:
            logger.exception("Could not record worker failure for %s", job_id)


def _running_count() -> int:
    return sum(1 for process in _active_processes.values() if process.is_alive())


def _start_job(job_id: str, params: dict, secrets: dict) -> bool:
    if _running_count() >= max(1, int(get_settings()["max_concurrent_jobs"])):
        return False
    from dashboard_worker import run_job
    ctx = multiprocessing.get_context("spawn")
    process = ctx.Process(target=run_job, args=(job_id, params, secrets, str(OUTPUT_FOLDER), str(DB_PATH)), daemon=False)
    process.start()
    _active_processes[job_id] = process
    return True


def _resolve_package(name: str) -> Optional[Path]:
    root = OUTPUT_FOLDER.resolve()
    candidate = (OUTPUT_FOLDER / name).resolve()
    if root not in candidate.parents or not candidate.is_dir():
        return None
    return candidate


@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.path.startswith("/api/jobs"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.errorhandler(RequestEntityTooLarge)
def too_large(_error):
    return jsonify({"error": "Upload exceeds configured size limit"}), 413


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        for key, value in data.items():
            if key not in SECRET_PARAM_KEYS:
                set_setting(key, value)
    return jsonify(get_settings())


@app.route("/api/jobs", methods=["POST"])
def create_job():
    client_ip = request.remote_addr or "unknown"
    if not check_rate_limit(client_ip):
        return jsonify({"error": "Rate limit exceeded. Try again later."}), 429
    data = request.form.to_dict() if request.form else (request.get_json(silent=True) or {})
    topic = str(data.get("topic", "")).strip()
    if not 2 <= len(topic) <= 500:
        return jsonify({"error": "Topic must be between 2 and 500 characters"}), 400
    settings_data = get_settings()
    try:
        target_seconds = float(data.get("target_seconds", settings_data["default_target_seconds"]))
    except (TypeError, ValueError):
        return jsonify({"error": "target_seconds must be numeric"}), 400
    if not 1 <= target_seconds <= 3600:
        return jsonify({"error": "target_seconds must be between 1 and 3600"}), 400
    params = {
        "topic": topic,
        "target_seconds": target_seconds,
        "workflow": str(data.get("workflow", settings_data["default_workflow"])),
        "use_groq": str(data.get("use_groq", "")).lower() in {"1", "true", "on", "yes"},
        "skip_qc": str(data.get("skip_qc", "")).lower() in {"1", "true", "on", "yes"},
    }
    secrets = get_runtime_default_secrets()
    secrets.update({key: str(data.get(key, "")).strip() for key in SECRET_PARAM_KEYS if data.get(key)})

    upload = request.files.get("raw_video")
    if upload and upload.filename:
        filename = secure_filename(upload.filename)
        suffix = Path(filename).suffix.lower()
        if not filename or suffix not in ALLOWED_EXTENSIONS:
            return jsonify({"error": "Unsupported video file type"}), 400
        upload_path = UPLOAD_FOLDER / f"{uuid.uuid4().hex}{suffix}"
        upload.save(upload_path)
        if not _probe_video(upload_path):
            upload_path.unlink(missing_ok=True)
            return jsonify({"error": "Upload is not a valid video stream"}), 400
        params["raw_video"] = str(upload_path)

    try:
        usage = shutil.disk_usage(UPLOAD_FOLDER)
        if usage.free < 1024 * 1024 * 1024:
            return jsonify({"error": "Server disk space is too low"}), 503
    except OSError:
        pass

    job_id = f"job_{uuid.uuid4().hex[:12]}"
    db_insert_job(job_id, topic, params)
    _runtime_secrets[job_id] = secrets
    _start_job(job_id, params, secrets)
    return jsonify({"job_id": job_id, "status": "queued"}), 202


@app.route("/api/jobs", methods=["GET"])
def list_jobs():
    return jsonify([_redact_job(job) for job in db_list_jobs()])


@app.route("/api/jobs/<job_id>", methods=["GET"])
def get_job(job_id):
    job = db_get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(_redact_job(job, include_logs=True))


@app.route("/api/jobs/<job_id>/status")
def get_job_status(job_id):
    job = db_get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({"id": job_id, "status": job["status"], "step": job["step"], "error": job["error"]})


@app.route("/api/jobs/<job_id>/cancel", methods=["POST"])
def cancel_job(job_id):
    from dashboard_compat import cancel_process
    return cancel_process(job_id)


@app.route("/api/jobs/<job_id>/logs")
@app.route("/api/jobs/<job_id>/logs/stream")
def job_logs_stream(job_id):
    def stream():
        last_id = 0
        while True:
            job = db_get_job(job_id)
            if not job:
                yield "data: " + json.dumps({"level": "ERROR", "msg": "Job not found"}) + "\n\n"
                return
            for row in db_logs_since(job_id, last_id):
                last_id = row["id"]
                yield "data: " + json.dumps({"time": row["created_at"], "level": row["level"], "msg": row["message"]}) + "\n\n"
            if job["status"] in TERMINAL_STATUSES:
                return
            yield ": heartbeat\n\n"
            time.sleep(0.5)
    return Response(stream(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/packages")
def list_packages():
    packages = []
    for pkg_path in sorted((p for p in OUTPUT_FOLDER.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True):
        thumb = next((f"/api/packages/{pkg_path.name}/file/{name}" for name in ("thumbnail.png", "thumbnail_vertical.png") if (pkg_path / name).exists()), None)
        script = pkg_path / "script.txt"
        preview = script.read_text(encoding="utf-8", errors="replace")[:200] if script.exists() else ""
        packages.append({"name": pkg_path.name, "created": datetime.fromtimestamp(pkg_path.stat().st_ctime).strftime("%Y-%m-%d %H:%M"), "thumbnail": thumb, "script_preview": preview, "has_video": any((pkg_path / name).exists() for name in ("final_short.mp4", "final_with_music.mp4", "final_short_vo.mp4"))})
    return jsonify(packages)


@app.route("/api/packages/<name>/file/<path:filename>")
def package_file(name, filename):
    pkg_dir = _resolve_package(name)
    if not pkg_dir:
        abort(404)
    return send_from_directory(pkg_dir, filename)


@app.route("/api/health")
def health():
    usage = shutil.disk_usage(UPLOAD_FOLDER)
    return jsonify({"status": "ok", "disk_free_mb": round(usage.free / (1024 * 1024), 1), "ffmpeg_available": shutil.which("ffmpeg") is not None, "ffprobe_available": shutil.which("ffprobe") is not None, "active_jobs": _running_count(), "max_content_length_mb": app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)})


init_db()

if __name__ == "__main__":
    from dashboard_auth import configure_dashboard_auth
    from dashboard_compat import register_dashboard_compat
    configure_dashboard_auth(app)
    register_dashboard_compat(app)
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
