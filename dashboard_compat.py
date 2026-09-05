"""Compatibility API and lifecycle hardening for the dashboard UI."""
import json
import os
import signal
import subprocess

from flask import jsonify, request

_DASHBOARD_SECRETS = {"groq_key": "", "model_key": "", "elevenlabs_key": ""}
SECRET_KEYS = set(_DASHBOARD_SECRETS)


def _terminate_process_tree(process):
    if not process.is_alive():
        process.join(timeout=1)
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    process.join(timeout=10)


def register_dashboard_compat(app):
    import web_app_v2

    # Prevent a worker that races with cancellation from moving a cancelled job back to done/error.
    with web_app_v2.get_db() as conn:
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS prevent_post_cancel_finalization
            BEFORE UPDATE OF status ON jobs
            WHEN OLD.status IN ('cancelling', 'cancelled')
                 AND NEW.status IN ('running', 'done', 'error', 'queued')
            BEGIN
                SELECT RAISE(ABORT, 'job cancellation already requested');
            END
        """)

    original_create_job = web_app_v2.create_job

    @app.route("/api/run", methods=["POST"])
    def compat_run():
        return app.view_functions["create_job"]()

    @app.route("/api/queue/status")
    def compat_queue_status():
        _reap_and_dispatch(web_app_v2)
        with web_app_v2.get_db() as conn:
            queued = conn.execute("SELECT COUNT(*) FROM jobs WHERE status='queued'").fetchone()[0]
            running = conn.execute("SELECT COUNT(*) FROM jobs WHERE status='running'").fetchone()[0]
        return jsonify({"queued": queued, "running": running,
                        "max_concurrent_jobs": int(web_app_v2.get_settings()["max_concurrent_jobs"])})

    @app.route("/api/presets", methods=["GET", "POST", "DELETE"])
    def compat_presets():
        if request.method == "POST":
            data = request.get_json(silent=True) or {}
            name = str(data.get("name", "")).strip()
            config = data.get("config") or {}
            if not name or len(name) > 80 or not isinstance(config, dict):
                return jsonify({"error": "Invalid preset"}), 400
            with web_app_v2.get_db() as conn:
                conn.execute(
                    "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (f"preset:{name}", json.dumps(config)),
                )
            return jsonify({"ok": True}), 201
        with web_app_v2.get_db() as conn:
            rows = conn.execute("SELECT key,value FROM settings WHERE key LIKE 'preset:%' ORDER BY key").fetchall()
        return jsonify({row["key"][7:]: json.loads(row["value"]) for row in rows})

    @app.route("/api/package/<name>/script", methods=["GET", "POST"])
    def compat_script(name):
        package = web_app_v2._resolve_package(name)
        if not package:
            return jsonify({"error": "Package not found"}), 404
        path = package / "script.txt"
        if request.method == "GET":
            return jsonify({"script": path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""})
        data = request.get_json(silent=True) or {}
        script = data.get("script")
        if not isinstance(script, str) or len(script) > 200000:
            return jsonify({"error": "Invalid script"}), 400
        path.write_text(script, encoding="utf-8")
        return jsonify({"ok": True})

    @app.route("/api/package/<name>/files")
    def compat_files(name):
        package = web_app_v2._resolve_package(name)
        if not package:
            return jsonify({"error": "Package not found"}), 404
        return jsonify([
            {"path": path.relative_to(package).as_posix(), "size": path.stat().st_size}
            for path in package.rglob("*") if path.is_file()
        ])

    @app.route("/api/package/<name>/file/<path:filename>")
    def compat_file(name, filename):
        from flask import send_from_directory
        package = web_app_v2._resolve_package(name)
        if not package:
            return jsonify({"error": "Package not found"}), 404
        return send_from_directory(package, filename)

    def hardened_settings():
        if request.method == "POST":
            data = request.get_json(silent=True) or {}
            for key in SECRET_KEYS:
                if key in data:
                    _DASHBOARD_SECRETS[key] = str(data[key] or "").strip()
            for key, value in data.items():
                if key not in SECRET_KEYS:
                    web_app_v2.set_setting(key, value)
        result = dict(web_app_v2.get_settings())
        result.update({f"{key}_configured": bool(value) for key, value in _DASHBOARD_SECRETS.items()})
        for key in SECRET_KEYS:
            result[key] = ""
        return jsonify(result)

    def hardened_create_job():
        original_get_settings = web_app_v2.get_settings

        def settings_with_runtime_secrets():
            values = dict(original_get_settings())
            values.update(_DASHBOARD_SECRETS)
            return values

        web_app_v2.get_settings = settings_with_runtime_secrets
        try:
            response = original_create_job()
            if response.status_code < 300:
                payload = response.get_json(silent=True) or {}
                job_id = payload.get("job_id")
                if job_id:
                    web_app_v2._runtime_secrets.setdefault(job_id, {}).update(
                        {k: v for k, v in _DASHBOARD_SECRETS.items() if v}
                    )
            return response
        finally:
            web_app_v2.get_settings = original_get_settings

    def hardened_cancel_job(job_id):
        job = web_app_v2.db_get_job(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404
        if job["status"] in web_app_v2.TERMINAL_STATUSES:
            return jsonify({"job_id": job_id, "status": job["status"]}), 409
        web_app_v2.db_update_job(job_id, status="cancelling", step="cancelling")
        process = web_app_v2._active_processes.get(job_id)
        if process:
            _terminate_process_tree(process)
            if process.is_alive():
                return jsonify({"error": "Worker termination timed out"}), 503
        web_app_v2._active_processes.pop(job_id, None)
        web_app_v2._runtime_secrets.pop(job_id, None)
        web_app_v2.db_update_job(job_id, status="cancelled", step="cancelled")
        web_app_v2.db_append_log(job_id, "INFO", "Job cancelled")
        return jsonify({"job_id": job_id, "status": "cancelled"})

    app.view_functions["settings"] = hardened_settings
    app.view_functions["create_job"] = hardened_create_job
    app.view_functions["cancel_job"] = hardened_cancel_job

    @app.before_request
    def lifecycle_maintenance():
        _reap_and_dispatch(web_app_v2)


def _reap_and_dispatch(web_app_v2):
    # Reconcile processes that exited without a terminal state.
    for job_id, process in list(web_app_v2._active_processes.items()):
        if process.is_alive():
            continue
        process.join(timeout=0)
        job = web_app_v2.db_get_job(job_id)
        web_app_v2._active_processes.pop(job_id, None)
        web_app_v2._runtime_secrets.pop(job_id, None)
        if job and job["status"] in {"queued", "running", "cancelling"}:
            web_app_v2.db_update_job(job_id, status="interrupted", step="interrupted",
                                     error=f"Worker exited with code {process.exitcode}")
            web_app_v2.db_append_log(job_id, "ERROR", "Worker exited unexpectedly")

    capacity = int(web_app_v2.get_settings()["max_concurrent_jobs"])
    while sum(1 for p in web_app_v2._active_processes.values() if p.is_alive()) < capacity:
        with web_app_v2.get_db() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created_at ASC LIMIT 1").fetchone()
        if not row:
            return
        job_id = row["id"]
        params = json.loads(row["params"] or "{}")
        secrets = dict(web_app_v2._runtime_secrets.get(job_id, {}))
        if not web_app_v2._start_job(job_id, params, secrets):
            return
