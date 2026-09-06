"""Compatibility entry point. The worker implementation lives in app.dashboard_worker."""
from app.dashboard_worker import run_job

__all__ = ["run_job"]
