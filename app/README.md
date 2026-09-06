# Edit Factory v2

**AI-assisted video production and auto-editing for short-form content.**

Edit Factory takes a topic and, when you provide one, raw video footage. It can plan a video, use optional AI/research features, analyze media, and produce an edited video package using FFmpeg.

This repository is written for developers, but you should **not** need to understand the whole codebase before trying it.

## 🚀 Start here

New to this project? Read **[docs/00-START-HERE.md](docs/00-START-HERE.md)**.

The documentation is numbered in the order a new person usually needs it:

```text
00 Start Here
01 Install
02 How It Works
03 Using the CLI
04 Using the Dashboard
05 Project Map
06 Production Deployment
07 Troubleshooting
08 Learning System
09 Developer Guide
10 Upgrading
```

GitHub surfaces the repository README prominently, so this page stays short and points newcomers to the detailed guides. citeturn136955search0turn136955search1

## What does it do?

```text
Topic + optional raw video
          ↓
   AI / research / plan
          ↓
   editing decisions
          ↓
    FFmpeg processing
          ↓
     video package
```

The browser dashboard adds job tracking, progress, logs, and cancellation around the same core application.

## The three files you should know first

| File | What it means |
|---|---|
| `cli.py` | Run the project from a terminal |
| `wsgi.py` | Start the production web application |
| `web_app_v2.py` | The Flask dashboard/API itself |

The installed command `aivf` points to `cli.py`.

## Quick start

Create a virtual environment:

```bash
python -m venv .venv
```

Activate it and install:

```bash
python -m pip install -e ".[web,dev]"
```

Check the CLI:

```bash
python cli.py --help
# or, after installation
aivf --help
```

Check media tools:

```bash
ffmpeg -version
ffprobe -version
```

## Run a simple job

```bash
python cli.py "Minecraft betrayal on SMP"
```

For raw-footage auto-editing, use the current CLI help to confirm the available input/editing flags:

```bash
python cli.py --help
```

## Run the production dashboard

The supported production entry point is `wsgi.py`, normally served by Gunicorn with one worker:

```bash
gunicorn --workers 1 --bind 0.0.0.0:5000 --timeout 0 wsgi:app
```

Production dashboard access requires `AIVF_DASHBOARD_TOKEN` and a strong `FLASK_SECRET_KEY`. Use `AIVF_COOKIE_SECURE=1` when HTTPS is in use.

## Optional features

Optional dependency groups include:

- `beats` — music beat analysis
- `vision` — OpenCV-based vision features
- `ocr` — OCR support
- `diarization` — speaker diarization
- `groq` — Groq integration
- `elevenlabs` — ElevenLabs integration
- `full` — the larger optional feature set

## How production works

```text
Browser
  ↓
Gunicorn (1 worker)
  ↓
Flask dashboard/API
  ├── SQLite durable state
  └── spawned job process
          ↓
       pipeline
          ↓
    FFmpeg / FFprobe
```

Jobs use dedicated spawned processes. SQLite uses WAL/busy-timeout settings, and runtime API credentials are kept out of persisted job records/logs.

## Production verification

Automated CI and Docker checks are necessary but are not the same as proving the application works on the real machine that will run it. Before calling a deployment fully verified, run a real render, cancellation test, restart/recovery test, persistence test, and shutdown test on the target host.

See **[docs/06-PRODUCTION-DEPLOYMENT.md](docs/06-PRODUCTION-DEPLOYMENT.md)**.

## Repository map

```text
README.md                    ← start here
pyproject.toml               ← dependencies + packaging
Dockerfile                   ← production container
cli.py                       ← command-line entry point
wsgi.py                      ← production web entry point
web_app_v2.py                ← dashboard/API
 dashboard_worker.py         ← isolated job worker
ai_video_factory/             ← core application code
tests/                        ← automated tests
docs/                         ← beginner + technical documentation
```

Generated media, uploads, runtime state, model caches, and local tool bundles are not source code and should not be committed.
