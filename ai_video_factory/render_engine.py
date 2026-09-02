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
    subprocess.run(cmd, check=True)


def render_segment(src_clip: str, ss: float, duration: float, vf: str, dst: str) -> None:
    encoder = choose_encoder()
    if encoder in ("h264_nvenc", "hevc_nvenc"):
        codec = encoder
        preset = "p5"
        extra = ["-preset", preset, "-rc", "vbr_hq", "-b:v", "6000k"]
    else:
        codec = "libx264"
        extra = ["-preset", "fast", "-crf", "23"]

    cmd = [
        "ffmpeg", "-y", "-i", src_clip,
        "-ss", str(ss), "-t", str(duration),
        "-vf", vf,
        "-c:v", codec, *extra,
        "-c:a", "aac", "-b:a", "128k",
        dst,
    ]
    run_ffmpeg(cmd)


def write_concat_list(seq_files: List[str], concat_list_path: str) -> None:
    with open(concat_list_path, "w", encoding="utf-8") as f:
        for p in seq_files:
            safe_path = p.replace("'", "'\''")
            f.write(f"file '{safe_path}'\n")


def concat_segments(concat_list_path: str, output_path: str, encoder: str = "libx264") -> None:
    preset = ffmpeg_preset_for(encoder)
    codec = preset.get("codec", "libx264")
    opts = []
    if "h264_nvenc" in codec or "hevc_nvenc" in codec:
        opts = ["-preset", preset.get("preset", "p5"), "-rc", preset.get("rc", "vbr_hq"), "-b:v", preset.get("bitrate", "6000k")]
    else:
        opts = ["-preset", preset.get("preset", "slow"), "-crf", preset.get("crf", "20")]

    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_list_path,
        "-c:v", codec, *opts,
        "-c:a", "aac",
        "-movflags", "+faststart",
        output_path,
    ]
    run_ffmpeg(cmd)


def burn_subtitles(video_path: str, srt_path: str, output_path: str) -> None:
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", f"subtitles='{srt_path}'",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "copy",
        "-movflags", "+faststart",
        output_path,
    ]
    try:
        run_ffmpeg(cmd)
    except Exception as e:
        logger.error("Subtitle burn failed (%s), using video without subs", e)
        shutil.copy2(video_path, output_path)


def mix_voiceover(video_path: str, vo_path: str, output_path: str) -> None:
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", vo_path,
        "-c:v", "copy",
        "-c:a", "aac",
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-shortest",
        output_path,
    ]
    run_ffmpeg(cmd)