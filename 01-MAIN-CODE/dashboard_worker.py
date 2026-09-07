"""Spawn-safe worker launcher."""
import os
from pathlib import Path
import sys

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WEB_DIR = _REPO_ROOT / "02-WEB-FILES"
if str(_WEB_DIR) not in sys.path:
    sys.path.insert(0, str(_WEB_DIR))


def _skip_stages_for_workflow(workflow: str) -> list[str]:
    """Translate the dashboard workflow name into the canonical pipeline stages."""
    from ai_video_factory.validation import normalize_workflow

    selected = normalize_workflow(workflow)
    configured = {
        "default": {
            "research", "plan", "script", "thumbnail", "auto_edit",
            "voiceover", "music", "quality_control", "metadata", "metrics",
        },
        "fast": {"plan", "script", "auto_edit", "metadata"},
        "package_only": {"research", "plan", "script", "thumbnail", "metadata"},
    }[selected]
    all_names = [
        "research", "plan", "script", "thumbnail", "auto_edit",
        "voiceover", "music", "quality_control", "metadata", "metrics",
    ]
    return [name for name in all_names if name not in configured]


def run_job(job_id: str, params: dict, secrets: dict, output_root: str, db_path: str) -> None:
    os.environ["AIVF_WORKER_PROCESS"] = "1"
    if os.name != "nt":
        try:
            os.setsid()
        except OSError:
            pass
    from app import web_app_v2
    from ai_video_factory.validation import validate_target_seconds

    # Validate the web/API values again inside the worker so queued jobs cannot
    # bypass the canonical pipeline constraints between submission and execution.
    params = dict(params)
    params["target_seconds"] = validate_target_seconds(params.get("target_seconds", 45.0))
    params["workflow"] = str(params.get("workflow", "default"))
    skip_stages = _skip_stages_for_workflow(params["workflow"])

    # Keep the worker launcher compatible with the canonical implementation while
    # making the selected dashboard workflow explicit.
    original_builder = web_app_v2._run_job_worker_impl
    if skip_stages:
        from ai_video_factory.pipeline import build_director_pipeline

        original_builder = web_app_v2._run_job_worker_impl

        # The canonical worker implementation currently builds the full director
        # pipeline. Temporarily expose the requested stage selection through a
        # process-local wrapper rather than changing the public worker contract.
        from unittest.mock import patch
        with patch("ai_video_factory.pipeline.build_director_pipeline", side_effect=lambda: build_director_pipeline(skip_stages=skip_stages)):
            original_builder(job_id, params, secrets, output_root, db_path)
        return

    original_builder(job_id, params, secrets, output_root, db_path)
