"""Spawn-safe worker launcher."""
import os
from pathlib import Path
import sys

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WEB_DIR = _REPO_ROOT / "02-WEB-FILES"
if str(_WEB_DIR) not in sys.path:
    sys.path.insert(0, str(_WEB_DIR))


def run_job(job_id: str, params: dict, secrets: dict, output_root: str, db_path: str) -> None:
    os.environ["AIVF_WORKER_PROCESS"] = "1"
    if os.name != "nt":
        try:
            os.setsid()
        except OSError:
            pass
    from app import web_app_v2
    web_app_v2._run_job_worker_impl(job_id, params, secrets, output_root, db_path)
