"""Operational maintenance for the single-worker dashboard."""
import os
import threading
import time

from flask import jsonify, request


def _cleanup(web_app_v2, max_age_days: float):
    if max_age_days < 0:
        raise ValueError("max_age_days must be non-negative")
    cutoff = time.time() - max_age_days * 86400
    active = set()
    with web_app_v2.get_db() as conn:
        rows = conn.execute("SELECT pkg_dir FROM jobs WHERE status NOT IN ('done','error','cancelled','interrupted') AND pkg_dir IS NOT NULL").fetchall()
        active = {row["pkg_dir"] for row in rows if row["pkg_dir"]}
    removed = []
    root = web_app_v2.OUTPUT_FOLDER.resolve()
    for child in root.iterdir():
        if not child.is_dir() or str(child) in active or child.stat().st_mtime >= cutoff:
            continue
        import shutil
        shutil.rmtree(child)
        removed.append(child.name)
    return removed


def register_operations(app):
    import web_app_v2

    # Jobs left queued across a restart do not have their in-memory secrets anymore.
    with web_app_v2.get_db() as conn:
        conn.execute("UPDATE jobs SET status='interrupted', step='interrupted', updated_at=CURRENT_TIMESTAMP WHERE status='queued'")

    @app.post("/api/admin/cleanup")
    def cleanup_packages_admin():
        try:
            days = float(request.args.get("max_age_days", os.environ.get("AIVF_RETENTION_DAYS", "7")))
            removed = _cleanup(web_app_v2, days)
            return jsonify({"removed": removed, "count": len(removed)})
        except (ValueError, OSError) as exc:
            return jsonify({"error": str(exc)}), 400

    interval = int(os.environ.get("AIVF_CLEANUP_INTERVAL_SECONDS", "21600"))
    retention = float(os.environ.get("AIVF_RETENTION_DAYS", "7"))
    if interval > 0 and retention >= 0 and os.environ.get("AIVF_DISABLE_AUTO_CLEANUP", "0") != "1":
        def loop():
            while True:
                time.sleep(interval)
                try:
                    _cleanup(web_app_v2, retention)
                except Exception as exc:
                    app.logger.warning("Automatic retention cleanup failed: %s", exc)
        threading.Thread(target=loop, name="aivf-retention", daemon=True).start()
