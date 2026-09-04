"""Isolated job worker for the dashboard.

This module intentionally contains no Flask app or ProcessPoolExecutor creation.
It is safe to import under Windows ``spawn`` semantics and can be launched as
an independent child process that the parent can terminate for real cancellation.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import traceback
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger("aivf.worker")
SECRET_PARAM_KEYS = {"groq_key", "model_key", "elevenlabs_key"}


def _db_update(db_path: str, job_id: str, **kwargs: Any) -> None:
    if not kwargs:
        return
    with sqlite3.connect(db_path, timeout=30) as conn:
        conn.execute("PRAGMA busy_timeout=5000")
        fields = []
        values = []
        for key, value in kwargs.items():
            fields.append(f"{key} = ?")
            values.append(value)
        values.append(job_id)
        conn.execute(
            f"UPDATE jobs SET {', '.join(fields)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            values,
        )
        conn.commit()


def _log(db_path: str, job_id: str, level: str, message: str) -> None:
    with sqlite3.connect(db_path, timeout=30) as conn:
        conn.execute("PRAGMA busy_timeout=5000")
        row = conn.execute("SELECT logs FROM jobs WHERE id = ?", (job_id,)).fetchone()
        logs = json.loads(row[0]) if row and row[0] else []
        logs.append(
            {
                "time": datetime.now().strftime("%H:%M:%S"),
                "level": level,
                "msg": message,
            }
        )
        conn.execute(
            "UPDATE jobs SET logs = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(logs[-500:]), job_id),
        )
        conn.commit()


def _erase_persisted_secrets(db_path: str, job_id: str) -> None:
    """Remove legacy secret fields from persisted job parameters."""
    with sqlite3.connect(db_path, timeout=30) as conn:
        conn.execute("PRAGMA busy_timeout=5000")
        row = conn.execute("SELECT params FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row or not row[0]:
            return
        try:
            params = json.loads(row[0])
        except (TypeError, ValueError, json.JSONDecodeError):
            return
        if not isinstance(params, dict):
            return
        changed = False
        for key in SECRET_PARAM_KEYS:
            if key in params:
                params.pop(key, None)
                changed = True
        if changed:
            conn.execute(
                "UPDATE jobs SET params = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (json.dumps(params), job_id),
            )
            conn.commit()


def run_job_worker(
    job_id: str,
    params: Dict[str, Any],
    output_root: str,
    db_path: str,
    runtime_secrets: Optional[Dict[str, str]] = None,
) -> int:
    """Run one pipeline job and persist non-secret state to SQLite.

    API keys are accepted only in process memory. ``runtime_secrets`` is the
    preferred source; environment variables are used as deployment fallbacks.
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    runtime_secrets = {
        key: str((runtime_secrets or {}).get(key, "") or "")
        for key in SECRET_PARAM_KEYS
    }
    _erase_persisted_secrets(db_path, job_id)
    try:
        from ai_video_factory.config import AIVFConfig
        from ai_video_factory.pipeline import PipelineContext, build_director_pipeline
        from ai_video_factory.validation import normalize_workflow, stage_skips_for_pipeline

        _db_update(
            db_path,
            job_id,
            status="running",
            step="Initializing",
            worker_pid=os.getpid(),
        )
        _log(db_path, job_id, "INFO", f"Worker started (pid={os.getpid()})")

        topic = str(params["topic"]).strip()
        config = AIVFConfig.load()
        workflow = normalize_workflow(str(params.get("workflow", "default")))
        skip_stages = stage_skips_for_pipeline(config, workflow)
        skip_stages.extend(
            str(item).strip() for item in params.get("skip_stages", []) if str(item).strip()
        )

        safe_topic = "_".join(topic.split())
        safe_topic = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in safe_topic)
        safe_topic = safe_topic[:50].strip("_") or "job"
        pkg_name = f"{safe_topic}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        pkg_dir = os.path.join(output_root, pkg_name)
        os.makedirs(pkg_dir, exist_ok=True)
        _db_update(db_path, job_id, pkg_dir=pkg_dir, step="Pipeline")

        def progress(completed: int, total: int, stage: str, elapsed: float, eta: float) -> None:
            percent = int(round(completed / max(total, 1) * 100))
            _db_update(db_path, job_id, step=stage, progress=percent)
            _log(db_path, job_id, "INFO", f"Progress {percent}% — {stage} — ETA {eta:.1f}s")

        ctx = PipelineContext(
            topic=topic,
            package_dir=pkg_dir,
            raw_video=params.get("raw_video"),
            target_seconds=params.get("target_seconds", 45.0),
            skip_qc=bool(params.get("skip_qc", False)),
            use_groq=bool(params.get("use_groq", False)),
            model_key=runtime_secrets.get("model_key") or os.environ.get("OPENAI_API_KEY"),
            groq_key=runtime_secrets.get("groq_key") or os.environ.get("GROQ_API_KEY"),
            thumbnail_variant=int(params.get("thumbnail_variant", 1)),
        )

        pipeline = build_director_pipeline(
            skip_stages=sorted(set(skip_stages)),
            verbose=False,
            progress_callback=progress,
        )
        ctx = pipeline.run(ctx)

        if ctx.errors:
            error_text = "; ".join(ctx.errors)
            _log(db_path, job_id, "ERROR", error_text)
            _db_update(db_path, job_id, status="error", error=error_text, progress=100)
            return 1

        _log(db_path, job_id, "INFO", "Job complete")
        _db_update(db_path, job_id, status="done", step="complete", progress=100, error=None)
        return 0
    except Exception as exc:
        error_text = f"{exc}\n{traceback.format_exc()}"
        try:
            _log(db_path, job_id, "ERROR", error_text)
            _db_update(db_path, job_id, status="error", error=str(exc))
        except sqlite3.Error:
            logger.exception("Could not persist worker failure for %s", job_id)
        return 1


if __name__ == "__main__":
    raise SystemExit("worker.py is a library entry point; use run_job_worker()")
