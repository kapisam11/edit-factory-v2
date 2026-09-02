"""Higher-level producer utilities for the AI Video Factory."""
import json
import logging
import os
import re
from datetime import datetime
from typing import Optional

from .research import research_topic
from .plan import make_idea, make_idea_with_knowledge
from .knowledge import KnowledgeBase
from .thumbnail import make_thumbnail, make_thumbnail_variants
from .output_packager import write_package
from .visuals_fetcher import download_visuals

logger = logging.getLogger(__name__)


def produce_package(
    topic: str,
    out_root: str = "output",
    use_groq: bool = False,
    groq_api_key: Optional[str] = None,
    thumbnail_subject: Optional[str] = None,
    enable_full_downloads: bool = False,
    allow_install_yt_dlp: bool = False,
    model_api_key: Optional[str] = None,
    use_spacy_persona: Optional[bool] = None,
    prune_min_match: Optional[float] = None,
    prune_min_motion: Optional[float] = None,
    prune_require_faces: Optional[list] = None,
    prune_min_model_confidence: Optional[float] = None,
    target_total_seconds: Optional[float] = None,
    config_path: Optional[str] = None,
) -> str:
    """Produce an upload-ready package for `topic`.

    Explicit function arguments always win over configuration-file values.
    Optional enrichments are best-effort, but every degraded feature is
    recorded in ``production_warnings.json`` so success is observable.
    """
    warnings = []
    cfg = {}
    try:
        if config_path and os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as cf:
                cfg = json.load(cf)
        else:
            for candidate in ("aivf_config.json", ".aivf.json"):
                if os.path.exists(candidate):
                    with open(candidate, "r", encoding="utf-8") as cf:
                        cfg = json.load(cf)
                    break
    except Exception as exc:
        logger.warning("Config load failed: %s", exc)
        warnings.append(f"config load failed: {exc}")

    # Config is a default layer; explicit args are never overwritten.
    prune_min_match = float(cfg.get("prune_min_match", 0.25)) if prune_min_match is None else float(prune_min_match)
    prune_min_motion = float(cfg.get("prune_min_motion", 0.07)) if prune_min_motion is None else float(prune_min_motion)
    prune_min_model_confidence = float(cfg.get("prune_min_model_confidence", 0.0)) if prune_min_model_confidence is None else float(prune_min_model_confidence)
    use_spacy_persona = bool(cfg.get("use_spacy_persona", False)) if use_spacy_persona is None else bool(use_spacy_persona)
    target_total_seconds = float(cfg.get("target_total_seconds", 45.0)) if target_total_seconds is None else float(target_total_seconds)
    if prune_require_faces is None:
        prune_require_faces = cfg.get("prune_require_faces")

    if not 15.0 <= target_total_seconds <= 120.0:
        raise ValueError("target_total_seconds must be between 15 and 120 seconds")

    summary = research_topic(topic, use_groq=use_groq, groq_api_key=groq_api_key)
    summary["target_total_seconds"] = target_total_seconds

    try:
        kb = KnowledgeBase()
        expertise = kb.get_topic_expertise(topic)
        trending = kb.get_trending_techniques()
        idea = make_idea_with_knowledge(summary, topic, expertise, trending)
    except Exception as exc:
        logger.warning("Knowledge-enhanced idea generation failed: %s", exc)
        warnings.append(f"knowledge enhancement failed: {exc}")
        idea = make_idea(summary)

    subject = thumbnail_subject or (idea.get("title_options") or [topic])[0]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_topic = re.sub(r"[^A-Za-z0-9_-]", "_", topic)[:40]
    pkg_dir = os.path.join(out_root, f"{safe_topic}_{timestamp}")
    os.makedirs(pkg_dir, exist_ok=True)

    main_thumb = ""
    main_thumb_vertical = ""
    try:
        vars_dir = os.path.join(pkg_dir, "thumbnails")
        make_thumbnail_variants(subject, vars_dir, count=3)
        main_thumb = os.path.join(pkg_dir, "thumbnail.png")
        make_thumbnail(subject, main_thumb, size=(1280, 720))
        try:
            from .thumbnail import make_thumbnail_vertical

            main_thumb_vertical = os.path.join(pkg_dir, "thumbnail_vertical.png")
            make_thumbnail_vertical(subject, main_thumb_vertical, size=(1080, 1920))
        except Exception as exc:
            logger.warning("Vertical thumbnail generation failed: %s", exc)
            warnings.append(f"vertical thumbnail failed: {exc}")
    except Exception as exc:
        logger.warning("Thumbnail generation failed: %s", exc)
        warnings.append(f"thumbnail generation failed: {exc}")

    write_package(pkg_dir, summary, idea, main_thumb)

    # Persona extraction is optional enrichment.
    try:
        script_path = os.path.join(pkg_dir, "script.txt")
        script_text = ""
        if os.path.exists(script_path):
            with open(script_path, "r", encoding="utf-8") as sf:
                script_text = sf.read()
        script_text = script_text or idea.get("script") or ""
        if script_text.strip():
            from .persona import extract_personas

            personas = extract_personas(script_text, use_spacy=use_spacy_persona)
            with open(os.path.join(pkg_dir, "personas.json"), "w", encoding="utf-8") as pf:
                json.dump(personas, pf, indent=2)
    except Exception as exc:
        logger.warning("Persona extraction failed: %s", exc)
        warnings.append(f"persona extraction failed: {exc}")

    if main_thumb_vertical:
        try:
            import shutil

            dstv = os.path.join(pkg_dir, os.path.basename(main_thumb_vertical))
            if os.path.abspath(main_thumb_vertical) != os.path.abspath(dstv):
                shutil.copyfile(main_thumb_vertical, dstv)
        except Exception as exc:
            logger.warning("Vertical thumbnail copy failed: %s", exc)
            warnings.append(f"vertical thumbnail copy failed: {exc}")

    # Download supporting visuals, but never install packages at runtime.
    try:
        visuals = summary.get("visuals") or []
        if visuals:
            vis_dir = os.path.join(pkg_dir, "visuals")
            os.makedirs(vis_dir, exist_ok=True)
            try:
                if model_api_key:
                    from .visuals_fetcher import vet_with_model
                    visuals = vet_with_model(visuals, summary, model_api_key)
                else:
                    from .visuals_fetcher import annotate_purposes
                    visuals = annotate_purposes(visuals, summary)
            except Exception as exc:
                logger.warning("Visual vetting failed: %s", exc)
                warnings.append(f"visual vetting failed: {exc}")

            saved = download_visuals(
                visuals,
                vis_dir,
                download_clips=bool(enable_full_downloads),
                clip_max_duration=30,
            )
            try:
                from .visuals_fetcher import prune_visuals

                req_faces = prune_require_faces if prune_require_faces is not None else ["hook", "payoff", "conflict"]
                motion_thresholds = cfg.get("prune_motion_by_purpose")
                kept, removed = prune_visuals(
                    saved,
                    min_match_score=prune_min_match,
                    min_motion=prune_min_motion,
                    require_faces_for=req_faces,
                    min_model_confidence=prune_min_model_confidence,
                    motion_thresholds=motion_thresholds,
                )
                with open(os.path.join(vis_dir, "visuals.json"), "w", encoding="utf-8") as vf:
                    json.dump(kept, vf, indent=2)
                with open(os.path.join(vis_dir, "visuals_pruned.json"), "w", encoding="utf-8") as pf:
                    json.dump({"removed": removed}, pf, indent=2)
            except Exception as exc:
                logger.warning("Visual pruning failed: %s", exc)
                warnings.append(f"visual pruning failed: {exc}")
                with open(os.path.join(vis_dir, "visuals.json"), "w", encoding="utf-8") as vf:
                    json.dump(saved, vf, indent=2)
    except Exception as exc:
        logger.warning("Visual download pipeline failed: %s", exc)
        warnings.append(f"visual download pipeline failed: {exc}")

    # Enforce a strong first hook.
    try:
        from tools.enforce_hook import ensure_hook_first, generate_hook_variants
        from tools.visual_hook_generator import generate_visual_hook

        script_path = os.path.join(pkg_dir, "script.txt")
        if os.path.exists(script_path):
            with open(script_path, "r", encoding="utf-8") as f:
                text = f.read()
            hook = idea.get("hook", "")
            if hook:
                text = ensure_hook_first(text, hook)
            vhook = generate_visual_hook(pkg_dir)
            if vhook:
                lines = text.splitlines()
                rest = "\n".join(lines[1:]).lstrip()
                text = vhook + ("\n" + rest if rest else "")
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(text)

            variants = generate_hook_variants(text, n=6)
            with open(os.path.join(pkg_dir, "title_options.txt"), "w", encoding="utf-8") as tf:
                for variant in variants:
                    tf.write(variant["hook"] + "\n")
            try:
                from tools import hook_report

                hook_report.main(["hook_report", pkg_dir])
            except Exception as exc:
                logger.warning("Hook report generation failed: %s", exc)
                warnings.append(f"hook report failed: {exc}")
    except Exception as exc:
        logger.warning("Hook enforcement failed: %s", exc)
        warnings.append(f"hook enforcement failed: {exc}")

    with open(os.path.join(pkg_dir, "production_warnings.json"), "w", encoding="utf-8") as wf:
        json.dump({"count": len(warnings), "warnings": warnings}, wf, indent=2)
    return pkg_dir
