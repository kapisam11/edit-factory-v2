"""AI Video Factory — Pipeline Stage System.

Replaces the 500-line god method with discrete, testable, swappable stages.
Each stage receives a PipelineContext and returns a modified context.
Failed stages can be retried or skipped without re-running the whole pipeline.
"""
import json
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable

from enum import Enum


# Compatibility layer for older director imports
class Severity(Enum):
    CRITICAL = "critical"
    DEGRADED = "degraded"
    OPTIONAL = "optional"


@dataclass
class StepResult:
    ok: bool
    output: Any = None
    severity: Severity = Severity.DEGRADED
    notes: List[str] = None

    def __post_init__(self):
        if self.notes is None:
            self.notes = []

    @property
    def failed_critical(self) -> bool:
        return not self.ok and self.severity == Severity.CRITICAL

    @property
    def failed_degraded(self) -> bool:
        return not self.ok and self.severity == Severity.DEGRADED

    @classmethod
    def success(cls, output: Any = None, notes: Optional[List[str]] = None) -> "StepResult":
        return cls(ok=True, output=output, severity=Severity.OPTIONAL, notes=notes or [])

    @classmethod
    def critical(cls, output: Any = None, notes: Optional[List[str]] = None) -> "StepResult":
        return cls(ok=False, output=output, severity=Severity.CRITICAL, notes=notes or [])

    @classmethod
    def degraded(cls, output: Any = None, notes: Optional[List[str]] = None) -> "StepResult":
        return cls(ok=False, output=output, severity=Severity.DEGRADED, notes=notes or [])

    @classmethod
    def optional(cls, output: Any = None, notes: Optional[List[str]] = None) -> "StepResult":
        return cls(ok=False, output=output, severity=Severity.OPTIONAL, notes=notes or [])


class PipelineError(Exception):
    def __init__(self, result: StepResult, step_name: str = ""):
        self.result = result
        self.step_name = step_name
        super().__init__(f"Pipeline step '{step_name}' failed: {result.notes}")


