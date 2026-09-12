import shutil
import subprocess

import pytest

from ai_video_factory.music_mixer import add_music_to_video, mix_audio


@pytest.mark.integration
def test_music_mix_paths_produce_valid_audio_video(tmp_path):
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("ffmpeg/ffprobe are required for music integration tests")

    video = tmp_path / "video.mp4"
    music = tmp_path / "music.wav"
    vo = tmp_path / "voice.wav"
    mixed = tmp_path / "mixed.mp4"
    simple = tmp_path / "simple.mp4"

    subprocess.run(
        [ffmpeg, "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=24",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
         "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(video)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for target, frequency in ((music, "880"), (vo, "220")):
        subprocess.run(
            [ffmpeg, "-y", "-f", "lavfi", "-i", f"sine=frequency={frequency}:sample_rate=48000",
             "-t", "1.5", "-c:a", "pcm_s16le", str(target)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    mix_audio(str(video), str(music), str(vo), str(mixed))
    add_music_to_video(str(video), str(music), str(simple), loop=True)

    for output in (mixed, simple):
        probe = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "stream=codec_type",
             "-of", "csv=p=0", str(output)],
            check=True, capture_output=True, text=True,
        )
        stream_types = set(probe.stdout.splitlines())
        assert "video" in stream_types
        assert "audio" in stream_types
