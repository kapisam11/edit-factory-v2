"""Recommended production Gunicorn configuration for the single-process dashboard."""
workers = 1
bind = "0.0.0.0:5000"
timeout = 0
preload_app = False


def worker_exit(server, worker):
    """Terminate active job processes when the Gunicorn worker exits."""
    try:
        import dashboard_compat
        dashboard_compat.shutdown_active_workers()
    except Exception as exc:
        server.log.error("Failed to terminate active AIVF jobs on worker exit: %s", exc)
