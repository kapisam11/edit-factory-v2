"""CLI for AI Video Factory v2 — supports pipelines, templates, and real learning.

Usage:
    # Full director pipeline (recommended)
    python cli_v2.py "Minecraft betrayal on SMP" --raw-video clip.mp4 --director
    # Use a template (no re-research)
    python cli_v2.py "Minecraft betrayal" --template minecraft_betrayal
    # Fast pipeline (skip research)
    python cli_v2.py "COD clutch" --raw-video clip.mp4 --pipeline fast
    # With styled subtitles
    python cli_v2.py "Topic" --raw-video clip.mp4 --subtitle-style bold_yellow
    # Export to DaVinci Resolve
    python cli_v2.py "Topic" --raw-video clip.mp4 --export-nle resolve
"""
import argparse
import os
import sys

from ai_video_factory.config import AIVFConfig
from ai_video_factory.pipeline import build_director_pipeline, PipelineContext
from ai_video_factory.nle_export_v2 import export_all_nle_formats
from ai_video_factory.subtitle_renderer import burn_subtitles
from ai_video_factory.quality_control_v2 import run_enhanced_qc


def main():
    p = argparse.ArgumentParser(
        description="AI Video Factory v2 — generate upload-ready short video packages",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  %(prog)s "Minecraft betrayal on SMP" --raw-video gameplay.mp4 --director
  %(prog)s "COD 1v5 clutch" --raw-video clip.mp4 --pipeline fast --subtitle-style bold_yellow
  %(prog)s "Minecraft" --template minecraft_betrayal --export-nle resolve
  %(prog)s "Topic" --out output --use-groq --skip-stages research music
        """,
    )
    p.add_argument("topic", help="Video topic or title")
    p.add_argument("--out", default="output", help="Output root folder")
    p.add_argument("--raw-video", default=None, help="Path to raw footage for auto-edit")
    p.add_argument("--director", action="store_true", help="Use full director pipeline")
    p.add_argument("--pipeline", default="default", choices=["default", "fast", "package_only"],
                   help="Pipeline preset to use")
    p.add_argument("--template", default=None, help="Use a template (skips research)")
    p.add_argument("--style", default="gaming_fast", choices=["gaming_fast", "gaming_cinematic", "tutorial"],
                   help="Style profile")
    p.add_argument("--subtitle-style", default="bold_white",
                   choices=["bold_white", "bold_yellow", "elegant_white", "clear_white", "karaoke"],
                   help="Subtitle burn-in style")
    p.add_argument("--export-nle", default=None, choices=["resolve", "premiere", "capcut", "all"],
                   help="Export to NLE format after rendering")
    p.add_argument("--skip-stages", default="", help="Comma-separated stages to skip (e.g., research,music)")
    p.add_argument("--use-groq", action="store_true", help="Enable Groq research enrichment")
    p.add_argument("--groq-key", default=None, help="Groq API key")
    p.add_argument("--model-key", default=None, help="Model API key")
    p.add_argument("--target-seconds", type=float, default=45.0, help="Target video length")
    p.add_argument("--skip-qc", action="store_true", help="Skip quality control")
    p.add_argument("--interactive", action="store_true", help="Interactive review")
    p.add_argument("--review", action="store_true", help="Run automated review")
    p.add_argument("--auto-fix", action="store_true", help="Auto-fix issues")
    p.add_argument("--elevenlabs-key", default=None, help="ElevenLabs API key")
    p.add_argument("--learn", action="store_true", help="Enable real learning feedback loop")
    p.add_argument("--engagement-score", type=float, default=None,
                   help="Provide engagement score (0.0-1.0) to train the learning system")
    args = p.parse_args()

    if not args.topic or len(args.topic.strip()) < 2:
        p.error("Topic must be at least 2 characters.")
    if args.raw_video and not os.path.exists(args.raw_video):
        p.error(f"Raw video not found: {args.raw_video}")
    if args.target_seconds < 15 or args.target_seconds > 120:
        p.error("Target seconds must be between 15 and 120.")

    # Load config
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

    skip_stages = [s.strip() for s in args.skip_stages.split(",") if s.strip()]
    if args.template:
        skip_stages.append("research")

    print("=" * 50)
    print("AI VIDEO FACTORY — v2")
    print(f"Topic: {args.topic}")
    print(f"Pipeline: {args.pipeline}")
    print(f"Style: {args.style}")
    print(f"Skip stages: {skip_stages}")
    print("=" * 50)

    # Build and run pipeline
    pipeline = build_director_pipeline(skip_stages=skip_stages)
    ctx = PipelineContext(
        topic=args.topic,
        raw_video=args.raw_video,
        target_seconds=args.target_seconds,
        skip_qc=args.skip_qc,
        use_groq=args.use_groq,
        model_key=config.api_keys.openai or os.environ.get("OPENAI_API_KEY"),
        groq_key=config.api_keys.groq or os.environ.get("GROQ_API_KEY"),
    )

    ctx = pipeline.run(ctx)

    if ctx.errors:
        print("\n* Pipeline completed with errors:")
        for err in ctx.errors:
            print(f"  - {err}")
        sys.exit(1)

    print(f"\n+ Pipeline complete!")
    print(f"Package: {ctx.package_dir}")

    # Subtitle burn-in
    if ctx.final_video and ctx.script and args.subtitle_style:
        try:
            sub_out = os.path.join(ctx.package_dir, "final_with_subtitles.mp4")
            burn_subtitles(ctx.final_video, sub_out, ctx.script, style=args.subtitle_style)
            print(f"Subtitled video: {sub_out}")
        except Exception as e:
            print(f"Subtitle burn-in failed: {e}")

    # NLE Export
    if args.export_nle and ctx.package_dir:
        try:
            clips_dir = os.path.join(ctx.package_dir, "_clips")
            clips = []
            if os.path.exists(clips_dir):
                clips = [os.path.join(clips_dir, c) for c in sorted(os.listdir(clips_dir)) if c.endswith(".mp4")]
            if clips:
                exports = export_all_nle_formats(ctx.package_dir, clips, ctx.plan)
                print(f"NLE exports: {exports}")
        except Exception as e:
            print(f"NLE export failed: {e}")

    # Enhanced QC
    if not args.skip_qc and ctx.package_dir:
        try:
            qc = run_enhanced_qc(ctx.package_dir, research=ctx.research, script=ctx.script)
            print(f"QC report: {os.path.join(ctx.package_dir, 'qc_report_v2.json')}")
            if qc.get("warnings"):
                print(f"Warnings ({len(qc['warnings'])}):")
                for w in qc["warnings"][:5]:
                    print(f"  ! {w}")
        except Exception as e:
            print(f"Enhanced QC failed: {e}")

    # Learning system feedback
    if args.learn and ctx.package_dir:
        try:
            from ai_video_factory.knowledge_v2 import RealKnowledgeBase, VideoFeatures
            kb = RealKnowledgeBase(root_dir=config.knowledge_root)

            features = VideoFeatures(
                topic=args.topic,
                filter_count=ctx.metrics.get("filter_count", 0),
                avg_shot_duration=ctx.metrics.get("avg_shot_duration", 0),
                cuts_per_minute=ctx.metrics.get("cuts_per_minute", 0),
                has_voiceover=ctx.voiceover is not None,
                has_music=ctx.music_track is not None,
                shot_variety_ratio=ctx.qc_report.get("checks", {}).get("shot_variance_ok", False) and 0.75 or 0.5,
                filters_used={f: True for f in (ctx.plan.get("filters_used", []))},
            )

            if args.engagement_score is not None:
                kb.learn_from_feedback(
                    package_id=ctx.package_dir,
                    engagement_score=args.engagement_score,
                    features=features,
                )
                print(f"Learning system updated with score: {args.engagement_score}")
            else:
                print("Tip: Use --engagement-score 0.85 to train the learning system.")

            report = kb.get_learning_report()
            print(f"Learning report: {report['total_feedback_records']} records, "
                  f"{len(report['filters_tracked'])} filters tracked")
        except Exception as e:
            print(f"Learning update failed: {e}")

    print("\nDone.")


if __name__ == "__main__":
    main()
"""CLI for AI Video Factory v2 — supports pipelines, templates, and real learning.

Usage:
    # Full director pipeline (recommended)
    python cli_v2.py "Minecraft betrayal on SMP" --raw-video clip.mp4 --director

    # Use a template (no re-research)
    python cli_v2.py "Minecraft betrayal" --template minecraft_betrayal

    # Fast pipeline (skip research)
    python cli_v2.py "COD clutch" --raw-video clip.mp4 --pipeline fast

    # With styled subtitles
    python cli_v2.py "Topic" --raw-video clip.mp4 --subtitle-style bold_yellow

    # Export to DaVinci Resolve
    python cli_v2.py "Topic" --raw-video clip.mp4 --export-nle resolve
"""
import argparse
import os
import sys

from ai_video_factory.config import AIVFConfig
from ai_video_factory.pipeline import build_director_pipeline, PipelineContext
from ai_video_factory.nle_export_v2 import export_all_nle_formats
from ai_video_factory.subtitle_renderer import burn_subtitles
from ai_video_factory.quality_control_v2 import run_enhanced_qc


def main():
    p = argparse.ArgumentParser(
        description="AI Video Factory v2 — generate upload-ready short video packages",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s "Minecraft betrayal on SMP" --raw-video gameplay.mp4 --director
  %(prog)s "COD 1v5 clutch" --raw-video clip.mp4 --pipeline fast --subtitle-style bold_yellow
  %(prog)s "Minecraft" --template minecraft_betrayal --export-nle resolve
  %(prog)s "Topic" --out output --use-groq --skip-stages research music
        """,
    )
    p.add_argument("topic", help="Video topic or title")
    p.add_argument("--out", default="output", help="Output root folder")
    p.add_argument("--raw-video", default=None, help="Path to raw footage for auto-edit")
    p.add_argument("--director", action="store_true", help="Use full director pipeline")
    p.add_argument("--pipeline", default="default", choices=["default", "fast", "package_only"],
                   help="Pipeline preset to use")
    """CLI for AI Video Factory v2 — supports pipelines, templates, and real learning.

    Usage:
        python cli_v2.py "Minecraft betrayal on SMP" --raw-video clip.mp4 --director
        python cli_v2.py "Minecraft betrayal" --template minecraft_betrayal
        python cli_v2.py "COD clutch" --raw-video clip.mp4 --pipeline fast --subtitle-style bold_yellow
        python cli_v2.py "Topic" --raw-video clip.mp4 --export-nle resolve
    """
    import argparse
    import os
    import sys

    from ai_video_factory.config import AIVFConfig
    from ai_video_factory.pipeline import build_director_pipeline, PipelineContext
    from ai_video_factory.nle_export_v2 import export_all_nle_formats
    from ai_video_factory.subtitle_renderer import burn_subtitles
    from ai_video_factory.quality_control_v2 import run_enhanced_qc


    def main():
        p = argparse.ArgumentParser(
            description="AI Video Factory v2 — generate upload-ready short video packages",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
    Examples:
      %(prog)s "Minecraft betrayal on SMP" --raw-video gameplay.mp4 --director
      %(prog)s "COD 1v5 clutch" --raw-video clip.mp4 --pipeline fast --subtitle-style bold_yellow
      %(prog)s "Minecraft" --template minecraft_betrayal --export-nle resolve
      %(prog)s "Topic" --out output --use-groq --skip-stages research music
            """,
        )
        p.add_argument("topic", help="Video topic or title")
        p.add_argument("--out", default="output", help="Output root folder")
        p.add_argument("--raw-video", default=None, help="Path to raw footage for auto-edit")
        p.add_argument("--director", action="store_true", help="Use full director pipeline")
        p.add_argument("--pipeline", default="default", choices=["default", "fast", "package_only"],
                       help="Pipeline preset to use")
        p.add_argument("--template", default=None, help="Use a template (skips research)")
        p.add_argument("--style", default="gaming_fast", choices=["gaming_fast", "gaming_cinematic", "tutorial"],
                       help="Style profile")
        p.add_argument("--subtitle-style", default="bold_white",
                       choices=["bold_white", "bold_yellow", "elegant_white", "clear_white", "karaoke"],
                       help="Subtitle burn-in style")
        p.add_argument("--export-nle", default=None, choices=["resolve", "premiere", "capcut", "all"],
                       help="Export to NLE format after rendering")
        p.add_argument("--skip-stages", default="", help="Comma-separated stages to skip (e.g., research,music)")
        p.add_argument("--use-groq", action="store_true", help="Enable Groq research enrichment")
        p.add_argument("--groq-key", default=None, help="Groq API key")
        p.add_argument("--model-key", default=None, help="Model API key")
        p.add_argument("--target-seconds", type=float, default=45.0, help="Target video length")
        p.add_argument("--skip-qc", action="store_true", help="Skip quality control")
        p.add_argument("--interactive", action="store_true", help="Interactive review")
        p.add_argument("--review", action="store_true", help="Run automated review")
        p.add_argument("--auto-fix", action="store_true", help="Auto-fix issues")
        p.add_argument("--elevenlabs-key", default=None, help="ElevenLabs API key")
        p.add_argument("--learn", action="store_true", help="Enable real learning feedback loop")
        p.add_argument("--engagement-score", type=float, default=None,
                       help="Provide engagement score (0.0-1.0) to train the learning system")
        args = p.parse_args()

        if not args.topic or len(args.topic.strip()) < 2:
            p.error("Topic must be at least 2 characters.")
        if args.raw_video and not os.path.exists(args.raw_video):
            p.error(f"Raw video not found: {args.raw_video}")
        if args.target_seconds < 15 or args.target_seconds > 120:
            p.error("Target seconds must be between 15 and 120.")

        # Load config
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

        skip_stages = [s.strip() for s in args.skip_stages.split(",") if s.strip()]
        if args.template:
            skip_stages.append("research")

        print("=" * 50)
        print("AI VIDEO FACTORY — v2")
        print(f"Topic: {args.topic}")
        print(f"Pipeline: {args.pipeline}")
        print(f"Style: {args.style}")
        print(f"Skip stages: {skip_stages}")
        print("=" * 50)

        # Build and run pipeline
        pipeline = build_director_pipeline(skip_stages=skip_stages)
        ctx = PipelineContext(
            topic=args.topic,
            raw_video=args.raw_video,
            target_seconds=args.target_seconds,
            skip_qc=args.skip_qc,
            use_groq=args.use_groq,
            model_key=config.api_keys.openai or os.environ.get("OPENAI_API_KEY"),
            groq_key=config.api_keys.groq or os.environ.get("GROQ_API_KEY"),
        )
    
        ctx = pipeline.run(ctx)

        if ctx.errors:
            print("\n* Pipeline completed with errors:")
            for err in ctx.errors:
                print(f"  - {err}")
            sys.exit(1)

        print(f"\n+ Pipeline complete!")
        print(f"Package: {ctx.package_dir}")

        # Subtitle burn-in
        if ctx.final_video and ctx.script and args.subtitle_style:
            try:
                sub_out = os.path.join(ctx.package_dir, "final_with_subtitles.mp4")
                burn_subtitles(ctx.final_video, sub_out, ctx.script, style=args.subtitle_style)
                print(f"Subtitled video: {sub_out}")
            except Exception as e:
                print(f"Subtitle burn-in failed: {e}")

        # NLE Export
        if args.export_nle and ctx.package_dir:
            try:
                clips_dir = os.path.join(ctx.package_dir, "_clips")
                clips = []
                if os.path.exists(clips_dir):
                    clips = [os.path.join(clips_dir, c) for c in sorted(os.listdir(clips_dir)) if c.endswith(".mp4")]
                if clips:
                    exports = export_all_nle_formats(ctx.package_dir, clips, ctx.plan)
                    print(f"NLE exports: {exports}")
            except Exception as e:
                print(f"NLE export failed: {e}")

        # Enhanced QC
        if not args.skip_qc and ctx.package_dir:
            try:
                qc = run_enhanced_qc(ctx.package_dir, research=ctx.research, script=ctx.script)
                print(f"QC report: {os.path.join(ctx.package_dir, 'qc_report_v2.json')}")
                if qc.get("warnings"):
                    print(f"Warnings ({len(qc['warnings'])}):")
                    for w in qc["warnings"][:5]:
                        print(f"  ! {w}")
            except Exception as e:
                print(f"Enhanced QC failed: {e}")

        # Learning system feedback
        if args.learn and ctx.package_dir:
            try:
                from ai_video_factory.knowledge_v2 import RealKnowledgeBase, VideoFeatures
                kb = RealKnowledgeBase(root_dir=config.knowledge_root)
            
                features = VideoFeatures(
                    topic=args.topic,
                    filter_count=ctx.metrics.get("filter_count", 0),
                    avg_shot_duration=ctx.metrics.get("avg_shot_duration", 0),
                    cuts_per_minute=ctx.metrics.get("cuts_per_minute", 0),
                    has_voiceover=ctx.voiceover is not None,
                    has_music=ctx.music_track is not None,
                    shot_variety_ratio=ctx.qc_report.get("checks", {}).get("shot_variance_ok", False) and 0.75 or 0.5,
                    filters_used={f: True for f in (ctx.plan.get("filters_used", []))},
                )
            
                if args.engagement_score is not None:
                    kb.learn_from_feedback(
                        package_id=ctx.package_dir,
                        engagement_score=args.engagement_score,
                        features=features,
                    )
                    print(f"Learning system updated with score: {args.engagement_score}")
                else:
                    print("Tip: Use --engagement-score 0.85 to train the learning system.")
                
                report = kb.get_learning_report()
                print(f"Learning report: {report['total_feedback_records']} records, "
                      f"{len(report['filters_tracked'])} filters tracked")
            except Exception as e:
                print(f"Learning update failed: {e}")

        print("\nDone.")


    if __name__ == "__main__":
        main()
    p.add_argument("--director", action="store_true", help="Use VideoDirector workflow (full creative pipeline)")
    p.add_argument("--thumbnail-subject", default=None, help="Custom thumbnail subject text")
    p.add_argument("--use-groq", action="store_true", help="Enable Groq research enrichment")
    p.add_argument("--groq-key", default=None, help="Groq API key (or set GROQ_API_KEY env var)")
    p.add_argument("--model-key", default=None, help="Model API key for QC/review (or set OPENAI_API_KEY)")
    p.add_argument("--target-seconds", type=float, default=45.0, help="Target video length (default 45)")
    p.add_argument("--skip-qc", action="store_true", help="Skip quality control checks (faster, for testing)")
    p.add_argument("--interactive", action="store_true", help="Interactive human-in-the-loop review")
    p.add_argument("--elevenlabs-key", default=None, help="ElevenLabs API key for high-quality TTS")
    p.add_argument("--review", action="store_true", help="Run automated review before finalizing")
    p.add_argument("--auto-fix", action="store_true", help="Auto-fix issues found in review")
    p.add_argument("--force-export", action="store_true", help="Force export even if QC fails")
    p.add_argument("--legacy", action="store_true", help="Use legacy producer instead of director")
    args = p.parse_args()

    if not args.topic or len(args.topic.strip()) < 2:
        p.error("Topic must be at least 2 characters.")

    if args.raw_video and not os.path.exists(args.raw_video):
        p.error(f"Raw video not found: {args.raw_video}")

    if args.target_seconds < 15 or args.target_seconds > 120:
        p.error("Target seconds must be between 15 and 120.")

    groq_key = args.groq_key or os.environ.get("GROQ_API_KEY")
    model_key = args.model_key or os.environ.get("OPENAI_API_KEY")

    # —— DIRECTOR WORKFLOW (recommended) ——————————————————————————————
    if args.director or (args.raw_video and not args.legacy):
        from ai_video_factory.director import VideoDirector

        print("=" * 50)
        print("AI VIDEO FACTORY — Director Mode")
        print("Topic:", args.topic)
        print("Raw video:", args.raw_video or "(none)")
        print("Target:", args.target_seconds, "seconds")
        print("=" * 50)

        director = VideoDirector(out_root=args.out, model_key=model_key)
        pkg = director.produce(
            args.topic,
            raw_video=args.raw_video,
            use_groq=args.use_groq,
            groq_key=groq_key,
            target_seconds=args.target_seconds,
            skip_qc=args.skip_qc,
        )
        print("\n✓ Director workflow complete!")
        print("Package:", pkg)

        # Optional: high-quality TTS
        if args.elevenlabs_key:
            from ai_video_factory.tts import generate_high_quality_voiceover
            script_path = os.path.join(pkg, "script.txt")
            if os.path.exists(script_path):
                with open(script_path, "r", encoding="utf-8") as f:
                    text = f.read()
                vo_out = os.path.join(pkg, "voice_hq.mp3")
                try:
                    generate_high_quality_voiceover(text, vo_out, args.elevenlabs_key)
                    print("High-quality VO:", vo_out)
                except Exception as e:
                    print("HQ TTS failed:", e)

        # Optional: interactive review
        if args.interactive:
            from ai_video_factory.interactive_review import interactive_review
            try:
                interactive_review(pkg, use_model=args.review, model_key=model_key, prefer_local=True)
            except Exception as e:
                print("Interactive review failed:", e)

        # Optional: EDL export
        clips_dir = os.path.join(pkg, "_clips")
        if os.path.exists(clips_dir):
            from ai_video_factory.nle_export import export_edl
            seq = [os.path.join(clips_dir, p) for p in sorted(os.listdir(clips_dir)) if p.endswith(".mp4")]
            if seq:
                edl = export_edl(pkg, seq)
                print("EDL:", edl)

        return

    # —— LEGACY WORKFLOW ————————————————————————————————————————
    from ai_video_factory.factory import create_package

    pkg = create_package(
        args.topic,
        out_root=args.out,
        thumbnail_subject=args.thumbnail_subject,
        use_groq=args.use_groq,
        groq_api_key=groq_key,
        target_total_seconds=args.target_seconds,
    )
    print("Package created:", pkg)

    if args.raw_video:
        if not os.path.exists(args.raw_video):
            print("ERROR: Raw video not found:", args.raw_video)
            sys.exit(1)

        if args.interactive:
            from ai_video_factory.interactive_review import interactive_review
            try:
                interactive_review(pkg, use_model=args.review, model_key=model_key, prefer_local=True)
            except Exception as e:
                print("Interactive review failed:", e)

        from ai_video_factory.composer import compose_short_from_video
        from ai_video_factory.nle_export import export_edl

        try:
            out = compose_short_from_video(
                args.raw_video,
                pkg,
                review=args.review,
                auto_fix=args.auto_fix,
                model_key=model_key,
            )
        except Exception as e:
            if args.force_export:
                print("QC failed, force-exporting:", e)
                out = compose_short_from_video(
                    args.raw_video, pkg,
                    review=False, auto_fix=False,
                    model_key=model_key, skip_qc=True,
                )
            else:
                print("Auto-edit aborted:", e)
                sys.exit(1)

        print("Auto-edit output:", out)

        clips_dir = os.path.join(pkg, "_clips")
        if os.path.exists(clips_dir):
            seq = [os.path.join(clips_dir, p) for p in sorted(os.listdir(clips_dir)) if p.endswith(".mp4")]
            if seq:
                edl = export_edl(pkg, seq)
                print("EDL exported:", edl)


if __name__ == "__main__":
    main()