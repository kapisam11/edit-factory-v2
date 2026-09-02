"""Command-line entry point for AI Video Factory v2."""
import argparse
import os
import sys
from typing import List

from ai_video_factory.config import AIVFConfig
from ai_video_factory.nle_export_v2 import export_all_nle_formats
from ai_video_factory.pipeline import PipelineContext, build_director_pipeline
from ai_video_factory.quality_control_v2 import run_enhanced_qc
from ai_video_factory.subtitle_renderer import burn_subtitles


def _stage_skips_for_pipeline(config: AIVFConfig, pipeline_name: str) -> List[str]:
    selected = config.get_pipeline(pipeline_name)
    all_names = [
        "research", "plan", "script", "thumbnail", "auto_edit",
        "voiceover", "music", "quality_control", "metadata", "metrics",
    ]
    configured = set(selected.stages)
    # Preserve compatibility with config files that call QC simply "qc".
    if "qc" in configured:
        configured.add("quality_control")
    return [name for name in all_names if name not in configured]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="AI Video Factory v2 — generate upload-ready short video packages",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  %(prog)s "Minecraft betrayal on SMP" --raw-video gameplay.mp4 --director
  %(prog)s "COD 1v5 clutch" --raw-video clip.mp4 --pipeline fast --subtitle-style bold_yellow
  %(prog)s "Minecraft" --template minecraft_betrayal --pipeline package_only
""",
    )
    parser.add_argument("topic", help="Video topic or title")
    parser.add_argument("--out", default="output", help="Output root folder")
    parser.add_argument("--raw-video", default=None, help="Path to raw footage for auto-edit")
    parser.add_argument("--director", action="store_true", help="Use the full director pipeline")
    parser.add_argument("--pipeline", default="default", choices=["default", "fast", "package_only"])
    parser.add_argument("--template", default=None, help="Template name; skips research")
    parser.add_argument("--style", default="gaming_fast", choices=["gaming_fast", "gaming_cinematic", "tutorial"])
    parser.add_argument("--subtitle-style", default="bold_white", choices=["bold_white", "bold_yellow", "elegant_white", "clear_white", "karaoke"])
    parser.add_argument("--export-nle", default=None, choices=["resolve", "premiere", "capcut", "all"])
    parser.add_argument("--skip-stages", default="", help="Comma-separated stages to skip")
    parser.add_argument("--use-groq", action="store_true", help="Enable Groq research enrichment")
    parser.add_argument("--groq-key", default=None, help="Groq API key")
    parser.add_argument("--model-key", default=None, help="Model API key")
    parser.add_argument("--elevenlabs-key", default=None, help="ElevenLabs API key")
    parser.add_argument("--target-seconds", type=float, default=45.0, help="Target video length (15-120)")
    parser.add_argument("--skip-qc", action="store_true", help="Skip quality control")
    parser.add_argument("--learn", action="store_true", help="Update learning system")
    parser.add_argument("--engagement-score", type=float, default=None, help="Feedback score from 0.0 to 1.0")
    args = parser.parse_args()

    topic = args.topic.strip()
    if len(topic) < 2:
        parser.error("Topic must be at least 2 characters.")
    if args.raw_video and not os.path.isfile(args.raw_video):
        parser.error(f"Raw video not found: {args.raw_video}")
    if not 15.0 <= args.target_seconds <= 120.0:
        parser.error("Target seconds must be between 15 and 120.")
    if args.engagement_score is not None and not 0.0 <= args.engagement_score <= 1.0:
        parser.error("Engagement score must be between 0.0 and 1.0.")

    config = AIVFConfig.load()
    config.output_root = args.out
    config.active_pipeline = args.pipeline
    config.active_style = args.style
    if args.groq_key:
        config.set_api_key("groq", args.groq_key)
    if args.elevenlabs_key:
        config.set_api_key("elevenlabs", args.elevenlabs_key)
    if args.model_key:
        config.set_api_key("openai", args.model_key)

    skip_stages = _stage_skips_for_pipeline(config, "default" if args.director else args.pipeline)
    skip_stages.extend(s.strip() for s in args.skip_stages.split(",") if s.strip())
    if args.template:
        skip_stages.append("research")

    print("=" * 60)
    print("AI VIDEO FACTORY — v2")
    print(f"Topic: {topic}")
    print(f"Pipeline: {'default' if args.director else args.pipeline}")
    print(f"Style: {args.style}")
    print(f"Skipped stages: {sorted(set(skip_stages))}")
    print("=" * 60)

    try:
        pipeline = build_director_pipeline(skip_stages=sorted(set(skip_stages)))
        ctx = PipelineContext(
            topic=topic,
            raw_video=args.raw_video,
            target_seconds=args.target_seconds,
            skip_qc=args.skip_qc,
            use_groq=args.use_groq,
            model_key=config.api_keys.openai or os.environ.get("OPENAI_API_KEY"),
            groq_key=config.api_keys.groq or os.environ.get("GROQ_API_KEY"),
        )
        ctx = pipeline.run(ctx)
    except Exception as exc:
        print(f"\nPipeline failed: {exc}")
        return 1

    if ctx.errors:
        print("\nPipeline completed with errors:")
        for error in ctx.errors:
            print(f"  - {error}")
        return 1

    print(f"\nPipeline complete! Package: {ctx.package_dir}")

    if ctx.final_video and ctx.script:
        try:
            sub_out = os.path.join(ctx.package_dir, "final_with_subtitles.mp4")
            burn_subtitles(ctx.final_video, sub_out, ctx.script, style=args.subtitle_style)
            print(f"Subtitled video: {sub_out}")
        except Exception as exc:
            print(f"Subtitle burn-in failed: {exc}")

    if args.export_nle and ctx.package_dir:
        try:
            clips_dir = os.path.join(ctx.package_dir, "_clips")
            clips = [os.path.join(clips_dir, name) for name in sorted(os.listdir(clips_dir)) if name.endswith(".mp4")] if os.path.isdir(clips_dir) else []
            if clips:
                exports = export_all_nle_formats(ctx.package_dir, clips, ctx.plan)
                print(f"NLE exports: {exports}")
        except Exception as exc:
            print(f"NLE export failed: {exc}")

    if not args.skip_qc and ctx.package_dir:
        try:
            qc = run_enhanced_qc(ctx.package_dir, research=ctx.research, script=ctx.script)
            print(f"QC: {qc.get('status', 'complete')}")
            for warning in qc.get("warnings", [])[:5]:
                print(f"  ! {warning}")
        except Exception as exc:
            print(f"Enhanced QC failed: {exc}")

    if args.learn and args.engagement_score is not None and ctx.package_dir:
        try:
            from ai_video_factory.knowledge_v2 import RealKnowledgeBase, VideoFeatures

            kb = RealKnowledgeBase(root_dir=config.knowledge_root)
            features = VideoFeatures(
                topic=topic,
                filter_count=ctx.metrics.get("filter_count", 0),
                avg_shot_duration=ctx.metrics.get("avg_shot_duration", 0),
                cuts_per_minute=ctx.metrics.get("cuts_per_minute", 0),
                has_voiceover=ctx.voiceover is not None,
                has_music=ctx.music_track is not None,
                shot_variety_ratio=0.75 if ctx.qc_report.get("checks", {}).get("shot_variance_ok", False) else 0.5,
                filters_used={f: True for f in ctx.plan.get("filters_used", [])},
            )
            kb.learn_from_feedback(ctx.package_dir, args.engagement_score, features)
            print(f"Learning updated with engagement score {args.engagement_score:.2f}")
        except Exception as exc:
            print(f"Learning update failed: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
