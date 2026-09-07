"""Production Gunicorn settings for the Edit Factory dashboard."""
chdir = "01-MAIN-CODE"
workers = 1
bind = "0.0.0.0:5000"
timeout = 0
preload_app = False


def worker_exit(server, worker):
    """Terminate active job processes when the Gunicorn worker exits."""
    try:
        from dashboard_shutdown import shutdown_active_workers
        shutdown_active_workers()
    except Exception as exc:
        server.log.error("Failed to terminate active AIVF jobs on worker exit: %s", exc)
