"""End-to-end production orchestration for Edit Factory v2."""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .composer import compose_short_from_video
from .edit_planner import build_timeline, timeline_to_composer_plan, save_timeline
from .learning_recommender import load_experiments, recommend
from .model_adapter import call_model
from .plan import make_idea
from .production_models import ProductionResult
from .scene_intelligence import analyze_video, save_scene_index


def _write_json(path: str, payload: Any) -> str:
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
    text = str(response or "").strip()
    if not text:
        return ""
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            value = payload.get("lines") or payload.get("script")
            if isinstance(value, list):
                return "\n".join(str(v).strip() for v in value if str(v).strip())
            if isinstance(value, str):
                return value.strip()
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    return text


def _generate_script(topic: str, summary: Dict[str, Any], target_seconds: float, model_key: Optional[str]) -> tuple[str, str]:
    if model_key:
        response = call_model(
            "Write a punchy vertical short-video script. Return JSON only as {\"lines\":[\"...\"]}. "
            "Start with a strong hook, use concise visual lines, avoid greetings/filler, and end with a payoff.\n"
            f"Topic: {topic}\nTarget duration: {target_seconds:.1f}s\nSummary: {json.dumps(summary, ensure_ascii=False, default=str)}",
            api_key=model_key,
            timeout=30,
        )
        script = _normalize_model_script(response)
        if len([line for line in script.splitlines() if line.strip()]) >= 2:
            return script, "model"
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
    music_path: Optional[str] = None,
    experiment_history_path: Optional[str] = None,
    enable_object_detection: bool = True,
    enable_diarization: bool = False,
) -> ProductionResult:
    """Run AI planning through CV/speech/music intelligence and final rendering.

    Optional heavy backends are attempted and never prevent the deterministic
    renderer path from completing; their availability is recorded in metadata.
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

    experiments = load_experiments(experiment_history_path) if experiment_history_path else []
    recommendation = recommend(
        {
            "platform": summary.get("platform", "youtube_shorts"),
            "content_type": summary.get("content_type", "short_video"),
            "cuts_per_minute": summary.get("cuts_per_minute", 12),
            "avg_shot_duration": summary.get("avg_shot_duration", 2.5),
            "hook_duration": summary.get("hook_duration", 2.0),
            "music_energy": summary.get("music_energy", 0.5),
        },
        experiments,
        defaults={"caption_style": "karaoke", "voice": "en-US-GuyNeural", "music_style": summary["emotion"]},
    )
    summary["recommended_settings"] = recommendation.settings
    result.warnings.append(f"Learning: {recommendation.reason}") if recommendation.evidence_count == 0 else None
    recommendation_path = os.path.join(package_dir, "recommendation.json")
    _write_json(recommendation_path, recommendation.__dict__)

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

    intelligence: Dict[str, Any] = {
        "object_detection": {"enabled": enable_object_detection, "available": False, "count": 0},
        "diarization": {"enabled": enable_diarization, "available": False, "count": 0},
        "word_timestamps": {"available": False},
        "caption_choreography": {"available": False},
        "music_profile": {"available": False},
    }

    try:
        from .advanced_intelligence import detect_video_objects, save_json
        if enable_object_detection:
            detections = detect_video_objects(source, sample_seconds=2.5)
            intelligence["object_detection"] = {"enabled": True, "available": True, "count": len(detections), "path": save_json(os.path.join(package_dir, "object_detections.json"), detections)}
    except Exception as exc:
        result.warnings.append(f"Object detection unavailable: {exc}")

    words = []
    try:
        from .advanced_intelligence import generate_word_timestamps, build_choreographed_captions, write_ass_captions, save_json
        audio_path = os.path.join(package_dir, "voiceover.mp3")
        word_path = os.path.join(package_dir, "word_timestamps.json")
        words = generate_word_timestamps(script, audio_path, voice=str(recommendation.settings.get("voice", "en-US-GuyNeural")), timestamps_path=word_path)
        intelligence["word_timestamps"] = {"available": True, "count": len(words), "path": word_path}
        captions = build_choreographed_captions(words)
        choreography_path = os.path.join(package_dir, "caption_choreography.json")
        ass_path = os.path.join(package_dir, "captions.ass")
        save_json(choreography_path, [cue.__dict__ for cue in captions])
        write_ass_captions(captions, ass_path)
        intelligence["caption_choreography"] = {"available": True, "count": len(captions), "path": ass_path, "json_path": choreography_path}

        if enable_diarization:
            from .advanced_intelligence import diarize_audio, assign_speakers
            diarization = diarize_audio(audio_path)
            words = assign_speakers(words, diarization)
            diar_path = os.path.join(package_dir, "diarization.json")
            save_json(diar_path, [item.__dict__ for item in diarization])
            intelligence["diarization"] = {"enabled": True, "available": True, "count": len(diarization), "path": diar_path}
    except Exception as exc:
        result.warnings.append(f"Speech intelligence unavailable: {exc}")

    music_profile = None
    if music_path and os.path.exists(music_path):
        try:
            from .advanced_intelligence import analyze_music_profile, music_aware_cut_plan, save_json
            music_profile = analyze_music_profile(music_path)
            profile_path = os.path.join(package_dir, "music_profile.json")
            save_json(profile_path, music_profile)
            intelligence["music_profile"] = {"available": True, "path": profile_path, "bpm": music_profile.get("bpm"), "beats": len(music_profile.get("beats", []))}
        except Exception as exc:
            result.warnings.append(f"Music intelligence unavailable: {exc}")

    try:
        timeline = build_timeline(script, scenes, total_seconds=float(target_seconds), aspect_ratio="9:16", source_video=source)
    except Exception as exc:
        result.errors.append(f"Timeline planning failed: {exc}")
        return result

    # Replace target timing with music-aware boundaries when a real music profile exists.
    if music_profile and music_profile.get("beats"):
        try:
            from .advanced_intelligence import music_aware_cut_plan
            cut_plan = music_aware_cut_plan([s.duration for s in timeline.segments], music_profile)
            for segment, (start, end) in zip(timeline.segments, cut_plan):
                segment.start = start
                segment.end = end
            timeline.duration = max((s.end for s in timeline.segments), default=timeline.duration)
            timeline.validate()
        except Exception as exc:
            result.warnings.append(f"Music-aware timing could not be applied: {exc}")

    result.timeline_path = save_timeline(timeline, os.path.join(package_dir, "timeline.json"))
    plan_payload: Dict[str, Any] = dict(summary)
    plan_payload.update({
        "topic": topic,
        "script": script,
        "script_source": script_source,
        "edit_plan": timeline_to_composer_plan(timeline),
        "timeline_path": result.timeline_path,
        "scene_index_path": result.scenes_path,
        "recommendation": recommendation.settings,
        "intelligence": intelligence,
    })
    result.plan_path = _write_json(os.path.join(package_dir, "plan.json"), plan_payload)

    try:
        rendered = compose_short_from_video(source, package_dir, out_file=os.path.join(package_dir, "final.mp4"), review=not skip_qc, auto_fix=True, model_key=model_key, skip_qc=skip_qc)
        final_path = os.path.join(package_dir, "final.mp4")
        if rendered and os.path.exists(rendered) and os.path.abspath(rendered) != os.path.abspath(final_path):
            shutil.copy2(rendered, final_path)
            rendered = final_path
        result.final_video = rendered if rendered and os.path.exists(rendered) else None
        if result.final_video is None:
            result.errors.append("Renderer completed without producing final.mp4")
    except Exception as exc:
        result.errors.append(f"Rendering failed: {exc}")

    metadata = {
        "version": 3,
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
        "recommendation": recommendation.__dict__,
        "intelligence": intelligence,
        "rendered": result.final_video is not None,
        "warnings": result.warnings,
        "errors": result.errors,
    }
    result.metadata_path = _write_json(os.path.join(package_dir, "metadata.json"), metadata)
    result.metrics_path = _write_json(os.path.join(package_dir, "metrics.json"), {
        "scene_count": len(scenes),
        "segment_count": len(timeline.segments),
        "cuts_per_minute": round(len(timeline.segments) / max(0.01, timeline.duration / 60.0), 3),
        "average_scene_importance": round(sum(s.importance_score for s in scenes) / max(1, len(scenes)), 4),
        "average_selected_score": round(sum(s.score for s in timeline.segments) / max(1, len(timeline.segments)), 4),
        "object_detections": intelligence["object_detection"].get("count", 0),
        "word_timestamps": intelligence["word_timestamps"].get("count", 0),
        "diarized_segments": intelligence["diarization"].get("count", 0),
        "rendered": result.final_video is not None,
    })
    return result


__all__ = ["run_production_pipeline"]
