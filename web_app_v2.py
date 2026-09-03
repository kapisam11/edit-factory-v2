"""AI Video Factory — Production Web Dashboard v2.

Fixes all issues from the original:
- SQLite persistence for jobs (not global dict)
- ProcessPoolExecutor for actual parallelism
- No Flask debug mode
- Input validation + rate limiting
- Disk quota checks
- Proper error handling
"""
import importlib.util
import json
import logging
import os
import shutil
import sqlite3
import time
import uuid
from concurrent.futures import Future, ProcessPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import (
    Flask,
    Response,
    jsonify,
    render_template,
    request,
    send_from_directory,
)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", "dev-key-change-me")

logger = logging.getLogger("web_app_v2")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv"}

BASE_DIR = Path(__file__).parent.resolve()
UPLOAD_FOLDER = BASE_DIR / "uploads"
OUTPUT_FOLDER = BASE_DIR / "output"
DB_PATH = BASE_DIR / "jobs.db"
UPLOAD_FOLDER.mkdir(exist_ok=True)
OUTPUT_FOLDER.mkdir(exist_ok=True)

# Worker pool for parallel job execution
_executor = ProcessPoolExecutor(max_workers=2)
_job_futures: Dict[str, Future] = {}


def init_db():
    """Initialize SQLite database for job persistence."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
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
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rate_limits (
                client_ip TEXT NOT NULL,
                ts REAL NOT NULL
            )
        """)
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
    with sqlite3.connect(DB_PATH) as conn:
        fields = []
        values = []
        for k, v in kwargs.items():
            fields.append(f"{k} = ?")
            values.append(v)
        values.append(job_id)
        conn.execute(
            f"UPDATE jobs SET {', '.join(fields)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            values,
        )
        conn.commit()


def db_get_job(job_id: str) -> dict:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None


def db_list_jobs() -> list:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT 100"
        ).fetchall()
        return [dict(r) for r in rows]


def db_append_log(job_id: str, level: str, msg: str) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT logs FROM jobs WHERE id = ?", (job_id,)).fetchone()
        logs = json.loads(row[0]) if row and row[0] else []
        logs.append({
            "time": datetime.now().strftime("%H:%M:%S"),
            "level": level,
            "msg": msg,
        })
        conn.execute(
            "UPDATE jobs SET logs = ? WHERE id = ?",
            (json.dumps(logs[-500:]), job_id),  # Keep last 500 logs
        )
        conn.commit()


def get_settings() -> dict:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        settings = {k: json.loads(v) for k, v in rows}
    defaults = {
        "default_target_seconds": 45.0,
        "default_workflow": "director",
        "default_skip_qc": False,
        "default_use_groq": False,
        "output_folder": str(OUTPUT_FOLDER),
        "groq_key": "",
        "model_key": "",
        "elevenlabs_key": "",
        "max_upload_mb": 500,
        "max_concurrent_jobs": 2,
    }
    defaults.update(settings)
    return defaults


def set_setting(key: str, value) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, json.dumps(value)),
        )
        conn.commit()


# --- Rate limiting (SQLite-backed so it works across workers) ---
def check_rate_limit(client_ip: str, max_requests: int = 10, window_seconds: int = 60) -> bool:
    now = time.time()
    cutoff = now - window_seconds
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM rate_limits WHERE client_ip = ? AND ts < ?", (client_ip, cutoff))
        count = conn.execute(
            "SELECT COUNT(*) FROM rate_limits WHERE client_ip = ?",
            (client_ip,),
        ).fetchone()[0]
        if count >= max_requests:
            return False
        conn.execute(
            "INSERT INTO rate_limits (client_ip, ts) VALUES (?, ?)",
            (client_ip, now),
        )
        conn.commit()
    return True


