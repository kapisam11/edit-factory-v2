"""Compatibility API used by the existing dashboard HTML."""
import json
from pathlib import Path

from flask import jsonify, request


def register_dashboard_compat(app):
    from web_app_v2 import OUTPUT_FOLDER, _resolve_package, create_job, get_db

    @app.route("/api/run", methods=["POST"])
    def compat_run():
        return create_job()

    @app.route("/api/queue/status")
    def compat_queue_status():
        with get_db() as conn:
            queued = conn.execute("SELECT COUNT(*) FROM jobs WHERE status='queued'").fetchone()[0]
            running = conn.execute("SELECT COUNT(*) FROM jobs WHERE status='running'").fetchone()[0]
        return jsonify({"queued": queued, "running": running})

    @app.route("/api/presets", methods=["GET", "POST", "DELETE"])
    def compat_presets():
        if request.method == "POST":
            data = request.get_json(silent=True) or {}
            name = str(data.get("name", "")).strip()
            config = data.get("config") or {}
            if not name or len(name) > 80 or not isinstance(config, dict):
                return jsonify({"error": "Invalid preset"}), 400
            with get_db() as conn:
                conn.execute(
                    "INSERT INTO settings(key,value) VALUES(?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (f"preset:{name}", json.dumps(config)),
                )
            return jsonify({"ok": True}), 201
        with get_db() as conn:
            rows = conn.execute(
                "SELECT key,value FROM settings WHERE key LIKE 'preset:%' ORDER BY key"
            ).fetchall()
        return jsonify({row["key"][7:]: json.loads(row["value"]) for row in rows})

    @app.route("/api/package/<name>/script", methods=["GET", "POST"])
    def compat_script(name):
        package = _resolve_package(name)
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
        package = _resolve_package(name)
        if not package:
            return jsonify({"error": "Package not found"}), 404
        files = []
        for path in package.rglob("*"):
            if path.is_file():
                rel = path.relative_to(package).as_posix()
                files.append({"path": rel, "size": path.stat().st_size})
        return jsonify(files)

    @app.route("/api/package/<name>/file/<path:filename>")
    def compat_file(name, filename):
        from flask import send_from_directory
        package = _resolve_package(name)
        if not package:
            return jsonify({"error": "Package not found"}), 404
        return send_from_directory(package, filename)
