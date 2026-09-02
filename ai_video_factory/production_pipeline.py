"""End-to-end production orchestration for Edit Factory v2.

This module connects the existing research/planning/composer stack to the new
scene index and script-to-timeline planner. It intentionally uses the current
renderer instead of replacing it, making the upgrade incremental and reversible.
"""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .composer import compose_short_from_video
from .edit_planner import build_timeline, timeline_to_composer_plan, save_timeline
from .plan import make_idea
from .production_models import ProductionResult
from .scene_intelligence import analyze_video, save_scene_index


def _write_json(path: str, payload: Dict[str, Any]) -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=str)
    return path


def _write_text(path: str, text: str) -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


def run_production_pipeline(
    input_video: str,
    topic: str,
    package_dir: str,
    *,
    target_seconds: float = 45.0,
    research_summary: Optional[Dict[str, Any]] = None,
    enable_ocr: bool = False,
    model_key: Optional[str] = None,
    skip_qc: bool = False,
) -> ProductionResult:
    """Run research-free deterministic planning plus footage-aware rendering.

    `research_summary` can be the output of the existing research system. When
    omitted, a compact local summary is used so the production path remains runnable.
    """
    os.makedirs(package_dir, exist_ok=True)
    result = ProductionResult(package_dir=package_dir)
    source = os.path.abspath(input_video)

    if not os.path.exists(source):
        result.errors.append(f"Input video does not exist: {source}")
        return result

    summary: Dict[str, Any] = dict(research_summary or {})
    summary.setdefault("topic", topic)
    summary.setdefault("target_total_seconds", target_seconds)
    summary.setdefault("emotion", "dramatic")
    summary.setdefault("strongest_angle", topic)
    summary.setdefault("main_conflict", f"Something important happened involving {topic}.")
    summary.setdefault("why_care", "The outcome changed what happened next.")

    idea = make_idea(summary)
    script = str(idea.get("script") or "").strip()
    if not script:
        result.errors.append("Planner returned an empty script")
        return result

    result.script_path = _write_text(os.path.join(package_dir, "script.txt"), script)

    try:
        scenes = analyze_video(source, sample_seconds=2.5, enable_ocr=enable_ocr)
    except Exception as exc:
        result.errors.append(f"Scene analysis failed: {exc}")
        return result

    result.scenes_path = save_scene_index(scenes, os.path.join(package_dir, "scenes.json"), source)

    try:
        timeline = build_timeline(
            script,
            scenes,
            total_seconds=float(target_seconds),
            aspect_ratio="9:16",
            source_video=source,
        )
    except Exception as exc:
        result.errors.append(f"Timeline planning failed: {exc}")
        return result

    result.timeline_path = save_timeline(timeline, os.path.join(package_dir, "timeline.json"))

    # Backward-compatible plan.json: the current composer reads edit_plan from this file.
    composer_plan = timeline_to_composer_plan(timeline)
    plan_payload: Dict[str, Any] = dict(idea)
    plan_payload["topic"] = topic
    plan_payload["script"] = script
    plan_payload["edit_plan"] = composer_plan
    plan_payload["timeline_path"] = result.timeline_path
    plan_payload["scene_index_path"] = result.scenes_path
    result.plan_path = _write_json(os.path.join(package_dir, "plan.json"), plan_payload)

    # Give the renderer the timeline's source ranges through timeline.json. The composer
    # will use them when present; this is the key connection between planning and rendering.
    try:
        rendered = compose_short_from_video(
            source,
            package_dir,
            out_file=os.path.join(package_dir, "final.mp4"),
            review=not skip_qc,
            auto_fix=True,
            model_key=model_key,
            skip_qc=skip_qc,
        )
        if rendered and os.path.exists(rendered) and os.path.abspath(rendered) != os.path.abspath(os.path.join(package_dir, "final.mp4")):
            shutil.copy2(rendered, os.path.join(package_dir, "final.mp4"))
            rendered = os.path.join(package_dir, "final.mp4")
        result.final_video = rendered if rendered and os.path.exists(rendered) else None
    except Exception as exc:
        result.errors.append(f"Rendering failed: {exc}")
        result.final_video = None

    result.qc_report_path = os.path.join(package_dir, "qc_report.json") if os.path.exists(os.path.join(package_dir, "qc_report.json")) else None

    metadata = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "topic": topic,
        "input_video": source,
        "target_seconds": target_seconds,
        "actual_timeline_seconds": timeline.duration,
        "scene_count": len(scenes),
        "segment_count": len(timeline.segments),
        "ocr_enabled": enable_ocr,
        "rendered": result.final_video is not None,
        "warnings": result.warnings,
        "errors": result.errors,
    }
    result.metadata_path = _write_json(os.path.join(package_dir, "metadata.json"), metadata)

    metrics = {
        "scene_count": len(scenes),
        "segment_count": len(timeline.segments),
        "cuts_per_minute": round(len(timeline.segments) / max(0.01, timeline.duration / 60.0), 3),
        "average_scene_importance": round(sum(s.importance_score for s in scenes) / max(1, len(scenes)), 4),
        "average_selected_score": round(sum(s.score for s in timeline.segments) / max(1, len(timeline.segments)), 4),
        "rendered": result.final_video is not None,
    }
    result.metrics_path = _write_json(os.path.join(package_dir, "metrics.json"), metrics)
    return result


__all__ = ["run_production_pipeline"]
