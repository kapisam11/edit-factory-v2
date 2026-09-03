# AI Video Factory v2

Generate research-backed short-video packages with automated planning, script generation, thumbnails, optional auto-editing, voiceover, music, QC, metadata, metrics, and learning feedback.

## Requirements

- Python 3.9+
- FFmpeg on PATH for video rendering
- Optional API keys for external AI providers
- Docker is supported for a reproducible web deployment

## Install

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[web,dev]"
```

Optional extras are available for beat detection, Groq, ElevenLabs, and audit tooling.

### Runtime assets

FFmpeg and MobileNetSSD runtime binaries/models are **not** tracked in the source tree anymore. Use the bootstrap helpers when those optional assets are required:

```bash
python tools/install_tools.py
python tools/install_mobilenet_ssd.py
```

The repository ignores `.tools/` and `.models/` so local runtime assets do not get committed again.

> Historical Git objects may still contain older binary revisions. The current branch is cleaned, but completely removing those historical objects requires a coordinated history rewrite and force-push; that is intentionally a separate migration because it rewrites commit SHAs.

## CLI

The main entry point is `cli.py`:

```bash
python cli.py "Minecraft betrayal on SMP"
python cli.py "Minecraft betrayal on SMP" --raw-video gameplay.mp4 --director
python cli.py "COD clutch" --raw-video clip.mp4 --pipeline fast
python cli.py "Minecraft" --pipeline package_only
```

The CLI now logs structured progress including percent, elapsed time, and ETA. Use `--verbose` for debug-level logging or `--quiet` for warnings/errors only.

### Batch mode

Queue CSV or JSON jobs in one invocation:

```bash
python cli.py --batch topics.csv --batch-workers 2
```

CSV requires a `topic` column. JSON may be a list of strings or objects such as `{"topic":"Minecraft", "target_seconds":45}`.

### Thumbnail experiments

The pipeline generates three thumbnail variants and records the selected variant in package metadata and learning feedback:

```bash
python cli.py "Minecraft betrayal" --thumbnail-variant 2 --learn --engagement-score 0.82
python cli.py "Minecraft betrayal" --thumbnail-variant auto
```

Variants are stored under `thumbnails/`. The helper `ai_video_factory.thumbnail_learning` can use historical feedback to rank variants.

## Web dashboard

The dashboard requires a Flask secret and authentication configuration.

### Single-admin mode

```bash
export FLASK_SECRET_KEY="use-a-long-random-secret"
export AIVF_ADMIN_PASSWORD="use-a-strong-password"
```

### Multi-user mode

Set `AIVF_ADMIN_USERS_JSON` to a JSON object mapping usernames to Werkzeug password hashes. Example shape:

```text
AIVF_ADMIN_USERS_JSON='{"admin":"scrypt:...","editor":"scrypt:..."}'
```

When multi-user mode is configured, it takes precedence over the single-admin password.

On Windows PowerShell:

```powershell
$env:FLASK_SECRET_KEY = "use-a-long-random-secret"
$env:AIVF_ADMIN_PASSWORD = "use-a-strong-password"
```

For local development:

```bash
python web_app_v2.py
```

For production on a Unix-like host, use one Gunicorn worker because the application owns the bounded `ProcessPoolExecutor`. Scale video-processing concurrency with `AIVF_WORKERS`:

```bash
AIVF_WORKERS=2 gunicorn -w 1 -b 0.0.0.0:5000 wsgi:app
```

Behind HTTPS, set:

```bash
export AIVF_COOKIE_SECURE=1
export AIVF_HSTS=1
```

The dashboard enforces same-origin checks for all state-changing routes. Requests with neither `Origin` nor `Referer` are rejected. Responses include defensive headers including CSP, X-Frame-Options, and no-sniff protection.

Dashboard-entered API keys are deliberately process-lifetime only and are **not persisted**. The UI warns about this. Use environment variables for persistent deployment configuration.

### Webhooks

Set `AIVF_WEBHOOK_URL` to receive a JSON notification when a queued job completes or fails. The payload contains the event, job ID, topic, status, and optional error text.

## Docker

Build and run the dashboard with:

```bash
docker compose up --build
```

Set `FLASK_SECRET_KEY` and either `AIVF_ADMIN_PASSWORD` or `AIVF_ADMIN_USERS_JSON` in your environment or `.env` file. Persistent output, uploads, and learning data are mounted as volumes. Install or mount any optional MobileNetSSD runtime model separately.

## Architecture

```text
cli.py / web_app_v2.py / wsgi.py
        |
        v
  PipelineContext
        |
        +--> research
        +--> plan
        +--> script
        +--> thumbnail (3 variants + selected variant)
        +--> auto_edit
        +--> voiceover
        +--> music
        +--> quality_control
        +--> metadata
        +--> metrics
```

Shared validation lives in `ai_video_factory/validation.py`, so CLI, web, and pipeline duration/workflow rules cannot silently diverge. Pipeline execution reports stage timing and live progress callbacks.

The dashboard persists jobs in SQLite with WAL mode and a busy timeout, while the ProcessPoolExecutor is the concurrency gate; there is no additional worker busy-poll loop.

## Project layout

| Path | Purpose |
| --- | --- |
| `cli.py` | Primary command-line entry point |
| `web_app_v2.py` | Authenticated browser dashboard/API |
| `wsgi.py` | Production WSGI entry point |
| `ai_video_factory/` | Core production package |
| `tools/` | Hook, bootstrap, reporting and utility tools |
| `tests/` | Unit and regression tests |
| `.github/workflows/python-tests.yml` | CI: install, dependency check, compile, lint, audit, coverage and tests |
| `Dockerfile` / `docker-compose.yml` | Containerized dashboard deployment |

Generated media, uploads, local databases, knowledge feedback, `.env` files, local runtime binaries/models, and logs are ignored by Git.

## Dependencies

`pyproject.toml` is the **source of truth** for dependencies. `requirements.txt` is intentionally a thin compatibility entry point that installs the editable project with the `web` and `dev` extras; do not maintain a second independent dependency list there.

`uv.lock` is checked in for reproducible resolver output. Use `uv sync --frozen` or an equivalent frozen resolver flow for deployments that support uv. Do not hand-maintain duplicate pinned dependency lists.

## Quality and CI

The CI workflow tests Python 3.9 through 3.12 and runs package installation, `pip check`, Python compilation, Ruff on the audited production entry points, `pip-audit`, and the pytest suite with coverage reporting.

Real-media or heavyweight tooling tests should be isolated behind the project integration test marker so normal CI stays deterministic and fast.
