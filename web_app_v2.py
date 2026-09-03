"""Secure production dashboard for AI Video Factory.

The dashboard supports a legacy single admin password plus optional multi-user
password-hash authentication. State-changing routes require same-origin
headers, SQLite uses WAL/busy timeouts, and the bounded ProcessPoolExecutor
controls video-processing concurrency.
"""
import hmac
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

import requests
from flask import Flask, Response, jsonify, redirect, render_template, request, session, url_for, send_from_directory
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename

from ai_video_factory.validation import normalize_workflow, validate_target_seconds

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("AIVF_MAX_UPLOAD_MB", "500")) * 1024 * 1024
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("AIVF_COOKIE_SECURE", "0") == "1"

logger = logging.getLogger("web_app_v2")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
SECRET_KEYS = {"groq_key": "GROQ_API_KEY", "model_key": "OPENAI_API_KEY", "elevenlabs_key": "ELEVENLABS_API_KEY"}
MUTABLE_SETTINGS = {"default_target_seconds", "default_workflow", "default_skip_qc", "default_use_groq", *SECRET_KEYS}
BASE_DIR = Path(__file__).resolve().parent
UPLOAD_FOLDER = BASE_DIR / "uploads"
OUTPUT_FOLDER = BASE_DIR / "output"
DB_PATH = BASE_DIR / "jobs.db"
UPLOAD_FOLDER.mkdir(exist_ok=True)
OUTPUT_FOLDER.mkdir(exist_ok=True)
MAX_CONCURRENT_JOBS = max(1, int(os.environ.get("AIVF_WORKERS", "2")))
_executor = ProcessPoolExecutor(max_workers=MAX_CONCURRENT_JOBS)
_job_futures: Dict[str, Future] = {}


