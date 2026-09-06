# Edit Factory v2

**AI-assisted video production and auto-editing for short-form content.**

Edit Factory takes a topic and optional raw footage, then can research, plan, script, edit, render, quality-check, and package a short video.

## New here? Start here

Read **[00-INFO/00-START-HERE.md](00-INFO/00-START-HERE.md)** first.

```text
Edit Factory v2
├── README.md                         ← you are here
├── 00-INFO/                          ← guides, architecture, operations
├── 01-MAIN-CODE/                     ← explanation of the core code
│   └── ai_video_factory/             ← described here; kept at root for Python imports
├── 02-WEB-FILES/                    ← browser resources
│   ├── static/                       ← CSS and browser assets
│   └── templates/                    ← dashboard HTML/config templates
├── 03-SIDE-CODE/                    ← helpers and maintenance
│   ├── tools/                        ← reusable developer utilities
│   └── scripts/                      ← project checks and maintenance commands
├── 04-TESTS/                         ← automated tests
├── 05-EXTENSIONS/                   ← optional/resource-driven features
│   ├── prompt-library/               ← reusable prompt resources
│   ├── learning-data/                ← learning data
│   └── hook-scoring/                 ← hook scoring weights
├── 07-EXAMPLES/                     ← old example material
│   └── sample-output/                ← generated Minecraft example package
├── 99-ARCHIVE/                      ← retired material
│   └── legacy/
├── app/                             ← canonical CLI + dashboard implementations
├── knowledge_base_v2/               ← persistent learning data; runtime path
├── cli.py                           ← compatibility launcher
├── wsgi.py                          ← compatibility web launcher
├── web_app_v2.py                    ← compatibility dashboard launcher
├── dashboard_worker.py              ← compatibility worker launcher
├── dashboard_auth.py                ← dashboard authentication support
├── dashboard_compat.py              ← dashboard compatibility routes
├── dashboard_shutdown.py            ← dashboard shutdown handling
├── aivf_config.json                 ← application configuration
├── Dockerfile                       ← production container build
├── docker-compose.yml               ← deployment definition
├── pyproject.toml                   ← Python package and dependencies
├── requirements.txt                 ← dependency reference
└── uv.lock                          ← locked dependency set
```

The root Python entrypoint files are deliberately small compatibility launchers. The real CLI/web implementations live in `app/`; keeping `app/` at the root preserves a normal importable Python package while still giving the project one clear home for the entrypoint implementation.

## What does it do?

```text
Topic + optional raw video
          ↓
   research / planning
          ↓
      script + hooks
          ↓
    editing decisions
          ↓
       FFmpeg work
          ↓
     quality control
          ↓
    upload-ready package
```

## Quick start

```bash
python -m venv .venv
python -m pip install -e ".[web,dev]"
python cli.py --help
```

Run a simple job:

```bash
python cli.py "Minecraft betrayal on SMP"
```

The production dashboard uses `wsgi.py` and Gunicorn:

```bash
gunicorn --workers 1 --bind 0.0.0.0:5000 --timeout 0 wsgi:app
```

Production dashboard access requires `AIVF_DASHBOARD_TOKEN` and a strong `FLASK_SECRET_KEY`.

## Important naming note

`07-EXAMPLES/sample-output/` is the old generated example that used to sit in the confusing root folder named `ok/`. It is sample/reference output, not a special Minecraft subsystem.

## Production verification

CI and Docker checks are necessary but are not the same as proving the application works on the real machine that will run it. Before calling a deployment fully verified, run a real render, cancellation test, restart/recovery test, persistence test, and shutdown test on the target host.

See **[00-INFO/06-PRODUCTION-DEPLOYMENT.md](00-INFO/06-PRODUCTION-DEPLOYMENT.md)**.
