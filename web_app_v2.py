"""Production web dashboard for AI Video Factory.

The Flask app owns HTTP/state concerns only. Job execution lives in worker.py
so Windows spawn semantics never import a module that creates a child process
pool at import time.
"""
from __future__ import annotations

import atexit
import hmac
import importlib.util
import json
import logging
import multiprocessing as mp
import os
import shutil
import signal
import sqlite3
import subprocess
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Flask, Response, jsonify, render_template, request, send_from_directory
from werkzeug.utils import secure_filename

from ai_video_factory.config import AIVFConfig
from ai_video_factory.validation import normalize_workflow, stage_skips_for_pipeline, validate_target_seconds

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", "dev-key-change-me")

logger = logging.getLogger("web_app_v2")
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv"}
PUBLIC_SETTINGS = {
    "default_target_seconds",
    "default_workflow",
    "default_skip_qc",
    "default_use_groq",
    "output_folder",
    "max_upload_mb",
    "max_concurrent_jobs",
}
SECRET_KEYS = {"groq_key", "model_key", "elevenlabs_key"}
_RUNTIME_SECRETS: Dict[str, str] = {}

BASE_DIR = Path(__file__).parent.resolve()
UPLOAD_FOLDER = BASE_DIR / "uploads"
OUTPUT_FOLDER = BASE_DIR / "output"
DB_PATH = BASE_DIR / "jobs.db"
UPLOAD_FOLDER.mkdir(exist_ok=True)
OUTPUT_FOLDER.mkdir(exist_ok=True)

