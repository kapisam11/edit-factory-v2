"""AI Video Factory — Pipeline Stage System.

Discrete, testable, swappable pipeline stages. Each stage receives a
PipelineContext and returns a modified context.
"""
import json
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from enum import Enum


class Severity(Enum):
    """Severity levels used by the compatibility step-result API."""
    CRITICAL = "critical"
    DEGRADED = "degraded"
    OPTIONAL = "optional"


@dataclass
class StepResult:
    ok: bool
    output: Any = None
    severity: Severity = Severity.DEGRADED
    notes: Optional[List[str]] = None

    def __post_init__(self) -> None:
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
    def __init__(self, result: StepResult, step_name: str = "") -> None:
        self.result = result
        self.step_name = step_name
        super().__init__(f"Pipeline step '{step_name}' failed: {result.notes}")


class PipelineManifest:
    def __init__(self, topic: str, target_seconds: float = 45.0) -> None:
        self.topic = topic
        self.target_seconds = target_seconds
        self.steps: Dict[str, StepResult] = {}
        self.degraded = False
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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "topic": self.topic,
            "target_seconds": self.target_seconds,
            "steps": {
                name: {
                    "ok": result.ok,
                    "output": result.output,
                    "severity": result.severity.value,
                    "notes": result.notes or [],
                }
                for name, result in self.steps.items()
            },
            "degraded": self.degraded,
            "critical_failure": self.critical_failure,
            "artifacts": self.artifacts,
        }


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
        return json.dumps(
            {k: v for k, v in self.__dict__.items() if k not in ("model_key", "groq_key")},
            indent=2,
            default=str,
        )


class PipelineStage(ABC):
    """Base class for all pipeline stages."""
    name = "stage"
    skippable = False
    retryable = True
    max_retries = 1

    @abstractmethod
    def run(self, ctx: PipelineContext) -> PipelineContext:
        ...

    def on_error(self, ctx: PipelineContext, error: Exception) -> PipelineContext:
        ctx.errors.append(f"[{self.name}] {error}")
        if not self.skippable:
            raise error
        ctx.warnings.append(f"[{self.name}] Skipped due to error: {error}")
        return ctx


class Pipeline:
    """Orchestrates stages in order with error handling and retries."""
    def __init__(self, stages: List[PipelineStage], verbose: bool = True) -> None:
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
            last_error: Optional[Exception] = None
            while attempts <= stage.max_retries and not success:
                try:
                    ctx = stage.run(ctx)
                    success = True
                except Exception as exc:
                    last_error = exc
                    attempts += 1
                    if attempts <= stage.max_retries:
                        time.sleep(0.5 * attempts)
            if not success and last_error is not None:
                ctx = stage.on_error(ctx, last_error)
            elapsed = time.time() - start
            self._stage_times[stage.name] = elapsed
            if self.verbose:
                status = "✓" if success else ("⚠ skipped" if stage.skippable else "✗ FAILED")
                print(f"[PIPELINE]   {status} {stage.name} ({elapsed:.2f}s)")

        if ctx.package_dir:
            report_path = os.path.join(ctx.package_dir, "pipeline_report.json")
            with open(report_path, "w", encoding="utf-8") as handle:
                json.dump({
                    "stages": [stage.name for stage in self.stages],
                    "stage_times": self._stage_times,
                    "errors": ctx.errors,
                    "warnings": ctx.warnings,
                    "completed_at": datetime.now().isoformat(),
                }, handle, indent=2)
        return ctx

    def get_report(self) -> Dict[str, Any]:
        return {"stages": [stage.name for stage in self.stages], "stage_times": self._stage_times}


class ResearchStage(PipelineStage):
    name = "research"
    skippable = True

    def run(self, ctx: PipelineContext) -> PipelineContext:
        from .capability_registry import build_default_registry
        result = build_default_registry().call("research", query=ctx.topic)
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
        summary = ctx.research or {"title": ctx.topic, "topic": ctx.topic}
        ctx.plan = make_idea(summary)
        ctx.edit_plan = ctx.plan.get("edit_plan", [])
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
        ctx.final_video = compose_short_from_video(
            ctx.raw_video,
            ctx.package_dir,
            review=not ctx.skip_qc,
            auto_fix=True,
            model_key=ctx.model_key,
            skip_qc=ctx.skip_qc,
        )
        return ctx


class VoiceoverStage(PipelineStage):
    name = "voiceover"
    skippable = True

    def run(self, ctx: PipelineContext) -> PipelineContext:
        if not ctx.script:
            return ctx
        from .capability_registry import build_default_registry
        path = os.path.join(ctx.package_dir, "voiceover.mp3") if ctx.package_dir else "voiceover.mp3"
        result = build_default_registry().call("tts", text=ctx.script, output_path=path)
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
        path = os.path.join(ctx.package_dir, "music_track.mp3") if ctx.package_dir else "music_track.mp3"
        result = build_default_registry().call("music", emotion=ctx.plan.get("mood", "dramatic"), output_path=path)
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
            with open(os.path.join(ctx.package_dir, "metadata.json"), "w", encoding="utf-8") as handle:
                json.dump(ctx.metadata, handle, indent=2)
        return ctx


class MetricsStage(PipelineStage):
    name = "metrics"
    skippable = True

    def run(self, ctx: PipelineContext) -> PipelineContext:
        ctx.metrics = {
            "filter_count": len(ctx.edit_plan),
            "avg_shot_duration": sum(s.get("duration", 0) for s in ctx.edit_plan) / max(len(ctx.edit_plan), 1),
            "cuts_per_minute": len(ctx.edit_plan) / (ctx.target_seconds / 60.0),
            "has_voiceover": ctx.voiceover is not None,
            "has_music": ctx.music_track is not None,
            "render_time_seconds": 0.0,
        }
        if ctx.package_dir:
            with open(os.path.join(ctx.package_dir, "metrics.json"), "w", encoding="utf-8") as handle:
                json.dump(ctx.metrics, handle, indent=2)
        return ctx


def build_director_pipeline(skip_stages: Optional[List[str]] = None) -> Pipeline:
    """Build the standard director pipeline."""
    all_stages = [
        ResearchStage(), PlanStage(), ScriptStage(), ThumbnailStage(),
        AutoEditStage(), VoiceoverStage(), MusicStage(), QCStage(),
        MetadataStage(), MetricsStage(),
    ]
    skip_set = set(skip_stages or [])
    return Pipeline([stage for stage in all_stages if stage.name not in skip_set], verbose=True)


def run_step(name: str, func: Callable, severity: Severity, *args, **kwargs) -> StepResult:
    """Compatibility helper used by older director imports."""
    try:
        return StepResult.success(output=func(*args, **kwargs))
    except Exception as exc:
        notes = [str(exc)]
        if severity == Severity.CRITICAL:
            return StepResult.critical(notes=notes)
        if severity == Severity.DEGRADED:
            return StepResult.degraded(notes=notes)
        return StepResult.optional(notes=notes)