# --- Job execution worker ---
def _run_job_worker(job_id: str, params: dict, output_root: str, db_path: str):
    """Run in a separate process. Must be picklable — no closures."""
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    def db_worker_update(**kwargs):
        with sqlite3.connect(db_path) as conn:
            fields = []
            values = []
            for k, v in kwargs.items():
                fields.append(f"{k} = ?")
                values.append(v)
            values.append(job_id)
            conn.execute(
                f"UPDATE jobs SET {', '.join(fields)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                values,
            )
            conn.commit()

    def log(level: str, msg: str):
        with sqlite3.connect(db_path) as conn:
            row = conn.execute("SELECT logs FROM jobs WHERE id = ?", (job_id,)).fetchone()
            logs = json.loads(row[0]) if row and row[0] else []
            logs.append({
                "time": datetime.now().strftime("%H:%M:%S"),
                "level": level,
                "msg": msg,
            })
            conn.execute(
                "UPDATE jobs SET logs = ? WHERE id = ?",
                (json.dumps(logs[-500:]), job_id),
            )
            conn.commit()

    def step_update(step_name: str):
        db_worker_update(step=step_name)
        log("INFO", f"→ {step_name}")

    try:
        step_update("Initializing")
        topic = params["topic"]

        from ai_video_factory.pipeline import build_director_pipeline, PipelineContext

        ctx = PipelineContext(
            topic=topic,
            raw_video=params.get("raw_video"),
            target_seconds=params.get("target_seconds", 45.0),
            skip_qc=params.get("skip_qc", False),
            use_groq=params.get("use_groq", False),
            model_key=params.get("model_key"),
            groq_key=params.get("groq_key"),
        )

        pkg_name = f"{topic.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        pkg_dir = os.path.join(output_root, pkg_name)
        os.makedirs(pkg_dir, exist_ok=True)
        ctx.package_dir = pkg_dir

        step_update("Running Pipeline")
        pipeline = build_director_pipeline()
        ctx = pipeline.run(ctx)

        if ctx.errors:
            for err in ctx.errors:
                log("ERROR", err)
            db_worker_update(status="error", error="; ".join(ctx.errors), pkg_dir=pkg_dir)
        else:
            db_worker_update(status="done", pkg_dir=pkg_dir)
            log("INFO", "Job complete!")

    except Exception as exc:
        log("ERROR", f"Job failed: {exc}")
        db_worker_update(status="error", error=str(exc))


# --- Routes ---

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        data = request.get_json() or {}
        for k, v in data.items():
            set_setting(k, v)
        return jsonify(get_settings())
    return jsonify(get_settings())


def _validate_video_upload(filename: str) -> bool:
    return bool(filename) and any(filename.lower().endswith(ext) for ext in ALLOWED_EXTENSIONS)


@app.route("/api/jobs", methods=["POST"])
def create_job():
    client_ip = request.remote_addr or "unknown"
    if not check_rate_limit(client_ip):
        return jsonify({"error": "Rate limit exceeded. Try again in a minute."}), 429

    data = request.get_json(silent=True) or {}
    if request.files and "raw_video" in request.files:
        upload = request.files["raw_video"]
        if not upload or not _validate_video_upload(upload.filename or ""):
            return jsonify({"error": "Invalid file type"}), 400
        data["raw_video"] = upload.filename

    topic = str(data.get("topic", "")).strip()
    if not topic or len(topic) < 2:
        return jsonify({"error": "Topic must be at least 2 characters"}), 400

    settings = get_settings()
    job_id = f"job_{uuid.uuid4().hex[:12]}"
    params = {
        "topic": topic,
        "target_seconds": float(data.get("target_seconds", settings.get("default_target_seconds", 45))),
        "workflow": data.get("workflow", settings.get("default_workflow", "director")),
        "use_groq": bool(data.get("use_groq", False)),
        "groq_key": str(data.get("groq_key", "")).strip() or settings.get("groq_key", ""),
        "model_key": str(data.get("model_key", "")).strip() or settings.get("model_key", ""),
        "skip_qc": bool(data.get("skip_qc", False)),
        "elevenlabs_key": str(data.get("elevenlabs_key", "")).strip() or settings.get("elevenlabs_key", ""),
    }

    if request.files and "raw_video" in request.files:
        upload = request.files["raw_video"]
        safe_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{upload.filename}"
        upload_path = UPLOAD_FOLDER / safe_name
        upload.save(upload_path)
        params["raw_video"] = str(upload_path)

    try:
        stat = os.statvfs(str(UPLOAD_FOLDER))
        free_mb = (stat.f_bavail * stat.f_frsize) / (1024 * 1024)
    except Exception:
        free_mb = 2000
    if free_mb < 1000:
        return jsonify({"error": "Server disk space low. Cannot accept new jobs."}), 503

    db_insert_job(job_id, topic, params)
    future = _executor.submit(_run_job_worker, job_id, params, str(OUTPUT_FOLDER), str(DB_PATH))
    _job_futures[job_id] = future

    return jsonify({"job_id": job_id, "status": "queued"})


