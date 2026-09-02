"""End-to-end production orchestration for Edit Factory v2.

This module connects research/planning/model scripting to the scene index,
script-to-timeline planner, and renderer. The legacy composer remains the
rendering backend so the upgrade stays incremental and reversible.
"""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .composer import compose_short_from_video
from .edit_planner import build_timeline, timeline_to_composer_plan, save_timeline
from .model_adapter import call_model
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


def _normalize_model_script(response: str) -> str:
    """Extract a newline-separated script from common model response shapes."""
    text = str(response or "").strip()
    if not text:
        return ""

    cleaned = text
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    try:
        payload = json.loads(cleaned)
        if isinstance(payload, dict):
            lines = payload.get("lines") or payload.get("script")
            if isinstance(lines, list):
                return "\n".join(str(line).strip() for line in lines if str(line).strip()).strip()
            if isinstance(lines, str):
                return lines.strip()
    except (TypeError, ValueError, json.JSONDecodeError):
        pass

    return cleaned


def _generate_script(topic: str, summary: Dict[str, Any], target_seconds: float, model_key: Optional[str]) -> tuple[str, str]:
    """Generate a model-backed script when configured, otherwise use the local planner."""
    if model_key:
        prompt = (
            "Write a short-form vertical video script. Return JSON only as "
            '{"lines":["..."]}. Keep each line concise and visual, start with a strong hook, '
            "and avoid greetings/filler.\n"
            f"Topic: {topic}\n"
            f"Target duration: {target_seconds:.1f} seconds\n"
            f"Research summary: {json.dumps(summary, ensure_ascii=False, default=str)}"
        )
        response = call_model(prompt, api_key=model_key)
        script = _normalize_model_script(response)
        lines = [line.strip() for line in script.splitlines() if line.strip()]
        if len(lines) >= 2:
            return "\n".join(lines), "model"

    idea = make_idea(summary)
    return str(idea.get("script") or "").strip(), "template"


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
    """Run the production path from script generation through final rendering.

    The model is optional: with ``model_key`` the pipeline attempts model-backed
    script generation; without it, the deterministic local planner remains the fallback.
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

    script, script_source = _generate_script(topic, summary, target_seconds, model_key)
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

    composer_plan = timeline_to_composer_plan(timeline)
    plan_payload: Dict[str, Any] = dict(summary)
    plan_payload.update({
        "topic": topic,
        "script": script,
        "script_source": script_source,
        "edit_plan": composer_plan,
        "timeline_path": result.timeline_path,
        "scene_index_path": result.scenes_path,
    })
    result.plan_path = _write_json(os.path.join(package_dir, "plan.json"), plan_payload)

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
        final_path = os.path.join(package_dir, "final.mp4")
        if rendered and os.path.exists(rendered) and os.path.abspath(rendered) != os.path.abspath(final_path):
            shutil.copy2(rendered, final_path)
            rendered = final_path
        result.final_video = rendered if rendered and os.path.exists(rendered) else None
        if result.final_video is None:
            result.errors.append("Renderer completed without producing final.mp4")
    except Exception as exc:
        result.errors.append(f"Rendering failed: {exc}")
        result.final_video = None

    qc_path = os.path.join(package_dir, "qc_report.json")
    result.qc_report_path = qc_path if os.path.exists(qc_path) else None

    metadata = {
        "version": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "topic": topic,
        "input_video": source,
        "target_seconds": target_seconds,
        "actual_timeline_seconds": timeline.duration,
        "scene_count": len(scenes),
        "segment_count": len(timeline.segments),
        "ocr_enabled": enable_ocr,
        "script_source": script_source,
        "model_backed": script_source == "model",
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