_job_processes: Dict[str, mp.Process] = {}
_job_monitors: Dict[str, threading.Thread] = {}
_cleanup_stop = threading.Event()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """Initialize SQLite and reconcile jobs left running by a crash/restart."""
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                topic TEXT NOT NULL,
                status TEXT DEFAULT 'queued',
                step TEXT DEFAULT 'waiting',
                progress INTEGER DEFAULT 0,
                worker_pid INTEGER,
                params TEXT,
                pkg_dir TEXT,
                error TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                logs TEXT DEFAULT '[]',
                cancel_requested INTEGER DEFAULT 0
            )
            """
        )
        conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS rate_limits (client_ip TEXT NOT NULL, ts REAL NOT NULL)")
        existing = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
        migrations = {
            "progress": "ALTER TABLE jobs ADD COLUMN progress INTEGER DEFAULT 0",
            "worker_pid": "ALTER TABLE jobs ADD COLUMN worker_pid INTEGER",
            "cancel_requested": "ALTER TABLE jobs ADD COLUMN cancel_requested INTEGER DEFAULT 0",
        }
        for column, sql in migrations.items():
            if column not in existing:
                conn.execute(sql)
        conn.execute(
            "UPDATE jobs SET status='interrupted', step='interrupted', error='Web process restarted while job was running' WHERE status='running'"
        )
        conn.commit()


def db_insert_job(job_id: str, topic: str, params: dict) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO jobs (id, topic, status, step, params) VALUES (?, ?, ?, ?, ?)",
            (job_id, topic, "queued", "waiting", json.dumps(params)),
        )
        conn.commit()


def db_update_job(job_id: str, **kwargs: Any) -> None:
    if not kwargs:
        return
    with _connect() as conn:
        fields = []
        values = []
        for key, value in kwargs.items():
            fields.append(f"{key} = ?")
            values.append(value)
        values.append(job_id)
        conn.execute(
            f"UPDATE jobs SET {', '.join(fields)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            values,
        )
        conn.commit()


def db_get_job(job_id: str) -> Optional[dict]:
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None


def db_list_jobs() -> list:
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT 100").fetchall()
        return [dict(row) for row in rows]


def db_append_log(job_id: str, level: str, msg: str) -> None:
    with _connect() as conn:
        row = conn.execute("SELECT logs FROM jobs WHERE id = ?", (job_id,)).fetchone()
        logs = json.loads(row[0]) if row and row[0] else []
        logs.append({"time": datetime.now().strftime("%H:%M:%S"), "level": level, "msg": msg})
        conn.execute(
            "UPDATE jobs SET logs = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(logs[-500:]), job_id),
        )
        conn.commit()


def get_settings() -> dict:
    with _connect() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        stored = {key: json.loads(value) for key, value in rows}
    defaults = {
        "default_target_seconds": 45.0,
        "default_workflow": "director",
        "default_skip_qc": False,
        "default_use_groq": False,
        "output_folder": str(OUTPUT_FOLDER),
        "max_upload_mb": 500,
        "max_concurrent_jobs": 2,
    }
    defaults.update({key: value for key, value in stored.items() if key in PUBLIC_SETTINGS})
    defaults.update({
        "groq_key_configured": bool(_RUNTIME_SECRETS.get("groq_key")),
        "model_key_configured": bool(_RUNTIME_SECRETS.get("model_key")),
        "elevenlabs_key_configured": bool(_RUNTIME_SECRETS.get("elevenlabs_key")),
        "api_keys_scope": "process-lifetime-only",
    })
    return defaults


def set_setting(key: str, value: Any) -> None:
    if key in SECRET_KEYS:
        _RUNTIME_SECRETS[key] = str(value or "").strip()
        return
    if key not in PUBLIC_SETTINGS:
        raise ValueError(f"Unsupported setting: {key}")
    with _connect() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, json.dumps(value)))
        conn.commit()


def check_admin_password(candidate: str, expected: Optional[str] = None) -> bool:
    """Timing-safe plaintext fallback for installations that use an admin password."""
    expected_value = expected if expected is not None else os.environ.get("AIVF_ADMIN_PASSWORD", "")
    return bool(expected_value) and hmac.compare_digest(str(candidate), str(expected_value))


def check_rate_limit(client_ip: str, max_requests: int = 10, window_seconds: int = 60) -> bool:
    now = time.time()
    cutoff = now - window_seconds
    with _connect() as conn:
        conn.execute("DELETE FROM rate_limits WHERE client_ip = ? AND ts < ?", (client_ip, cutoff))
        count = conn.execute("SELECT COUNT(*) FROM rate_limits WHERE client_ip = ?", (client_ip,)).fetchone()[0]
        if count >= max_requests:
            return False
        conn.execute("INSERT INTO rate_limits (client_ip, ts) VALUES (?, ?)", (client_ip, now))
        conn.commit()
    return True


def _declared_concurrency() -> Optional[int]:
    for name in ("WEB_CONCURRENCY", "GUNICORN_WORKERS"):
        value = os.environ.get(name)
        if value and value.isdigit():
            return int(value)
    args = os.environ.get("GUNICORN_CMD_ARGS", "")
    marker = "--workers="
    if marker in args:
        try:
            return int(args.split(marker, 1)[1].split()[0])
        except ValueError:
            return None
    return None


def enforce_single_web_worker() -> None:
    workers = _declared_concurrency()
    if workers and workers > 1 and os.environ.get("AIVF_ALLOW_MULTI_WEB_WORKER") != "1":
        raise RuntimeError(
            "AI Video Factory dashboard requires one Gunicorn/web worker because job state is process-local. "
            "Set AIVF_ALLOW_MULTI_WEB_WORKER=1 only after moving job orchestration to a shared queue."
        )


def _validate_video_upload(filename: str) -> bool:
    suffix = Path(filename).suffix.lower()
    return bool(filename) and suffix in ALLOWED_EXTENSIONS


def _validate_video_content(path: Path) -> bool:
    """Validate a saved upload using signatures first, then ffprobe when available."""
    try:
        header = path.read_bytes()[:32]
    except OSError:
        return False
    suffix = path.suffix.lower()
    if suffix in {".mp4", ".mov"}:
        signature_ok = len(header) >= 12 and header[4:8] == b"ftyp"
    elif suffix == ".mkv":
        signature_ok = header.startswith(b"\x1a\x45\xdf\xa3")
    elif suffix == ".avi":
        signature_ok = header[:4] == b"RIFF" and header[8:12] == b"AVI "
    else:
        signature_ok = False
    if not signature_ok:
        return False
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return True
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=format_name", "-of", "default=nw=1:nk=1", str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def _worker_monitor(job_id: str, process: mp.Process) -> None:
    process.join()
    _job_processes.pop(job_id, None)
    _job_monitors.pop(job_id, None)
    job = db_get_job(job_id)
    if job and job.get("status") == "running" and process.exitcode not in (0, None):
        db_update_job(job_id, status="error", step="worker_exit", error=f"Worker exited with code {process.exitcode}")


def _spawn_job(job_id: str, params: dict) -> None:
    ctx = mp.get_context("spawn")
    from worker import run_job_worker

    process = ctx.Process(
        target=run_job_worker,
        args=(job_id, params, str(OUTPUT_FOLDER), str(DB_PATH)),
        name=f"aivf-{job_id}",
        daemon=False,
    )
    process.start()
    _job_processes[job_id] = process
    db_update_job(job_id, worker_pid=process.pid, status="running", step="Starting")
    monitor = threading.Thread(target=_worker_monitor, args=(job_id, process), daemon=True)
    _job_monitors[job_id] = monitor
    monitor.start()


def _shutdown_workers(*_args: Any) -> None:
    _cleanup_stop.set()
    for job_id, process in list(_job_processes.items()):
        if process.is_alive():
            try:
                process.terminate()
            except (OSError, AttributeError):
                logger.exception("Could not terminate worker %s", job_id)
            db_update_job(job_id, status="interrupted", step="shutdown", error="Web process shutting down")


def _cleanup_loop() -> None:
    interval = float(os.environ.get("AIVF_CLEANUP_INTERVAL_SECONDS", "21600"))
    max_age_days = float(os.environ.get("AIVF_RETENTION_DAYS", "7"))
    while not _cleanup_stop.wait(interval):
        try:
            removed = cleanup_old_packages(max_age_days)
            if removed:
                logger.info("Automatic cleanup removed %d package(s)", len(removed))
        except Exception:
            logger.exception("Automatic package cleanup failed")


def start_background_cleanup() -> None:
    if os.environ.get("AIVF_DISABLE_AUTO_CLEANUP") == "1":
        return
    threading.Thread(target=_cleanup_loop, name="aivf-cleanup", daemon=True).start()


init_db()
enforce_single_web_worker()
atexit.register(_shutdown_workers)
if threading.current_thread() is threading.main_thread():
    signal.signal(signal.SIGTERM, _shutdown_workers)
    if hasattr(signal, "SIGINT"):
        signal.signal(signal.SIGINT, _shutdown_workers)
start_background_cleanup()


@app.after_request
def add_security_headers(response: Response) -> Response:
    response.headers.setdefault("Content-Security-Policy", "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if request.is_secure:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        for key, value in data.items():
            set_setting(key, value)
        return jsonify(get_settings())
    return jsonify(get_settings())


@app.route("/api/jobs", methods=["POST"])
def create_job():
    client_ip = request.remote_addr or "unknown"
    if not check_rate_limit(client_ip):
        return jsonify({"error": "Rate limit exceeded. Try again in a minute."}), 429

    data = request.get_json(silent=True) or {}
    upload_path: Optional[Path] = None
    if request.files and "raw_video" in request.files:
        upload = request.files["raw_video"]
        if not upload or not _validate_video_upload(upload.filename or ""):
            return jsonify({"error": "Invalid video file type"}), 400
        safe = secure_filename(upload.filename or "upload")
        upload_path = UPLOAD_FOLDER / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}_{safe}"
        upload.save(upload_path)
        if not _validate_video_content(upload_path):
            upload_path.unlink(missing_ok=True)
            return jsonify({"error": "Upload failed video signature/ffprobe validation"}), 400
        data["raw_video"] = str(upload_path)

    topic = str(data.get("topic", "")).strip()
    if not 2 <= len(topic) <= 200:
        return jsonify({"error": "Topic must be between 2 and 200 characters"}), 400

    settings_data = get_settings()
    try:
        target_seconds = validate_target_seconds(data.get("target_seconds", settings_data["default_target_seconds"]))
        workflow = normalize_workflow(data.get("workflow", settings_data["default_workflow"]))
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400

    config = AIVFConfig.load()
    try:
        skip_stages = stage_skips_for_pipeline(config, workflow)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    job_id = f"job_{uuid.uuid4().hex[:12]}"
    params = {
        "topic": topic,
        "target_seconds": target_seconds,
        "workflow": workflow,
        "skip_stages": skip_stages,
        "raw_video": str(upload_path) if upload_path else data.get("raw_video"),
        "use_groq": bool(data.get("use_groq", settings_data.get("default_use_groq", False))),
        "groq_key": _RUNTIME_SECRETS.get("groq_key", ""),
        "model_key": _RUNTIME_SECRETS.get("model_key", ""),
        "skip_qc": bool(data.get("skip_qc", settings_data.get("default_skip_qc", False))),
        "thumbnail_variant": int(data.get("thumbnail_variant", 1)),
    }
    try:
        if not 1 <= int(params["thumbnail_variant"]) <= 3:
            raise ValueError("thumbnail_variant must be 1, 2, or 3")
    except (ValueError, TypeError) as exc:
        if upload_path:
            upload_path.unlink(missing_ok=True)
        return jsonify({"error": str(exc)}), 400

    max_jobs = max(1, int(settings_data.get("max_concurrent_jobs", 2)))
    active_jobs = sum(1 for process in _job_processes.values() if process.is_alive())
    if active_jobs >= max_jobs:
        if upload_path:
            upload_path.unlink(missing_ok=True)
        return jsonify({"error": "Maximum concurrent jobs reached. Please retry shortly."}), 429

    try:
        free_mb = shutil.disk_usage(UPLOAD_FOLDER).free / (1024 * 1024)
    except OSError:
        free_mb = 0
    if free_mb < 1000:
        if upload_path:
            upload_path.unlink(missing_ok=True)
        return jsonify({"error": "Server disk space low. Cannot accept new jobs."}), 503

    db_insert_job(job_id, topic, params)
    try:
        _spawn_job(job_id, params)
    except Exception as exc:
        logger.exception("Could not start job %s", job_id)
        db_update_job(job_id, status="error", error=str(exc))
        if upload_path:
            upload_path.unlink(missing_ok=True)
        return jsonify({"error": "Could not start job"}), 500
    return jsonify({"job_id": job_id, "status": "running"})


@app.route("/api/jobs", methods=["GET"])
def list_jobs():
    jobs = db_list_jobs()
    for job in jobs:
        try:
            job["params"] = json.loads(job.get("params", "{}"))
            job["logs"] = json.loads(job.get("logs", "[]"))[-50:]
        except (TypeError, ValueError, json.JSONDecodeError):
            job["params"] = {}
            job["logs"] = []
        for key in SECRET_KEYS:
            job["params"].pop(key, None)
    return jsonify(jobs)


@app.route("/api/jobs/<job_id>", methods=["GET"])
def get_job(job_id: str):
    job = db_get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    try:
        job["params"] = json.loads(job.get("params", "{}"))
        job["logs"] = json.loads(job.get("logs", "[]"))[-100:]
    except (TypeError, ValueError, json.JSONDecodeError):
        job["params"] = {}
        job["logs"] = []
    for key in SECRET_KEYS:
        job["params"].pop(key, None)
    return jsonify(job)


@app.route("/api/jobs/<job_id>/cancel", methods=["POST"])
def cancel_job(job_id: str):
    job = db_get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    status = job.get("status")
    if status in {"done", "error", "cancelled", "interrupted"}:
        return jsonify({"job_id": job_id, "status": status})

    process = _job_processes.get(job_id)
    db_update_job(job_id, cancel_requested=1, status="cancelled", step="cancelling")
    if process and process.is_alive():
        try:
            process.terminate()
            process.join(timeout=5)
            if process.is_alive():
                process.kill()
                process.join(timeout=2)
        except (OSError, AttributeError):
            logger.exception("Could not terminate job process %s", job_id)
    db_update_job(job_id, worker_pid=None, status="cancelled", step="cancelled")
    return jsonify({"job_id": job_id, "status": "cancelled"})


@app.route("/api/jobs/<job_id>/logs/stream")
def job_logs_stream(job_id: str):
    def stream():
        last_len = 0
        while True:
            job = db_get_job(job_id)
            if not job:
                yield f"data: {json.dumps({'level': 'ERROR', 'msg': 'Job not found'})}\n\n"
                return
            try:
                logs = json.loads(job.get("logs", "[]"))
            except (TypeError, ValueError, json.JSONDecodeError):
                logs = []
            for entry in logs[last_len:]:
                yield f"data: {json.dumps(entry)}\n\n"
            last_len = len(logs)
            if job.get("status") in {"done", "error", "cancelled", "interrupted"}:
                break
            time.sleep(0.5)
    return Response(stream(), mimetype="text/event-stream")


@app.route("/api/packages")
def list_packages():
    packages = []
    if OUTPUT_FOLDER.exists():
        for name in sorted(os.listdir(OUTPUT_FOLDER), reverse=True):
            pkg_path = OUTPUT_FOLDER / name
            if not pkg_path.is_dir():
                continue
            thumb = None
            for t in ("thumbnail.png", "thumbnail_vertical.png"):
                if (pkg_path / t).exists():
                    thumb = f"/api/packages/{name}/file/{t}"
                    break
            script_preview = ""
            script_file = pkg_path / "script.txt"
            if script_file.exists():
                try:
                    script_preview = script_file.read_text(encoding="utf-8")[:200]
                except OSError:
                    script_preview = ""
            has_video = any((pkg_path / v).exists() for v in ("final_short.mp4", "final_with_music.mp4", "final_short_vo.mp4"))
            packages.append({
                "name": name,
                "created": datetime.fromtimestamp(pkg_path.stat().st_ctime).strftime("%Y-%m-%d %H:%M"),
                "thumbnail": thumb,
                "script_preview": script_preview,
                "has_video": has_video,
            })
    return jsonify(packages)


@app.route("/api/packages/<name>/file/<path:filename>")
def package_file(name: str, filename: str):
    pkg_dir = OUTPUT_FOLDER / name
    if not pkg_dir.exists() or not pkg_dir.is_dir():
        return jsonify({"error": "Package not found"}), 404
    return send_from_directory(pkg_dir, filename)


def health_check() -> None:
    ffmpeg_ok = shutil.which("ffmpeg") is not None
    tts_available = any(importlib.util.find_spec(name) is not None for name in ("edge_tts", "pyttsx3", "elevenlabs"))
    if not ffmpeg_ok:
        logger.warning("FFmpeg is not installed or not on PATH; some jobs may fail.")
    if not tts_available:
        logger.warning("No TTS provider detected; voiceover generation may be unavailable.")


@app.before_request
def _run_startup_health_check():
    if not app.config.get("_health_checked"):
        health_check()
        app.config["_health_checked"] = True


@app.route("/api/health")
def health():
    try:
        free_mb = shutil.disk_usage(UPLOAD_FOLDER).free / (1024 * 1024)
    except OSError:
        free_mb = 0
    return jsonify({
        "status": "ok",
        "disk_free_mb": round(free_mb, 1),
        "max_content_length_mb": app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024),
        "ffmpeg_available": shutil.which("ffmpeg") is not None,
        "tts_available": any(importlib.util.find_spec(name) is not None for name in ("edge_tts", "pyttsx3", "elevenlabs")),
        "active_jobs": sum(1 for process in _job_processes.values() if process.is_alive()),
        "api_keys_scope": "process-lifetime-only",
        "sqlite_wal": True,
    })


def cleanup_old_packages(max_age_days: float = 7.0) -> List[str]:
    cutoff = time.time() - (max_age_days * 86400)
    removed: List[str] = []
    if not OUTPUT_FOLDER.exists():
        return removed
    for child in OUTPUT_FOLDER.iterdir():
        try:
            if child.is_dir() and child.stat().st_mtime < cutoff:
                shutil.rmtree(child, ignore_errors=True)
                removed.append(child.name)
        except OSError:
            logger.exception("Could not inspect/remove package %s", child)
    return removed


@app.route("/api/admin/cleanup", methods=["POST"])
def cleanup_packages_admin():
    try:
        days = float(request.args.get("max_age_days", "7"))
    except ValueError:
        return jsonify({"error": "max_age_days must be a number"}), 400
    if days < 0:
        return jsonify({"error": "max_age_days must be non-negative"}), 400
    removed = cleanup_old_packages(days)
    return jsonify({"removed": removed, "count": len(removed)})


if __name__ == "__main__":
    health_check()
    logger.info("AI VIDEO FACTORY — Production Web Dashboard v2")
    logger.info("Database: %s", DB_PATH)
    logger.info("Output: %s", OUTPUT_FOLDER)
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
