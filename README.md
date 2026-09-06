# AI Video Factory / Edit Factory v2

Generate research-backed short video packages with auto-edit support.

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\Activate.ps1 on Windows
python -m pip install -e ".[web,dev]"

# Canonical installed CLI
aivf --help

# Compatibility/script CLI
python cli.py "Minecraft betrayal on SMP"

# Auto-edit from raw footage
python cli.py "Minecraft betrayal on SMP" --input-video recording.mp4 --auto-edit
```

## Supported interfaces

| Interface | Purpose |
|---|---|
| `aivf` / `cli.py` | Canonical packaged CLI |
| `cli_v2.py` | Deprecated compatibility CLI; retained for existing scripts |
| `wsgi.py` | Production Flask/Gunicorn dashboard entry point |

The `archive/` directory contains historical code and is not part of the supported runtime path.

## Dashboard

Run one Gunicorn worker because dashboard job-process bookkeeping is intentionally process-local:

```bash
gunicorn --workers 1 --bind 0.0.0.0:5000 --timeout 0 wsgi:app
```

Set `FLASK_SECRET_KEY` and `AIVF_DASHBOARD_TOKEN`. For HTTPS set `AIVF_COOKIE_SECURE=1`.
`AIVF_ALLOW_INSECURE_LOCAL=1` is for local development only.

## Architecture

```text
Browser
  |
  v
Gunicorn (1 worker)
  |
  +--> Flask dashboard/API
  |      +--> SQLite (WAL + busy timeout)
  |      +--> in-memory process registry
  |
  +--> spawned job process
          +--> pipeline
          +--> FFmpeg / FFprobe
          +--> package output
```

Runtime API credentials stay in process memory and are never stored in job records or logs.
Uploads are UUID-backed, extension-checked, and FFprobe-validated. Package paths are slugged and
contained under the output root.

## Optional features

- Groq enrichment: `GROQ_API_KEY` with the relevant workflow flag
- ElevenLabs voiceover: `ELEVENLABS_API_KEY`
- Beat sync: `librosa`
- Vision/OCR/diarization: enable the corresponding extras in `pyproject.toml`

## Requirements

- Python 3.9+
- FFmpeg and FFprobe on PATH
- Optional GPU for accelerated encoding

See `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md`, and `docs/RELEASE_CHECKLIST.md` before production deployment.
