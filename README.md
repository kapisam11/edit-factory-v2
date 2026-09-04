# AI Video Factory

Generate research-backed short-video packages with AI planning and auto-edit support.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# Generate a package
python cli.py "Minecraft betrayal on SMP"

# Auto-edit raw footage
python cli.py "Minecraft betrayal on SMP" --input-video recording.mp4 --auto-edit
```

Python **3.10–3.12** is the supported/tested range. FFmpeg must be available on `PATH` for media rendering.

## Entry points

| Entry point | Purpose |
|---|---|
| `cli.py` | Main CLI for package generation, auto-editing, batch jobs, progress and ETA |
| `web_app_v2.py` | Production Flask dashboard controller |
| `wsgi.py` | WSGI entry point for Gunicorn/Linux deployments |
| `worker.py` | Isolated dashboard job process; safe for Windows `spawn` |
| `tools/apply_polish.py` | Polish an existing package |
| `tools/build_dashboard.py` | Build an HTML review dashboard |
| `tools/regenerate_visual_hooks.py` | Re-score visual hooks across packages |

## Architecture

The current application separates HTTP/state management from video execution:

```text
CLI ───────────────┐
                   ├── ai_video_factory/ ── pipeline stages ── FFmpeg/media tools
Flask dashboard ──┘
        │
        └── worker.py (one OS process per dashboard job)
                │
                └── SQLite job state + progress/log updates
```

The dashboard uses SQLite WAL mode and a busy timeout. Jobs have explicit lifecycle states and running jobs are marked `interrupted` after a restart. Dashboard workers are terminated at the OS-process level for real cancellation.

The current web deployment intentionally uses **one Gunicorn/web worker**. A shared job queue (Redis/Celery/RQ/etc.) should be introduced before enabling multiple web workers.

## Security and runtime behavior

Uploads are checked by filename extension, media signatures and `ffprobe` when available. Dashboard API keys are process-lifetime secrets and are not intended to be stored in SQLite job state. Mutating browser requests are expected to be same-origin. Production deployments should provide a strong `FLASK_SECRET_KEY` and an admin password for administrative operations.

Runtime assets such as FFmpeg binaries, model weights, generated media, uploads and knowledge data are not source-controlled application dependencies.

## Optional features

- **Groq enrichment:** configure `GROQ_API_KEY`, then use `--use-groq`.
- **ElevenLabs voiceover:** configure `ELEVENLABS_API_KEY` or pass the supported CLI option.
- **Beat sync:** install the `beats` extra (`pip install -e '.[beats]'`).
- **Vision/OCR/diarization:** install the corresponding optional extras from `pyproject.toml`.
- **Batch mode:** provide CSV or JSON input through the CLI batch options.

## Testing

CI tests Python 3.10, 3.11 and 3.12, runs linting, coverage tests, a Windows-style `multiprocessing spawn` smoke test, a real FFmpeg render integration test, and a dependency vulnerability audit. The real-render test generates an actual MP4 and validates the output with `ffprobe`.

## Documentation

The maintained documentation lives under `docs/`. Historical Git cleanup is documented separately in `docs/GIT_HISTORY_CLEANUP.md`; rewriting old Git history remains a coordinated migration because it requires a force-push and fresh clones.
