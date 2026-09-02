"""Runtime capability detection and bundled-model/tool manifest."""
from __future__ import annotations

import importlib.util
import os
import shutil
from typing import Any, Dict


def build_runtime_manifest() -> Dict[str, Any]:
    def module_available(name: str) -> bool:
        return importlib.util.find_spec(name) is not None

    model = os.environ.get("EDIT_FACTORY_MOBILENET_MODEL", ".models/mobilenet_ssd/mobilenet.caffemodel")
    config = os.environ.get("EDIT_FACTORY_MOBILENET_CONFIG", ".models/mobilenet_ssd/deploy.prototxt")
    ffmpeg = shutil.which("ffmpeg") or shutil.which(os.path.join(".tools", "ffmpeg", "bin", "ffmpeg"))
    ffprobe = shutil.which("ffprobe")

    return {
        "ffmpeg": {"available": bool(ffmpeg), "path": ffmpeg},
        "ffprobe": {"available": bool(ffprobe), "path": ffprobe},
        "models": {
            "mobilenet_ssd": {
                "available": os.path.exists(model) and os.path.exists(config),
                "model_path": model,
                "config_path": config,
            }
        },
        "python": {
            "opencv": module_available("cv2"),
            "pytesseract": module_available("pytesseract"),
            "librosa": module_available("librosa"),
            "pyannote_audio": module_available("pyannote.audio"),
            "edge_tts": module_available("edge_tts"),
        },
        "environment": {
            "huggingface_token": bool(os.environ.get("HUGGINGFACE_TOKEN") or os.environ.get("PYANNOTE_AUTH_TOKEN")),
            "openai_key": bool(os.environ.get("OPENAI_API_KEY")),
            "groq_key": bool(os.environ.get("GROQ_API_KEY")),
            "elevenlabs_key": bool(os.environ.get("ELEVENLABS_API_KEY")),
        },
    }
