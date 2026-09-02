"""AI Video Factory — automated short video production system.

Main entry points:
    VideoDirector              — legacy/full director orchestration
    run_production_pipeline    — footage-aware production path
    compose_short_from_video   — low-level composition helper
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

# Compatibility shim retained for the existing test suite.
builtins.tempfile = tempfile

from .director import VideoDirector
from .factory import create_package
from .composer import compose_short_from_video
from .production_pipeline import run_production_pipeline
from .production_models import EditTimeline, Scene, TimelineSegment

__version__ = "2.1.0"
__all__ = [
    "VideoDirector",
    "create_package",
    "compose_short_from_video",
    "run_production_pipeline",
    "Scene",
    "TimelineSegment",
    "EditTimeline",
]
