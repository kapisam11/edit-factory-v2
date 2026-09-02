import os


def generate_aspect_variants(input_video: str, srt_path: str, out_dir: str):
    """
    Generate vertical, square, and landscape variants with subtitles burned in.

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
        cmd = rf'ffmpeg -y -i "{input_video}" -vf "scale=w=min({w}\,iw):h=min({h}\,ih),pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,subtitles=\"{srt_path}\"" -c:v libx264 -c:a aac -b:a 128k "{out}"'
        try:
            import subprocess

            subprocess.check_call(cmd, shell=True)
            variants.append(out)
        except Exception:
            # skip on error
            pass
    return variants
