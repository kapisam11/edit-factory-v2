"""Safe ffmpeg execution, concat, subtitle burn, and hardware encoding."""
import logging
import os
import shutil
import subprocess
from typing import List

from .hardware import choose_encoder, ffmpeg_preset_for

logger = logging.getLogger(__name__)


def _ensure_dir(p: str) -> None:
    os.makedirs(p, exist_ok=True)


def run_ffmpeg(cmd: List[str]) -> None:
    logger.info("RUN: %s", " ".join(cmd))
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError as exc:
        raise RuntimeError("FFmpeg is not installed or not available on PATH") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"FFmpeg failed with exit code {exc.returncode}") from exc


def render_segment(src_clip: str, ss: float, duration: float, vf: str, dst: str) -> None:
    if not os.path.isfile(src_clip):
        raise FileNotFoundError(f"Source clip not found: {src_clip}")
    if duration <= 0:
        raise ValueError("Segment duration must be positive")

    encoder = choose_encoder()
    if encoder in ("h264_nvenc", "hevc_nvenc"):
        codec = encoder
        extra = ["-preset", "p5", "-rc", "vbr_hq", "-b:v", "6000k"]
    else:
        codec = "libx264"
        extra = ["-preset", "fast", "-crf", "23"]

    _ensure_dir(os.path.dirname(dst) or ".")
    cmd = [
        "ffmpeg", "-y", "-ss", str(ss), "-t", str(duration), "-i", src_clip,
        "-vf", vf,
        "-c:v", codec, *extra,
        "-c:a", "aac", "-b:a", "128k",
        dst,
    ]
    run_ffmpeg(cmd)
    if not os.path.isfile(dst) or os.path.getsize(dst) == 0:
        raise RuntimeError(f"FFmpeg reported success but produced no output: {dst}")


def write_concat_list(seq_files: List[str], concat_list_path: str) -> None:
    if not seq_files:
        raise ValueError("Cannot create a concat list from an empty sequence")
    with open(concat_list_path, "w", encoding="utf-8") as f:
        for p in seq_files:
            safe_path = os.path.abspath(p).replace("'", "'\\''")
            f.write(f"file '{safe_path}'\n")


def concat_segments(concat_list_path: str, output_path: str, encoder: str = "libx264") -> None:
    if not os.path.isfile(concat_list_path):
        raise FileNotFoundError(concat_list_path)
    preset = ffmpeg_preset_for(encoder)
    codec = preset.get("codec", "libx264")
    if "h264_nvenc" in codec or "hevc_nvenc" in codec:
        opts = ["-preset", preset.get("preset", "p5"), "-rc", preset.get("rc", "vbr_hq"), "-b:v", preset.get("bitrate", "6000k")]
    else:
        opts = ["-preset", preset.get("preset", "slow"), "-crf", preset.get("crf", "20")]

    _ensure_dir(os.path.dirname(output_path) or ".")
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_list_path,
        "-c:v", codec, *opts,
        "-c:a", "aac",
        "-movflags", "+faststart",
        output_path,
    ]
    run_ffmpeg(cmd)
    if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
        raise RuntimeError(f"Concatenation produced no output: {output_path}")


def burn_subtitles(video_path: str, srt_path: str, output_path: str) -> None:
    if not os.path.isfile(video_path):
        raise FileNotFoundError(video_path)
    if not os.path.isfile(srt_path):
        raise FileNotFoundError(srt_path)

    _ensure_dir(os.path.dirname(output_path) or ".")
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", f"subtitles={srt_path!r}",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "copy",
        "-movflags", "+faststart",
        output_path,
    ]
    run_ffmpeg(cmd)
    if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
        raise RuntimeError(f"Subtitle burn produced no output: {output_path}")


def mix_voiceover(video_path: str, vo_path: str, output_path: str) -> None:
    for path in (video_path, vo_path):
        if not os.path.isfile(path):
            raise FileNotFoundError(path)
    _ensure_dir(os.path.dirname(output_path) or ".")
    cmd = [
        "ffmpeg", "-y", "-i", video_path, "-i", vo_path,
        "-c:v", "copy", "-c:a", "aac",
        "-map", "0:v:0", "-map", "1:a:0", "-shortest",
        output_path,
    ]
    run_ffmpeg(cmd)
    if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
        raise RuntimeError(f"Voiceover mix produced no output: {output_path}")
