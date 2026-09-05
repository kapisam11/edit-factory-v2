"""Compatibility API used by the existing dashboard HTML.

Also provides a small in-memory dashboard secret store so the existing settings UI can
configure provider credentials without writing them to SQLite.
"""
import json

from flask import jsonify, request

_DASHBOARD_SECRETS = {"groq_key": "", "model_key": "", "elevenlabs_key": ""}
SECRET_KEYS = set(_DASHBOARD_SECRETS)


def register_dashboard_compat(app):
    import web_app_v2

    original_create_job = web_app_v2.create_job

    @app.route("/api/run", methods=["POST"])
    def compat_run():
        return app.view_functions["create_job"]()

    @app.route("/api/queue/status")
    def compat_queue_status():
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
                    "INSERT INTO settings(key,value) VALUES(?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
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
        files = []
        for path in package.rglob("*"):
            if path.is_file():
                files.append({"path": path.relative_to(package).as_posix(), "size": path.stat().st_size})
        return jsonify(files)

    @app.route("/api/package/<name>/file/<path:filename>")
    def compat_file(name, filename):
        from flask import send_from_directory
        package = web_app_v2._resolve_package(name)
        if not package:
            return jsonify({"error": "Package not found"}), 404
        return send_from_directory(package, filename)

    original_settings = web_app_v2.settings

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
        # The existing creator reads defaults from web_app_v2.get_settings(). Temporarily
        # overlay runtime-only secrets without ever writing them to SQLite.
        original_get_settings = web_app_v2.get_settings

        def settings_with_runtime_secrets():
            values = dict(original_get_settings())
            values.update(_DASHBOARD_SECRETS)
            return values

        web_app_v2.get_settings = settings_with_runtime_secrets
        try:
            return original_create_job()
        finally:
            web_app_v2.get_settings = original_get_settings

    app.view_functions["settings"] = hardened_settings
    app.view_functions["create_job"] = hardened_create_job