def _db_connect(path: Path = DB_PATH) -> sqlite3.Connection:
    """Open SQLite with WAL and a generous busy timeout for worker contention."""
    conn = sqlite3.connect(path, timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _users_from_env() -> Dict[str, str]:
    raw = os.environ.get("AIVF_ADMIN_USERS_JSON", "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        logger.exception("Ignoring invalid AIVF_ADMIN_USERS_JSON")
        return {}


def _security_ready() -> bool:
    return bool(app.config.get("SECRET_KEY")) and bool(
        os.environ.get("AIVF_ADMIN_PASSWORD") or _users_from_env()
    )


def _auth_error() -> Optional[Response]:
    if not _security_ready():
        return jsonify({"error": "Server security is not configured."}), 503
    if not session.get("authenticated"):
        return jsonify({"error": "Authentication required"}), 401
    return None


def _same_origin_expected() -> str:
    return f"{request.scheme}://{request.host}"


def _state_change_error() -> Optional[Response]:
    error = _auth_error()
    if error:
        return error
    expected = _same_origin_expected()
    origin = request.headers.get("Origin")
    referer = request.headers.get("Referer")
    if not origin and not referer:
        return jsonify({"error": "Missing Origin or Referer header"}), 403
    if origin and origin != expected:
        return jsonify({"error": "Cross-origin request blocked"}), 403
    if referer and not referer.startswith(expected + "/"):
        return jsonify({"error": "Cross-origin request blocked"}), 403
    return None


def _security_headers(response: Response) -> Response:
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
    )
    if app.config.get("SESSION_COOKIE_SECURE") or os.environ.get("AIVF_HSTS", "0") == "1":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


app.after_request(_security_headers)


def init_db() -> None:
    with _db_connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, topic TEXT NOT NULL, status TEXT DEFAULT 'queued', step TEXT DEFAULT 'waiting',
                params TEXT, pkg_dir TEXT, error TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, logs TEXT DEFAULT '[]',
                progress REAL DEFAULT 0, eta_seconds REAL DEFAULT NULL, started_at TIMESTAMP DEFAULT NULL
            )"""
        )
        conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS rate_limits (client_ip TEXT NOT NULL, ts REAL NOT NULL)")
        columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
        for name, ddl in (
            ("progress", "ALTER TABLE jobs ADD COLUMN progress REAL DEFAULT 0"),
            ("eta_seconds", "ALTER TABLE jobs ADD COLUMN eta_seconds REAL"),
            ("started_at", "ALTER TABLE jobs ADD COLUMN started_at TIMESTAMP"),
        ):
            if name not in columns:
                conn.execute(ddl)
        conn.commit()


init_db()


def _redact(params: dict) -> dict:
    result = dict(params)
    for key in SECRET_KEYS:
        if key in result:
            result[key] = "<redacted>" if result[key] else ""
    return result


def _public_job(job: dict) -> dict:
    result = dict(job)
    try:
        result["params"] = _redact(json.loads(result.get("params", "{}")))
    except (TypeError, json.JSONDecodeError):
        result["params"] = {}
    try:
        result["logs"] = json.loads(result.get("logs", "[]") or "[]")[-100:]
    except (TypeError, json.JSONDecodeError):
        result["logs"] = []
    return result


def db_insert_job(job_id: str, topic: str, params: dict) -> None:
    with _db_connect() as conn:
        conn.execute(
            "INSERT INTO jobs (id, topic, status, step, params) VALUES (?, ?, ?, ?, ?)",
            (job_id, topic, "queued", "waiting", json.dumps(_redact(params))),
        )
        conn.commit()


def db_get_job(job_id: str, path: Path = DB_PATH) -> Optional[dict]:
    with _db_connect(path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None


def db_list_jobs() -> List[dict]:
    with _db_connect() as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT 100").fetchall()]


def db_update_job(job_id: str, **kwargs) -> None:
    allowed = {"status", "step", "pkg_dir", "error", "params", "logs", "progress", "eta_seconds", "started_at"}
    clean = {k: v for k, v in kwargs.items() if k in allowed}
    if not clean:
        return
    with _db_connect() as conn:
        fields = [f"{k} = ?" for k in clean]
        conn.execute(
            f"UPDATE jobs SET {', '.join(fields)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            list(clean.values()) + [job_id],
        )
        conn.commit()


def _rate_limit(key: str, limit: int, window: int) -> bool:
    now = time.time()
    cutoff = now - window
    with _db_connect() as conn:
        conn.execute("DELETE FROM rate_limits WHERE client_ip = ? AND ts < ?", (key, cutoff))
        count = conn.execute("SELECT COUNT(*) FROM rate_limits WHERE client_ip = ?", (key,)).fetchone()[0]
        if count >= limit:
            return False
        conn.execute("INSERT INTO rate_limits (client_ip, ts) VALUES (?, ?)", (key, now))
        conn.commit()
    return True


def get_setting(key: str, default: Any = None) -> Any:
    with _db_connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if not row:
        return default
    try:
        return json.loads(row[0])
    except json.JSONDecodeError:
        return default


def get_settings() -> dict:
    with _db_connect() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    stored = {}
    for key, value in rows:
        try:
            stored[key] = json.loads(value)
        except json.JSONDecodeError:
            continue
    result = {
        "default_target_seconds": stored.get("default_target_seconds", 45.0),
        "default_workflow": stored.get("default_workflow", "default"),
        "default_skip_qc": stored.get("default_skip_qc", False),
        "default_use_groq": stored.get("default_use_groq", False),
        "output_folder": str(OUTPUT_FOLDER),
        "max_upload_mb": app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024),
        "max_concurrent_jobs": MAX_CONCURRENT_JOBS,
        "multi_user_auth": bool(_users_from_env()),
        "webhook_configured": bool(os.environ.get("AIVF_WEBHOOK_URL")),
    }
    for key, env_name in SECRET_KEYS.items():
        result[f"has_{key}"] = bool(os.environ.get(env_name))
    return result


def set_setting(key: str, value: Any) -> None:
    if key not in MUTABLE_SETTINGS:
        raise ValueError(f"Setting '{key}' is not writable")
    if key == "default_target_seconds":
        value = validate_target_seconds(value, "default_target_seconds")
    elif key == "default_workflow":
        value = normalize_workflow(str(value))
    elif key in {"default_skip_qc", "default_use_groq"}:
        value = bool(value)
    elif key in SECRET_KEYS:
        value = str(value).strip()
        if value:
            os.environ[SECRET_KEYS[key]] = value
        return
    with _db_connect() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, json.dumps(value)))
        conn.commit()


def _build_params(data: dict, upload=None) -> Tuple[dict, Optional[str]]:
    topic = str(data.get("topic", "")).strip()
    if not 2 <= len(topic) <= 200:
        raise ValueError("Topic must be between 2 and 200 characters")
    target = validate_target_seconds(data.get("target_seconds", get_settings()["default_target_seconds"]))
    workflow = normalize_workflow(str(data.get("workflow", get_settings()["default_workflow"])))
    try:
        thumbnail_variant = int(data.get("thumbnail_variant", 1))
    except (TypeError, ValueError) as exc:
        raise ValueError("thumbnail_variant must be 1, 2, or 3") from exc
    if thumbnail_variant not in {1, 2, 3}:
        raise ValueError("thumbnail_variant must be 1, 2, or 3")
    params = {
        "topic": topic,
        "target_seconds": target,
        "workflow": workflow,
        "use_groq": bool(data.get("use_groq", get_settings()["default_use_groq"])),
        "groq_key": str(data.get("groq_key", "")).strip() or os.environ.get("GROQ_API_KEY", ""),
        "model_key": str(data.get("model_key", "")).strip() or os.environ.get("OPENAI_API_KEY", ""),
        "skip_qc": bool(data.get("skip_qc", get_settings()["default_skip_qc"])),
        "thumbnail_variant": thumbnail_variant,
    }
    raw_path = None
    if upload:
        name = secure_filename(upload.filename or "")
        if not name or Path(name).suffix.lower() not in ALLOWED_EXTENSIONS:
            raise ValueError("Invalid video file type")
        raw_path = str(UPLOAD_FOLDER / f"{uuid.uuid4().hex}{Path(name).suffix.lower()}")
        upload.save(raw_path)
        params["raw_video"] = raw_path
    return params, raw_path


def _validate_video_upload(filename: str) -> bool:
    return bool(filename) and Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


def _read_job(db_path: str, job_id: str) -> Optional[dict]:
    with _db_connect(Path(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None


def _worker_update(db_path: str, job_id: str, **kwargs) -> None:
    allowed = {"status", "step", "pkg_dir", "error", "progress", "eta_seconds", "started_at"}
    clean = {k: v for k, v in kwargs.items() if k in allowed}
    if not clean:
        return
    with _db_connect(Path(db_path)) as conn:
        fields = [f"{k} = ?" for k in clean]
        conn.execute(
            f"UPDATE jobs SET {', '.join(fields)}, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND status != 'cancelled'",
            list(clean.values()) + [job_id],
        )
        conn.commit()


def _worker_log(db_path: str, job_id: str, level: str, message: str) -> None:
    job = _read_job(db_path, job_id)
    if not job or job.get("status") == "cancelled":
        return
    try:
        logs = json.loads(job.get("logs", "[]") or "[]")
    except json.JSONDecodeError:
        logs = []
    logs.append({"time": datetime.now().strftime("%H:%M:%S"), "level": level, "msg": message})
    with _db_connect(Path(db_path)) as conn:
        conn.execute(
            "UPDATE jobs SET logs = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND status != 'cancelled'",
            (json.dumps(logs[-500:]), job_id),
        )
        conn.commit()


def _send_webhook(event: str, job_id: str, topic: str, status: str, error: Optional[str] = None) -> None:
    url = os.environ.get("AIVF_WEBHOOK_URL", "").strip()
    if not url:
        return
    message = f"AI Video Factory: {event} — {topic} ({job_id}) — {status}"
    payload = {"text": message, "content": message, "event": event, "job_id": job_id, "topic": topic, "status": status}
    if error:
        payload["error"] = error[:1000]
    try:
        response = requests.post(url, json=payload, timeout=5)
        response.raise_for_status()
    except requests.RequestException:
        logger.exception("Webhook delivery failed for %s", job_id)


def _run_job_worker(job_id: str, params: dict, output_root: str, db_path: str) -> None:
    try:
        _worker_update(db_path, job_id, status="running", step="Initializing", progress=0, eta_seconds=None, started_at=datetime.utcnow().isoformat())
        _worker_log(db_path, job_id, "INFO", "Initializing")
        from ai_video_factory.pipeline import PipelineContext, build_director_pipeline

        topic = params["topic"]
        started = time.monotonic()
        workflow = normalize_workflow(params.get("workflow", "default"))
        safe_topic = re.sub(r"[^A-Za-z0-9_-]", "_", topic)[:40].strip("_") or "job"
        pkg_dir = os.path.join(output_root, f"{safe_topic}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{job_id[-6:]}")
        os.makedirs(pkg_dir, exist_ok=True)

        def progress(completed: int, total: int, stage: str, elapsed: float, eta: float) -> None:
            percent = round((completed / max(total, 1)) * 100, 1)
            _worker_update(db_path, job_id, step=f"{stage} — {percent:.0f}%", progress=percent, eta_seconds=round(eta, 1))
            _worker_log(db_path, job_id, "INFO", f"→ {stage} ({percent:.0f}%, ETA {eta:.1f}s)")

        ctx = PipelineContext(
            topic=topic,
            package_dir=pkg_dir,
            raw_video=params.get("raw_video"),
            target_seconds=params["target_seconds"],
            skip_qc=params["skip_qc"],
            use_groq=params["use_groq"],
            model_key=params.get("model_key") or None,
            groq_key=params.get("groq_key") or None,
            thumbnail_variant=params.get("thumbnail_variant", 1),
        )
        _worker_update(db_path, job_id, step=f"Pipeline: {workflow}")
        _worker_log(db_path, job_id, "INFO", f"Running pipeline: {workflow}")
        ctx = build_director_pipeline(
            skip_stages=_pipeline_skips(workflow), verbose=False, progress_callback=progress
        ).run(ctx)
        current = _read_job(db_path, job_id)
        if not current or current.get("status") == "cancelled":
            return
        elapsed = time.monotonic() - started
        if ctx.errors:
            for error in ctx.errors:
                _worker_log(db_path, job_id, "ERROR", error)
            error_text = "; ".join(ctx.errors)
            _worker_update(db_path, job_id, status="error", error=error_text, pkg_dir=pkg_dir, progress=100, eta_seconds=0)
            _send_webhook("job failed", job_id, topic, "error", error_text)
        else:
            _worker_update(db_path, job_id, status="done", step=f"Complete — 100% ({elapsed:.1f}s)", pkg_dir=pkg_dir, progress=100, eta_seconds=0)
            _worker_log(db_path, job_id, "INFO", f"Job complete in {elapsed:.1f}s")
            _send_webhook("job complete", job_id, topic, "done")
    except Exception as exc:
        logger.exception("Worker job failed: %s", job_id)
        _worker_log(db_path, job_id, "ERROR", f"Job failed: {exc}")
        _worker_update(db_path, job_id, status="error", error=str(exc), progress=100, eta_seconds=0)
        _send_webhook("job failed", job_id, params.get("topic", "unknown"), "error", str(exc))


def _pipeline_skips(workflow: str) -> List[str]:
    included = {
        "default": {"research", "plan", "script", "thumbnail", "auto_edit", "voiceover", "music", "quality_control", "metadata", "metrics"},
        "fast": {"plan", "script", "auto_edit", "metadata"},
        "package_only": {"research", "plan", "script", "thumbnail", "metadata"},
    }[workflow]
    all_stages = {"research", "plan", "script", "thumbnail", "auto_edit", "voiceover", "music", "quality_control", "metadata", "metrics"}
    return sorted(all_stages - included)


def _verify_login(username: str, password: str) -> bool:
    users = _users_from_env()
    if users:
        stored = users.get(username)
        if not stored:
            return False
        try:
            return check_password_hash(stored, password)
        except (ValueError, TypeError):
            return False
    expected = os.environ.get("AIVF_ADMIN_PASSWORD", "")
    try:
        if expected.startswith(("scrypt:", "pbkdf2:")):
            return check_password_hash(expected, password)
        return hmac.compare_digest(password, expected)
    except (ValueError, TypeError):
        return False


@app.route("/login", methods=["GET", "POST"])
def login():
    if not _security_ready():
        return render_template("login.html", error="Set FLASK_SECRET_KEY and authentication settings before starting the dashboard."), 503
    if request.method == "POST":
        ip = request.remote_addr or "unknown"
        if not _rate_limit(f"login:{ip}", 5, 300):
            return render_template("login.html", error="Too many login attempts. Try again later."), 429
        username = str(request.form.get("username", "admin")).strip() or "admin"
        password = request.form.get("password", "")
        if _verify_login(username, password):
            session.clear()
            session["authenticated"] = True
            session["username"] = username
            return redirect(url_for("index"))
        return render_template("login.html", error="Invalid username or password."), 401
    return render_template("login.html", error=None, next=request.args.get("next", ""), multi_user=bool(_users_from_env()))


@app.post("/logout")
def logout():
    error = _state_change_error()
    if error:
        return error
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
def index():
    if not _security_ready() or not session.get("authenticated"):
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
        "status": "ok" if _security_ready() else "misconfigured",
        "authenticated": bool(session.get("authenticated")),
        "username": session.get("username"),
        "disk_free_mb": round(free_mb, 1),
        "max_content_length_mb": app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024),
        "ffmpeg_available": shutil.which("ffmpeg") is not None,
        "tts_available": any(importlib.util.find_spec(n) is not None for n in ("edge_tts", "pyttsx3", "elevenlabs")),
        "multi_user_auth": bool(_users_from_env()),
    })


@app.route("/api/settings", methods=["GET", "POST"])
def settings():
    error = _state_change_error() if request.method == "POST" else _auth_error()
    if error:
        return error
    if request.method == "POST":
        try:
            for key, value in (request.get_json(silent=True) or {}).items():
                set_setting(key, value)
        except (TypeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400
    return jsonify(get_settings())


@app.route("/api/run", methods=["POST"])
def run_api():
    error = _state_change_error()
    if error:
        return error
    data = request.form.to_dict() if request.form else (request.get_json(silent=True) or {})
    upload = request.files.get("raw_video") if request.files else None
    if not _rate_limit(f"api:{request.remote_addr or 'unknown'}", 10, 60):
        return jsonify({"error": "Rate limit exceeded"}), 429
    try:
        params, _ = _build_params(data, upload)
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    job_id = f"job_{uuid.uuid4().hex[:12]}"
    db_insert_job(job_id, params["topic"], params)
    try:
        _job_futures[job_id] = _executor.submit(_run_job_worker, job_id, params, str(OUTPUT_FOLDER), str(DB_PATH))
    except Exception:
        logger.exception("Could not queue job %s", job_id)
        db_update_job(job_id, status="error", error="Could not queue job", progress=100, eta_seconds=0)
        return jsonify({"error": "Could not queue job"}), 503
    return jsonify({"job_id": job_id, "status": "queued"})


@app.route("/api/jobs", methods=["GET", "POST"])
def jobs_api():
    if request.method == "GET":
        error = _auth_error()
        if error:
            return error
        return jsonify([_public_job(job) for job in db_list_jobs()])
    return run_api()


@app.get("/api/jobs/<job_id>")
def get_job(job_id: str):
    error = _auth_error()
    if error:
        return error
    job = db_get_job(job_id)
    return jsonify(_public_job(job)) if job else (jsonify({"error": "Job not found"}), 404)


@app.get("/api/jobs/<job_id>/status")
def job_status(job_id: str):
    error = _auth_error()
    if error:
        return error
    job = db_get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({
        "job_id": job_id, "status": job["status"], "step": job["step"], "error": job["error"],
        "pkg_dir": job["pkg_dir"], "progress": job.get("progress", 0) or 0, "eta_seconds": job.get("eta_seconds"),
        "started_at": job.get("started_at"),
    })


@app.post("/api/jobs/<job_id>/cancel")
def cancel_job(job_id: str):
    error = _state_change_error()
    if error:
        return error
    job = db_get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    if job["status"] in {"done", "error", "cancelled"}:
        return jsonify({"job_id": job_id, "status": job["status"]})
    future = _job_futures.get(job_id)
    if future:
        future.cancel()
    db_update_job(job_id, status="cancelled", step="Cancelled", progress=100, eta_seconds=0)
    return jsonify({"job_id": job_id, "status": "cancelled"})


@app.get("/api/jobs/<job_id>/logs")
def job_logs_stream(job_id: str):
    error = _auth_error()
    if error:
        return error
    if not db_get_job(job_id):
        return jsonify({"error": "Job not found"}), 404

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
                return
            time.sleep(0.5)

    return Response(stream(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/queue/status")
def queue_status():
    error = _auth_error()
    if error:
        return error
    jobs = db_list_jobs()
    return jsonify({k: sum(j["status"] == k for j in jobs) for k in ("running", "queued", "done", "error", "cancelled")} | {"max_concurrent_jobs": MAX_CONCURRENT_JOBS})


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


@app.get("/api/packages")
def packages():
    error = _auth_error()
    if error:
        return error
    result = []
    for pkg in sorted((p for p in OUTPUT_FOLDER.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True):
        names = [n for n in ("thumbnail.png", "thumbnail_vertical.png") if (pkg / n).is_file()]
        thumbs = pkg / "thumbnails"
        if thumbs.is_dir():
            names.extend(f"thumbnails/{p.name}" for p in sorted(thumbs.iterdir()) if p.is_file())
        urls = [f"/api/package/{pkg.name}/file/{n}" for n in names]
        script = pkg / "script.txt"
        try:
            preview = script.read_text(encoding="utf-8")[:200] if script.is_file() else ""
        except OSError:
            preview = ""
        result.append({
            "name": pkg.name,
            "created": datetime.fromtimestamp(pkg.stat().st_mtime).isoformat(),
            "thumbnail": urls[0] if urls else None,
            "thumbnails": urls,
            "script_preview": preview,
            "has_video": any((pkg / n).is_file() for n in ("final_short.mp4", "final_with_music.mp4", "final_short_vo.mp4")),
        })
    return jsonify(result)


@app.route("/api/package/<name>/script", methods=["GET", "POST"])
def package_script(name: str):
    error = _state_change_error() if request.method == "POST" else _auth_error()
    if error:
        return error
    pkg = _safe_package_path(name)
    if not pkg:
        return jsonify({"error": "Package not found"}), 404
    path = pkg / "script.txt"
    if request.method == "GET":
        return jsonify({"script": path.read_text(encoding="utf-8") if path.is_file() else ""})
    script = str((request.get_json(silent=True) or {}).get("script", ""))
    if len(script) > 50000:
        return jsonify({"error": "Script is too long"}), 400
    path.write_text(script, encoding="utf-8")
    return jsonify({"ok": True})


@app.get("/api/package/<name>/files")
def package_files(name: str):
    error = _auth_error()
    if error:
        return error
    pkg = _safe_package_path(name)
    if not pkg:
        return jsonify({"error": "Package not found"}), 404
    return jsonify([{"path": p.relative_to(pkg).as_posix(), "size": p.stat().st_size} for p in pkg.rglob("*") if p.is_file()])


@app.get("/api/package/<name>/file/<path:filename>")
def package_file(name: str, filename: str):
    error = _auth_error()
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


@app.route("/api/presets", methods=["GET", "POST"])
def presets():
    error = _state_change_error() if request.method == "POST" else _auth_error()
    if error:
        return error
    if request.method == "GET":
        with _db_connect() as conn:
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
    with _db_connect() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (f"preset:{name}", json.dumps(config)))
        conn.commit()
    return jsonify({"ok": True, "name": name})


@app.post("/api/admin/cleanup")
def cleanup_admin():
    error = _state_change_error()
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
    if not _security_ready():
        raise SystemExit("Set FLASK_SECRET_KEY and authentication settings before starting the dashboard.")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