@app.route("/api/jobs", methods=["GET"])
def list_jobs():
    jobs = db_list_jobs()
    for job in jobs:
        try:
            job["params"] = json.loads(job.get("params", "{}"))
            job["logs"] = json.loads(job.get("logs", "[]"))[-50:]  # Last 50 logs
        except:
            pass
    return jsonify(jobs)


@app.route("/api/jobs/<job_id>", methods=["GET"])
def get_job(job_id):
    job = db_get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    try:
        job["params"] = json.loads(job.get("params", "{}"))
        job["logs"] = json.loads(job.get("logs", "[]"))[-100:]
    except Exception:
        pass
    return jsonify(job)


@app.route("/api/jobs/<job_id>/cancel", methods=["POST"])
def cancel_job(job_id):
    future = _job_futures.get(job_id)
    if not future:
        return jsonify({"error": "Job not found"}), 404
    if not future.done():
        future.cancel()
    db_update_job(job_id, status="cancelled", step="cancelled")
    return jsonify({"job_id": job_id, "status": "cancelled"})


@app.route("/api/jobs/<job_id>/logs/stream")
def job_logs_stream(job_id):
    def stream():
        last_len = 0
        while True:
            job = db_get_job(job_id)
            if not job:
                yield f"data: {json.dumps({'level': 'ERROR', 'msg': 'Job not found'})}\n\n"
                return
            try:
                logs = json.loads(job.get("logs", "[]"))
            except:
                logs = []
            new_logs = logs[last_len:]
            last_len = len(logs)
            for log_entry in new_logs:
                yield f"data: {json.dumps(log_entry)}\n\n"

            if job.get("status") in ("done", "error"):
                # Send a few more times then close
                time.sleep(1)
                job = db_get_job(job_id)
                if job.get("status") in ("done", "error"):
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
            for t in ["thumbnail.png", "thumbnail_vertical.png"]:
                if (pkg_path / t).exists():
                    thumb = f"/api/packages/{name}/file/{t}"
                    break
            script_preview = ""
            script_file = pkg_path / "script.txt"
            if script_file.exists():
                script_preview = script_file.read_text(encoding="utf-8")[:200]
            has_video = any((pkg_path / v).exists() for v in [
                "final_short.mp4", "final_with_music.mp4", "final_short_vo.mp4"
            ])
            packages.append({
                "name": name,
                "created": datetime.fromtimestamp(pkg_path.stat().st_ctime).strftime("%Y-%m-%d %H:%M"),
                "thumbnail": thumb,
                "script_preview": script_preview,
                "has_video": has_video,
            })
    return jsonify(packages)


@app.route("/api/packages/<name>/file/<path:filename>")
def package_file(name, filename):
    pkg_dir = OUTPUT_FOLDER / name
    if not pkg_dir.exists():
        return jsonify({"error": "Package not found"}), 404
    return send_from_directory(pkg_dir, filename)


def health_check() -> None:
    ffmpeg_ok = shutil.which("ffmpeg") is not None
    tts_available = any(
        importlib.util.find_spec(name) is not None
        for name in ("edge_tts", "pyttsx3", "elevenlabs")
    )
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
        stat = os.statvfs(str(UPLOAD_FOLDER))
        free_mb = (stat.f_bavail * stat.f_frsize) / (1024 * 1024)
    except Exception:
        free_mb = 0
    return jsonify({
        "status": "ok",
        "disk_free_mb": round(free_mb, 1),
        "max_content_length_mb": app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024),
        "ffmpeg_available": shutil.which("ffmpeg") is not None,
        "tts_available": any(importlib.util.find_spec(name) is not None for name in ("edge_tts", "pyttsx3", "elevenlabs")),
    })


def cleanup_old_packages(max_age_days: float = 7.0) -> List[str]:
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
    days = float(request.args.get("max_age_days", "7"))
    removed = cleanup_old_packages(days)
    return jsonify({"removed": removed, "count": len(removed)})


if __name__ == "__main__":
    init_db()
    health_check()
    logger.info("=" * 50)
    logger.info("AI VIDEO FACTORY — Production Web Dashboard v2")
    logger.info("Database: %s", DB_PATH)
    logger.info("Output: %s", OUTPUT_FOLDER)
    logger.info("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
