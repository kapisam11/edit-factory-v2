"""Shared validation helpers used by CLI, web, and pipeline entry points."""
from __future__ import annotations

import math
from typing import Iterable

VALID_WORKFLOWS = ("default", "fast", "package_only")
PIPELINE_STAGES = (
    "research",
    "plan",
    "script",
    "thumbnail",
    "auto_edit",
    "voiceover",
    "music",
    "quality_control",
    "metadata",
    "metrics",
)
MIN_TARGET_SECONDS = 15.0
MAX_TARGET_SECONDS = 120.0


def validate_target_seconds(value: float, field_name: str = "target_seconds") -> float:
    """Validate and return a finite target duration in the supported range."""
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a number") from exc
    if not math.isfinite(result) or not MIN_TARGET_SECONDS <= result <= MAX_TARGET_SECONDS:
        raise ValueError(
            f"{field_name} must be between {MIN_TARGET_SECONDS:g} and {MAX_TARGET_SECONDS:g} seconds"
        )
    return result


def normalize_workflow(value: str, allowed: Iterable[str] = VALID_WORKFLOWS) -> str:
    """Normalize compatibility aliases and validate the workflow name."""
    workflow = str(value).strip().lower()
    workflow = {"director": "default", "legacy": "default"}.get(workflow, workflow)
    allowed_set = {str(name) for name in allowed}
    if workflow not in allowed_set:
        raise ValueError(f"Unsupported workflow: {workflow}")
    return workflow


def stage_skips_for_pipeline(config: object, pipeline_name: str) -> list[str]:
    """Return stage names omitted by the configured workflow.

    Keeping this mapping here prevents the CLI and dashboard from silently
    implementing different workflow definitions.
    """
    normalized = normalize_workflow(pipeline_name)
    selected = config.get_pipeline(normalized)
    configured = set(selected.stages)
    if "qc" in configured:
        configured.add("quality_control")
    return [name for name in PIPELINE_STAGES if name not in configured]
