# AI Video Factory v2

Generate research-backed short-video packages with automated planning, script generation, thumbnails, optional auto-editing, voiceover, music, QC, metadata, and learning feedback.

## Requirements

- Python 3.9+
- FFmpeg on PATH for video rendering
- Optional API keys for external AI providers

## Install

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[web,dev]"
```

For beat detection, install the optional `beats` extra. For Groq or ElevenLabs integrations, install their corresponding extras.

## CLI

The main entry point is `cli.py`:

```bash
python cli.py "Minecraft betrayal on SMP"
python cli.py "Minecraft betrayal on SMP" --raw-video gameplay.mp4 --director
python cli.py "COD clutch" --raw-video clip.mp4 --pipeline fast
python cli.py "Minecraft" --pipeline package_only
```

Available pipelines are `default`, `fast`, and `package_only`. `--director` is an alias for the full `default` pipeline.

## Web dashboard

The dashboard is intentionally locked down. Before starting it, configure both values:

```bash
export FLASK_SECRET_KEY="use-a-long-random-secret"
export AIVF_ADMIN_PASSWORD="use-a-strong-password"
```

On Windows PowerShell:

```powershell
$env:FLASK_SECRET_KEY = "use-a-long-random-secret"
$env:AIVF_ADMIN_PASSWORD = "use-a-strong-password"
```

For local development:

```bash
python web_app_v2.py
```

For production on a Unix-like host, use a production WSGI server such as Gunicorn rather than Flask's development server:

```bash
gunicorn -w 2 -b 0.0.0.0:5000 web_app_v2:app
```

Enable secure session cookies behind HTTPS with:

```bash
export AIVF_COOKIE_SECURE=1
```

Uploaded videos are stored under generated UUID filenames. Package files are served only from the output directory. Dashboard settings never return API secrets; keys supplied through the dashboard are kept in the running process environment.

## Architecture

```text
cli.py / web_app_v2.py
        |
        v
  PipelineContext
        |
        +--> research
        +--> plan
        +--> script
        +--> thumbnail
        +--> auto_edit
        +--> voiceover
        +--> music
        +--> quality_control
        +--> metadata
        +--> metrics
```

The pipeline records stage status, elapsed time, errors and warnings. Optional stages degrade gracefully; required failures are surfaced.

## Project layout

| Path | Purpose |
| --- | --- |
| `cli.py` | Primary command-line entry point |
| `web_app_v2.py` | Authenticated browser dashboard/API |
| `ai_video_factory/` | Core production package |
| `tools/` | Hook, reporting and utility tools |
| `tests/` | Unit and regression tests |
| `.github/workflows/python-tests.yml` | CI: install, dependency check, compile, lint and tests |

Generated media, uploads, local databases, `.env` files and local config overrides are ignored by Git.

## Quality and CI

The CI workflow runs package installation, `pip check`, Python compilation, Ruff and the complete pytest suite. Integration tests that need real media/tooling can be marked with the `integration` pytest marker.

## Large runtime assets

The repository includes project runtime assets such as FFmpeg/model files for convenience. For a distribution-focused deployment, move those large binaries to release assets or Git LFS rather than growing the Git history with repeated binary revisions.