class PipelineManifest:
    def __init__(self, topic: str, target_seconds: float = 45.0):
        self.topic = topic
        self.target_seconds = target_seconds
        self.steps: Dict[str, StepResult] = {}
        self.degraded: bool = False
        self.critical_failure: Optional[str] = None
        self.artifacts: Dict[str, Any] = {}

    def record(self, name: str, result: StepResult) -> None:
        self.steps[name] = result
        if result.failed_degraded:
            self.degraded = True
        if result.failed_critical:
            self.critical_failure = name

    def add_artifact(self, key: str, value: Any) -> None:
        self.artifacts[key] = value

    """AI Video Factory — Pipeline Stage System.

    Replaces the 500-line god method with discrete, testable, swappable stages.
    Each stage receives a PipelineContext and returns a modified context.
    Failed stages can be retried or skipped without re-running the whole pipeline.
    """
    import json
    import os
    import time
    from abc import ABC, abstractmethod
    from dataclasses import dataclass, field
    from datetime import datetime
    from pathlib import Path
    from typing import Any, Dict, List, Optional


    @dataclass
    class PipelineContext:
        """Shared state passed through all pipeline stages."""
        topic: str
        package_dir: Optional[str] = None
        raw_video: Optional[str] = None
        target_seconds: float = 45.0
        skip_qc: bool = False
        use_groq: bool = False
        model_key: Optional[str] = None
        groq_key: Optional[str] = None

        # Stage outputs
        research: Dict[str, Any] = field(default_factory=dict)
        plan: Dict[str, Any] = field(default_factory=dict)
        script: str = ""
        edit_plan: List[Dict[str, Any]] = field(default_factory=list)
        clips: List[str] = field(default_factory=list)
        final_video: Optional[str] = None
        thumbnail: Optional[str] = None
        voiceover: Optional[str] = None
        music_track: Optional[str] = None
        metadata: Dict[str, Any] = field(default_factory=dict)
        metrics: Dict[str, Any] = field(default_factory=dict)
        qc_report: Dict[str, Any] = field(default_factory=dict)
        errors: List[str] = field(default_factory=list)
        warnings: List[str] = field(default_factory=list)

        def to_json(self) -> str:
            return json.dumps({
                k: v for k, v in self.__dict__.items()
                if k not in ("model_key", "groq_key")  # Don't leak keys
            }, indent=2, default=str)


    class PipelineStage(ABC):
        """Base class for all pipeline stages."""
        name: str = "stage"
        skippable: bool = False
        retryable: bool = True
        max_retries: int = 1

        @abstractmethod
        def run(self, ctx: PipelineContext) -> PipelineContext:
            """Execute the stage. Modifies and returns the context."""
            ...

        def on_error(self, ctx: PipelineContext, error: Exception) -> PipelineContext:
            """Handle stage failure. Default: log and continue if skippable."""
            ctx.errors.append(f"[{self.name}] {error}")
            if not self.skippable:
                raise error
            ctx.warnings.append(f"[{self.name}] Skipped due to error: {error}")
            return ctx


    class Pipeline:
        """Orchestrates stages in order with error handling and retries."""

        def __init__(self, stages: List[PipelineStage], verbose: bool = True):
            self.stages = stages
            self.verbose = verbose
            self._stage_times: Dict[str, float] = {}

        def run(self, ctx: PipelineContext) -> PipelineContext:
            for stage in self.stages:
                start = time.time()
                if self.verbose:
                    print(f"[PIPELINE] → {stage.name}")

                attempts = 0
                success = False
                last_error = None

                while attempts <= stage.max_retries and not success:
                    try:
                        ctx = stage.run(ctx)
                        success = True
                    except Exception as e:
                        last_error = e
                        attempts += 1
                        if attempts <= stage.max_retries:
                            time.sleep(0.5 * attempts)  # Backoff

                if not success and last_error:
                    ctx = stage.on_error(ctx, last_error)

                elapsed = time.time() - start
                self._stage_times[stage.name] = elapsed
                if self.verbose:
                    status = "✓" if success else "⚠ skipped" if stage.skippable else "✗ FAILED"
                    print(f"[PIPELINE]   {status} {stage.name} ({elapsed:.2f}s)")

            # Save pipeline report
            if ctx.package_dir:
                report_path = os.path.join(ctx.package_dir, "pipeline_report.json")
                with open(report_path, "w", encoding="utf-8") as f:
                    json.dump({
                        "stages": [s.name for s in self.stages],
                        "stage_times": self._stage_times,
                        "errors": ctx.errors,
                        "warnings": ctx.warnings,
                        "completed_at": datetime.now().isoformat(),
                    }, f, indent=2)

            return ctx

        def get_report(self) -> Dict[str, Any]:
            return {
                "stages": [s.name for s in self.stages],
                "stage_times": self._stage_times,
            }


    # --- Concrete Stage Implementations ---

    class ResearchStage(PipelineStage):
        name = "research"
        skippable = True

        def run(self, ctx: PipelineContext) -> PipelineContext:
            from .capability_registry import build_default_registry
            reg = build_default_registry()
            result = reg.call("research", query=ctx.topic)
            if result.success:
                ctx.research = result.data if isinstance(result.data, dict) else {"summary": result.data}
            else:
                ctx.warnings.append(f"Research failed: {result.error}")
                ctx.research = {"title": ctx.topic, "summary": f"Auto-generated research for {ctx.topic}"}
            return ctx


    class PlanStage(PipelineStage):
        name = "plan"
        skippable = False

        def run(self, ctx: PipelineContext) -> PipelineContext:
            from .plan import make_idea
            summary = ctx.research if ctx.research else {"title": ctx.topic, "topic": ctx.topic}
            idea = make_idea(summary)
            ctx.plan = idea
            ctx.edit_plan = idea.get("edit_plan", [])
            return ctx


    class ScriptStage(PipelineStage):
        name = "script"
        skippable = False

        def run(self, ctx: PipelineContext) -> PipelineContext:
            from .story import generate_script
            ctx.script = generate_script(ctx.plan, ctx.topic)
            return ctx


    class ThumbnailStage(PipelineStage):
        name = "thumbnail"
        skippable = True

        def run(self, ctx: PipelineContext) -> PipelineContext:
            # Placeholder: actual thumbnail generation would go here
            ctx.thumbnail = os.path.join(ctx.package_dir, "thumbnail.png") if ctx.package_dir else None
            return ctx


    class AutoEditStage(PipelineStage):
        name = "auto_edit"
        skippable = False
        retryable = True
        max_retries = 2

        def run(self, ctx: PipelineContext) -> PipelineContext:
            if not ctx.raw_video:
                ctx.warnings.append("No raw video provided, skipping auto-edit")
                return ctx
            from .composer import compose_short_from_video
            out = compose_short_from_video(
                ctx.raw_video,
                ctx.package_dir,
                review=not ctx.skip_qc,
                auto_fix=True,
                model_key=ctx.model_key,
                skip_qc=ctx.skip_qc,
            )
            ctx.final_video = out
            return ctx


    class VoiceoverStage(PipelineStage):
        name = "voiceover"
        skippable = True

        def run(self, ctx: PipelineContext) -> PipelineContext:
            if not ctx.script:
                return ctx
            from .capability_registry import build_default_registry
            reg = build_default_registry()
            vo_path = os.path.join(ctx.package_dir, "voiceover.mp3") if ctx.package_dir else "voiceover.mp3"
            result = reg.call("tts", text=ctx.script, output_path=vo_path)
            if result.success:
                ctx.voiceover = result.data
            else:
                ctx.warnings.append(f"TTS failed: {result.error}")
            return ctx


    class MusicStage(PipelineStage):
        name = "music"
        skippable = True

        def run(self, ctx: PipelineContext) -> PipelineContext:
            from .capability_registry import build_default_registry
            reg = build_default_registry()
            music_path = os.path.join(ctx.package_dir, "music_track.mp3") if ctx.package_dir else "music_track.mp3"
            emotion = ctx.plan.get("mood", "dramatic")
            result = reg.call("music", emotion=emotion, output_path=music_path)
            if result.success:
                ctx.music_track = result.data
            else:
                ctx.warnings.append(f"Music fetch failed: {result.error}")
            return ctx


    class QCStage(PipelineStage):
        name = "quality_control"
        skippable = True

        def run(self, ctx: PipelineContext) -> PipelineContext:
            if ctx.skip_qc:
                ctx.qc_report = {"skipped": True}
                return ctx
            from .quality_control import run_final_checks
            ctx.qc_report = run_final_checks(ctx.package_dir)
            return ctx


    class MetadataStage(PipelineStage):
        name = "metadata"
        skippable = True

        def run(self, ctx: PipelineContext) -> PipelineContext:
            ctx.metadata = {
                "title": ctx.plan.get("title", ctx.topic),
                "topic": ctx.topic,
                "target_seconds": ctx.target_seconds,
                "generated_at": datetime.now().isoformat(),
                "has_voiceover": ctx.voiceover is not None,
                "has_music": ctx.music_track is not None,
            }
            if ctx.package_dir:
                meta_path = os.path.join(ctx.package_dir, "metadata.json")
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(ctx.metadata, f, indent=2)
            return ctx


    class MetricsStage(PipelineStage):
        name = "metrics"
        skippable = True

        def run(self, ctx: PipelineContext) -> PipelineContext:
            """Extract measurable features from the generated package."""
            ctx.metrics = {
                "filter_count": len(ctx.edit_plan),
                "avg_shot_duration": (
                    sum(s.get("duration", 0) for s in ctx.edit_plan) / max(len(ctx.edit_plan), 1)
                ),
                "cuts_per_minute": (
                    len(ctx.edit_plan) / (ctx.target_seconds / 60.0)
                ),
                "has_voiceover": ctx.voiceover is not None,
                "has_music": ctx.music_track is not None,
                "render_time_seconds": 0.0,  # Updated by render stage
            }
            if ctx.package_dir:
                metrics_path = os.path.join(ctx.package_dir, "metrics.json")
                with open(metrics_path, "w", encoding="utf-8") as f:
                    json.dump(ctx.metrics, f, indent=2)
            return ctx


    def build_director_pipeline(skip_stages: Optional[List[str]] = None) -> Pipeline:
        """Build the full director pipeline.

        Args:
            skip_stages: List of stage names to skip (e.g., ["research", "music"])
        """
        all_stages = [
            ResearchStage(),
            PlanStage(),
            ScriptStage(),
            ThumbnailStage(),
            AutoEditStage(),
            VoiceoverStage(),
            MusicStage(),
            QCStage(),
            MetadataStage(),
            MetricsStage(),
        ]
        skip_set = set(skip_stages or [])
        stages = [s for s in all_stages if s.name not in skip_set]
        return Pipeline(stages, verbose=True)

def build_director_pipeline(skip_stages: Optional[List[str]] = None) -> Pipeline:
    all_stages = [
        ResearchStage(),
        PlanStage(),
        ScriptStage(),
        ThumbnailStage(),
        AutoEditStage(),
        VoiceoverStage(),
        MusicStage(),
        QCStage(),
        MetadataStage(),
        MetricsStage(),
    ]
    skip_set = set(skip_stages or [])
    stages = [s for s in all_stages if s.name not in skip_set]
    return Pipeline(stages, verbose=True)


def run_step(name: str, func: Callable, severity: Severity, *args, **kwargs) -> StepResult:
    """Compatibility helper used by older `director` imports.

    Signature: run_step(name, callable, severity, *args, **kwargs)
    Returns a `StepResult` with appropriate severity mapping on exception.
    """
    try:
        output = func(*args, **kwargs)
        return StepResult.success(output=output)
    except Exception as e:
        notes = [str(e)]
        if severity == Severity.CRITICAL:
            return StepResult.critical(notes=notes)
        if severity == Severity.DEGRADED:
            return StepResult.degraded(notes=notes)
        return StepResult.optional(notes=notes)
