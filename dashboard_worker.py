"""Spawn-safe worker entrypoint with isolated process-group semantics."""
import os


def run_job(job_id: str, params: dict, secrets: dict, output_root: str, db_path: str) -> None:
    # Give FFmpeg and other descendants a private process group/session so cancellation
    # can terminate the entire job tree without touching Gunicorn.
    if os.name != "nt":
        try:
            os.setsid()
        except OSError:
            pass
    import web_app_v2
    web_app_v2._run_job_worker(job_id, params, secrets, output_root, db_path)
