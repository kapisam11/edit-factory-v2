"""Music analysis, beat-sync editing, and audio mixing.

Detects BPM and beat positions from music tracks.
Aligns video cuts to beats.
Mixes music + voiceover with ducking (sidechain compression).

Requires: librosa (optional but recommended), numpy
"""
import json
import logging
import os
import shutil
from typing import List, Optional, Tuple

import numpy as np

from .render_engine import run_ffmpeg, run_ffprobe, validate_media_output

logger = logging.getLogger(__name__)

try:
    import librosa  # type: ignore
except Exception:
    librosa = None


def detect_music_beats(audio_path: str) -> Tuple[Optional[float], Optional[List[float]]]:
    """Detect BPM and beat timestamps from a music track.

    Returns (bpm, [beat_times]) or (None, None) if analysis fails.
    """
    if not librosa:
        logger.warning("librosa not installed; music beat detection unavailable")
        return None, None
    try:
        y, sr = librosa.load(audio_path, sr=None, mono=True, duration=120)
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
        beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        onset_frames = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr)
        onset_times = librosa.frames_to_time(onset_frames, sr=sr).tolist()
        all_impacts = sorted(set(beat_times + onset_times))
        return float(tempo), all_impacts
    except Exception as e:
        logger.warning("Music beat detection failed: %s", e)
    return None, None


def find_nearest_beat(time_sec: float, beats: List[float], tolerance: float = 0.3) -> Optional[float]:
    """Find the nearest beat to a given time, if within tolerance."""
    if not beats:
        return None
    nearest = min(beats, key=lambda b: abs(b - time_sec))
    if abs(nearest - time_sec) <= tolerance:
        return nearest
    return None


def align_segments_to_music(
    segments: List[Tuple[float, float]],
    beats: List[float],
    bpm: float,
) -> List[Tuple[float, float]]:
    """Snap segment boundaries to nearest music beats."""
    if not beats or not bpm:
        return segments

    aligned = []
    for s, e in segments:
        new_s = s
        prev_beats = [b for b in beats if b <= s]
        if prev_beats:
            candidate = max(prev_beats)
            if abs(candidate - s) < 0.25:
                new_s = candidate

        new_e = e
        local_beats = [b for b in beats if new_s < b <= e + 0.5]
        if local_beats:
            nearest = min(local_beats, key=lambda b: abs(b - e))
            if abs(nearest - e) < 0.35:
                new_e = nearest

        beat_dur = 60.0 / bpm
        if new_e - new_s < beat_dur * 0.5:
            new_e = new_s + beat_dur

        aligned.append((round(new_s, 3), round(new_e, 3)))
    return aligned


def _probe_duration(path: str) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe is required for music mixing")
    result = run_ffprobe([
        ffprobe, "-v", "error", "-show_entries", "format=duration",
        "-of", "json", path,
    ])
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path}: {result.stderr[-1000:]}")
    try:
        duration = float(json.loads(result.stdout)["format"]["duration"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"ffprobe returned no usable duration for {path}") from exc
    if duration <= 0:
        raise RuntimeError(f"Media has no positive duration: {path}")
    return duration


def mix_audio(
    video_path: str,
    music_path: str,
    vo_path: Optional[str],
    output_path: str,
    music_volume: float = 0.25,
    duck_db: float = -12.0,
) -> str:
    """Mix video + background music + optional voiceover with bounded FFmpeg execution."""
    if not os.path.exists(video_path):
        raise FileNotFoundError(video_path)
    if not os.path.exists(music_path):
        raise FileNotFoundError(music_path)
    if not 0.0 <= music_volume <= 1.0:
        raise ValueError("music_volume must be between 0 and 1")

    cmd = ["ffmpeg", "-y", "-i", video_path, "-i", music_path]
    filter_complex_parts = []
    music_gain = max(0.0, min(1.0, music_volume))
    filter_complex_parts.append(f"[1:a]volume={music_gain}[music]")

    if vo_path and os.path.exists(vo_path):
        cmd.extend(["-i", vo_path])
        duck_gain = 10 ** (float(duck_db) / 20.0)
        filter_complex_parts.append(
            "[music][2:a]sidechaincompress=threshold=0.02:ratio=4:attack=50:release=200:level_sc=1"
            "[music_ducked]"
        )
        filter_complex_parts.append(f"[music_ducked]volume={duck_gain}[ducked_gain]")
        filter_complex_parts.append(
            "[ducked_gain][2:a]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        )
    else:
        filter_complex_parts.append("[music]anull[aout]")

    cmd.extend([
        "-filter_complex", ";".join(filter_complex_parts),
        "-map", "0:v:0", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", output_path,
    ])

    logger.info("[MIX] Running music mix")
    run_ffmpeg(cmd)
    validate_media_output(output_path, require_video=True, require_audio=True)
    return output_path


def add_music_to_video(
    video_path: str,
    music_path: str,
    output_path: str,
    music_volume: float = 0.2,
    loop: bool = True,
) -> str:
    """Add background music to video, looping it when requested."""
    if not os.path.exists(video_path):
        raise FileNotFoundError(video_path)
    if not os.path.exists(music_path):
        raise FileNotFoundError(music_path)
    if not 0.0 <= music_volume <= 1.0:
        raise ValueError("music_volume must be between 0 and 1")

    vid_dur = _probe_duration(video_path)
    music_dur = _probe_duration(music_path)
    cmd = ["ffmpeg", "-y", "-i", video_path]
    if loop and music_dur < vid_dur:
        cmd.extend(["-stream_loop", "-1"])
    cmd.extend(["-i", music_path])

    vol = max(0.0, min(1.0, music_volume))
    fade_start = max(0.0, vid_dur - 2.0)
    filter_complex = (
        f"[1:a]volume={vol},afade=t=out:st={fade_start}:d=2[music];"
        "[0:a][music]amix=inputs=2:duration=first:dropout_transition=2[aout]"
    )
    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", "0:v:0", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", output_path,
    ])

    logger.info("[MIX] Adding background music")
    run_ffmpeg(cmd)
    validate_media_output(output_path, require_video=True, require_audio=True)
    return output_path
