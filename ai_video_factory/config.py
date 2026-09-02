"""AI Video Factory — Real Configuration System.

Expands the tiny aivf_config.schema.json into a full-featured config manager
with profiles, pipelines, style presets, and hardware settings.
"""
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class StyleProfile:
    name: str
    cuts_per_minute: float = 15.0
    zoom_intensity: float = 1.04
    avg_shot_seconds: float = 1.8
    hook_placement_seconds: float = 0.4
    preferred_filters: List[str] = field(default_factory=list)
    music_mood: str = "dramatic"
    subtitle_style: str = "bold_white"
    thumbnail_style: str = "high_contrast"
    note: str = ""


@dataclass
class PipelineConfig:
    name: str
    stages: List[str] = field(default_factory=lambda: [
        "research", "plan", "script", "thumbnail", "auto_edit",
        "voiceover", "music", "qc", "metadata", "metrics"
    ])
    description: str = ""


@dataclass
class HardwareConfig:
    encoder: str = "libx264"  # libx264, h264_nvenc, hevc_nvenc, etc.
    gpu_memory_mb: int = 0
    max_parallel_jobs: int = 2
    use_gpu_for_filters: bool = False


@dataclass
class APIKeys:
    groq: str = ""
    elevenlabs: str = ""
    openai: str = ""
    freesound: str = ""


@dataclass
class AIVFConfig:
    version: str = "2.0"
    active_pipeline: str = "default"
    active_style: str = "gaming_fast"
    output_root: str = "output"
    upload_root: str = "uploads"
    asset_root: str = "assets"
    templates_root: str = "templates"
    knowledge_root: str = "knowledge_base_v2"

    pipelines: Dict[str, PipelineConfig] = field(default_factory=lambda: {
        "default": PipelineConfig("default", description="Full pipeline with everything"),
        "fast": PipelineConfig("fast", stages=["plan", "script", "auto_edit", "metadata"],
                               description="Skip research and extras for speed"),
        "package_only": PipelineConfig("package_only", stages=["research", "plan", "script", "thumbnail", "metadata"],
                                       description="Generate plan + script, no video editing"),
    })

    style_profiles: Dict[str, StyleProfile] = field(default_factory=lambda: {
        "gaming_fast": StyleProfile(
            name="gaming_fast",
            cuts_per_minute=20.0,
            zoom_intensity=1.1,
            avg_shot_seconds=1.5,
            preferred_filters=["jump_cut", "impact_frame", "speed_ramp"],
            music_mood="intense",
            subtitle_style="bold_yellow",
            thumbnail_style="high_contrast",
            note="Fast-paced gaming content (Fortnite, COD, Valorant)",
        ),
        "gaming_cinematic": StyleProfile(
            name="gaming_cinematic",
            cuts_per_minute=8.0,
            zoom_intensity=1.04,
            avg_shot_seconds=2.5,
            preferred_filters=["cinematic_transition", "soft_settle", "camera_move"],
            music_mood="emotional",
            subtitle_style="elegant_white",
            thumbnail_style="cinematic",
            note="Slow, story-driven gaming content (Minecraft SMP, RP)",
        ),
        "tutorial": StyleProfile(
            name="tutorial",
            cuts_per_minute=10.0,
            zoom_intensity=1.02,
            avg_shot_seconds=2.0,
            preferred_filters=["zoom", "cinematic_transition"],
            music_mood="calm",
            subtitle_style="clear_white",
            thumbnail_style="clean_text",
            note="Educational / how-to content",
        ),
    })

    hardware: HardwareConfig = field(default_factory=HardwareConfig)
    api_keys: APIKeys = field(default_factory=APIKeys)
    heuristics: Dict[str, Any] = field(default_factory=lambda: {
        "viral_length_range": [30, 60],
        "optimal_length_seconds": 42,
        "cuts_per_minute": 15.0,
        "avg_shot_seconds": 1.8,
        "hook_placement_seconds": [0.3, 0.5],
        "climax_position_pct": [0.60, 0.75],
        "note": "Default heuristics. Tune for your niche via config or feedback.",
    })

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self, path: str = "aivf_config.json"):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: str = "aivf_config.json") -> "AIVFConfig":
        if not os.path.exists(path):
            config = cls()
            config.save(path)
            return config
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(**data)

    def get_pipeline(self, name: Optional[str] = None) -> PipelineConfig:
        return self.pipelines.get(name or self.active_pipeline, self.pipelines["default"])

    def get_style(self, name: Optional[str] = None) -> StyleProfile:
        return self.style_profiles.get(name or self.active_style, self.style_profiles["gaming_fast"])

    def set_api_key(self, provider: str, key: str):
        """Set API key and also export to env for capability registry."""
        if provider == "groq":
            self.api_keys.groq = key
            os.environ["GROQ_API_KEY"] = key
        elif provider == "elevenlabs":
            self.api_keys.elevenlabs = key
            os.environ["ELEVENLABS_API_KEY"] = key
        elif provider == "openai":
            self.api_keys.openai = key
            os.environ["OPENAI_API_KEY"] = key
        elif provider == "freesound":
            self.api_keys.freesound = key
            os.environ["FREESOUND_API_KEY"] = key

    def apply_heuristics(self, heuristics: Dict[str, Any]):
        """Update heuristics and save."""
        self.heuristics.update(heuristics)
        self.save()
