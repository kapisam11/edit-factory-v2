"""Subtitle generation and multi-aspect render helpers."""

import os
import textwrap
from typing import List


def _fmt_time(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int(round((t - int(t)) * 1000))
    if ms >= 1000:
        s += 1
        ms -= 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def script_to_srt(
    script: str,
    out_path: str,
    avg_words_per_second: float = 2.5,
) -> str:
    """Convert a script into a simple sequentially-timed SRT file.

    Timing is estimated from word count and is intended as a lightweight
    fallback when transcript-aligned timings are not available.
    """
    if avg_words_per_second <= 0:
        raise ValueError("avg_words_per_second must be greater than zero")

    lines = [line.strip() for line in script.splitlines() if line.strip()]
    subs = []
    time_cursor = 0.0
    idx = 1

    for line in lines:
        for wrapped in textwrap.wrap(line, width=24) or [line]:
            word_count = len(wrapped.split())
            duration = max(0.8, word_count / avg_words_per_second)
            start = time_cursor
            end = time_cursor + duration
            subs.append((idx, start, end, wrapped))
            idx += 1
            time_cursor = end

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as handle:
        for sub_idx, start, end, text in subs:
            handle.write(f"{sub_idx}\n")
            handle.write(f"{_fmt_time(start)} --> {_fmt_time(end)}\n")
            handle.write(f"{text}\n\n")

    return out_path


def generate_aspect_variants(input_video: str, srt_path: str, out_dir: str) -> List[str]:
    """Generate vertical, square, and landscape variants with burned-in subtitles.

    Requires ffmpeg in PATH. A failed individual variant is skipped so one
    unsupported render does not prevent the remaining variants from completing.
    """
    os.makedirs(out_dir, exist_ok=True)
    variants: List[str] = []
    specs = [
        (1080, 1920, "vertical_9_16.mp4"),
        (1080, 1080, "square_1_1.mp4"),
        (1920, 1080, "landscape_16_9.mp4"),
    ]

    for width, height, name in specs:
        out = os.path.join(out_dir, name)
        cmd = (
            'ffmpeg -y -i "{input_video}" '
            '-vf "scale=w=min({width}\\,iw):h=min({height}\\,ih),'
            'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,'
            'subtitles=\\"{srt_path}\\"" '
            '-c:v libx264 -c:a aac -b:a 128k "{out}"'
        ).format(
            input_video=input_video,
            width=width,
            height=height,
            srt_path=srt_path,
            out=out,
        )
        try:
            import subprocess

            subprocess.check_call(cmd, shell=True)
            variants.append(out)
        except Exception:
            continue

    return variants


# Backwards-compatible public name used by older callers.
def render_variants(input_video: str, srt_path: str, out_dir: str) -> List[str]:
    return generate_aspect_variants(input_video, srt_path, out_dir)
