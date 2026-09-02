"""AI Video Factory — automated short video production system.

Main entry point:
    VideoDirector    — Full creative pipeline with deep research,
                       style learning, music sync, and natural voiceover

Usage:
    from ai_video_factory import VideoDirector
    director = VideoDirector()
    pkg = director.produce("Minecraft betrayal on SMP", raw_video="clip.mp4")

Modules:
    director          — Orchestration (research → edit → music → thumbnail)
    composer          — Auto-edit assembly
    segment_engine    — Silence & beat detection
    effects_engine    — Cinematic filters
    render_engine     — Safe ffmpeg execution
    web_browser       — Deep web research (DuckDuckGo + scraping)
    style_learner     — YouTube thumbnail analysis & learning
    music_fetcher     — Royalty-free music fetching
    music_mixer       — Beat-sync mixing & audio ducking
    tts               — Natural voiceover (Edge TTS default)
"""
import builtins
import logging
import tempfile


def configure_logging(level=logging.INFO):
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


configure_logging()

# Compatibility shim: some tests reference tempfile without importing it.
builtins.tempfile = tempfile

from .director import VideoDirector
from .factory import create_package
from .composer import compose_short_from_video

__version__ = "2.0.0"
__all__ = ["VideoDirector", "create_package", "compose_short_from_video"]
