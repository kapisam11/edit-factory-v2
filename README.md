# Edit Factory v2

**AI-assisted video production and auto-editing for short-form content.**

Edit Factory takes a topic and, when you provide one, raw video footage. It can plan a video, use optional AI/research features, analyze media, and produce an edited video package using FFmpeg.

## 👋 New here? Start here

Read **[00-INFO/00-START-HERE.md](00-INFO/00-START-HERE.md)** first. The information folder is intentionally placed at the top so a new person can understand the project before opening code.

```text
Edit Factory v2
├── 00-INFO/                         ← READ THIS FIRST
├── app/                             ← main CLI + web runtime implementations
├── ai_video_factory/                ← core video-generation pipeline
├── templates/                       ← dashboard HTML/templates
├── static/                          ← dashboard CSS/assets
├── tools/                           ← developer/helper tools
├── scripts/                         ← maintenance and verification scripts
├── prompt_templates/                ← prompt/resource material
├── tests/                           ← automated tests
├── knowledge_base_v2/               ← learning data
├── legacy/                          ← old compatibility/demo material
│
├── cli.py                           ← compatibility launcher
├── wsgi.py                          ← compatibility web launcher
├── web_app_v2.py                    ← compatibility dashboard launcher
├── dashboard_worker.py              ← compatibility worker launcher
├── Dockerfile                       ← production container
├── docker-compose.yml               ← local/host deployment
├── pyproject.toml                   ← Python project + dependencies
└── uv.lock                          ← locked Python dependencies
```

The four small root Python files above are compatibility launchers. The main implementations now live in `app/`, giving the project one obvious home for entrypoint code while preserving existing commands and integrations.

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

Run a simple job:

```bash
python cli.py "Minecraft betrayal on SMP"
```

## Run the production dashboard

The supported production entry point is still `wsgi.py`, normally served by Gunicorn with one worker:

```bash
gunicorn --workers 1 --bind 0.0.0.0:5000 --timeout 0 wsgi:app
```

Production dashboard access requires `AIVF_DASHBOARD_TOKEN` and a strong `FLASK_SECRET_KEY`. Use `AIVF_COOKIE_SECURE=1` when HTTPS is in use.

## Optional features

Optional dependency groups include beats/music analysis, computer vision, OCR, speaker diarization, Groq integration, and ElevenLabs integration. See the install guide in `00-INFO/` for details.

## Production verification

Automated CI and Docker checks are necessary but are not the same as proving the application works on the real machine that will run it. Before calling a deployment fully verified, run a real render, cancellation test, restart/recovery test, persistence test, and shutdown test on the target host.

See **[00-INFO/06-PRODUCTION-DEPLOYMENT.md](00-INFO/06-PRODUCTION-DEPLOYMENT.md)**.
