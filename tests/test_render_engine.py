import pytest

from ai_video_factory import render_engine


def test_validate_media_output_rejects_missing(tmp_path):
    with pytest.raises(RuntimeError):
        render_engine.validate_media_output(str(tmp_path / "missing.mp4"))


def test_write_concat_list_escapes_apostrophes(tmp_path):
    path = tmp_path / "list.txt"
    render_engine.write_concat_list(["/tmp/a file's clip.mp4"], str(path))
    text = path.read_text(encoding="utf-8")
    assert "a file" in text
    assert "'\\''" in text


def test_run_ffmpeg_rejects_non_ffmpeg_command():
    with pytest.raises(ValueError):
        render_engine.run_ffmpeg(["echo", "hello"])
