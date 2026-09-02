"""Subtitle generation and multi-aspect render helpers."""
import textwrap
import os
from typing import List


def script_to_srt(script: str, out_path: str, avg_words_per_second: float = 2.5) -> str:
    """Convert a script string into a simple SRT file with estimated timings.

    This heuristic assigns sequential timestamps based on word counts.
    """
    lines = [l.strip() for l in script.splitlines() if l.strip()]
    subs = []
    time_cursor = 0.0
    idx = 1
    for line in lines:
        # split into 2-6 words lines
        words = line.split()
        wrapped = textwrap.wrap(line, width=24)
        for w in wrapped:
            wc = len(w.split())
            duration = max(0.8, wc / avg_words_per_second)
            start = time_cursor
            end = time_cursor + duration
            subs.append((idx, start, end, w))
            idx += 1
            time_cursor = end

    # write SRT
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for idx, start, end, text in subs:
            f.write(f"{idx}\n")
            f.write(f"{_fmt_time(start)} --> {_fmt_time(end)}\n")
            f.write(f"{text}\n\n")

    return out_path


def _fmt_time(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int((t - int(t)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def render_variants(input_video: str, srt_path: str, out_dir: str) -> List[str]:
    """Create multi-aspect renders (9:16, 1:1, 16:9) with burned-in subtitles using ffmpeg.

    Returns list of generated file paths. Requires ffmpeg in PATH.
    """
    os.makedirs(out_dir, exist_ok=True)
    variants = []
    specs = [
        (1080, 1920, "vertical_9_16.mp4"),
        (1080, 1080, "square_1_1.mp4"),
        (1920, 1080, "landscape_16_9.mp4"),
    ]
    for w, h, name in specs:
        out = os.path.join(out_dir, name)
        # scale and pad to fit target, burn subtitles
        cmd = f'ffmpeg -y -i "{input_video}" -vf "scale=w=min({w}\,iw):h=min({h}\,ih),pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,subtitles=\"{srt_path}\"" -c:v libx264 -c:a aac -b:a 128k "{out}"'
        try:
            import subprocess

            subprocess.check_call(cmd, shell=True)
            variants.append(out)
        except Exception:
            # skip on error
            continue

    return variants
