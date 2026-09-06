# Edit Factory v2

**AI-assisted video production and auto-editing for short-form content.**

Edit Factory takes a topic and optional raw footage, then can research, plan, script, edit, render, quality-check, and package a short video.

## New here? Start here

Read **[00-INFO/00-START-HERE.md](00-INFO/00-START-HERE.md)** first.

```text
Edit Factory v2
├── README.md                         ← you are here
├── 00-INFO/                          ← READ THIS FIRST: guides and project info
├── 01-MAIN-CODE/                     ← explains the core application
├── 02-WEB-FILES/                    ← explains the dashboard/web side
├── 03-SIDE-CODE/                    ← helper tools and maintenance scripts
├── 04-TESTS/                         ← automated tests
├── 05-EXTENSIONS/                   ← prompts, learning data, hook scoring
├── 06-CONFIG-AND-DEPLOYMENT/        ← explains configuration/deployment files
├── 07-EXAMPLES/                     ← sample/reference output
├── 99-ARCHIVE/                      ← retired/legacy material
│
├── app/                             ← canonical CLI + dashboard implementations
├── ai_video_factory/                ← core video-production Python package
├── templates/                       ← dashboard HTML/templates (runtime path)
├── static/                          ← dashboard CSS/assets (runtime path)
├── knowledge_base_v2/               ← persistent learning data (runtime path)
│
├── cli.py                           ← compatibility CLI launcher
├── wsgi.py                          ← compatibility web launcher
├── web_app_v2.py                    ← compatibility dashboard launcher
├── dashboard_worker.py              ← compatibility worker launcher
├── dashboard_auth.py                ← dashboard authentication
├── dashboard_compat.py              ← compatibility routes/lifecycle helpers
├── dashboard_shutdown.py            ← worker shutdown handling
├── cli_v2.py                        ← older CLI kept for compatibility
│
├── aivf_config.json                 ← application configuration
├── Dockerfile                       ← production container build
├── docker-compose.yml               ← deployment definition
├── gunicorn.conf.py                 ← Gunicorn settings
├── pyproject.toml                   ← package metadata + dependencies
├── requirements.txt                 ← dependency reference
└── uv.lock                          ← locked dependency versions
```

The numbered folders are for people. The root runtime packages and compatibility launchers stay in their normal Python import locations so the application can run without fragile path tricks.

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

Run the production dashboard:

```bash
gunicorn --workers 1 --bind 0.0.0.0:5000 --timeout 0 wsgi:app
```

Production dashboard access requires `AIVF_DASHBOARD_TOKEN` and a strong `FLASK_SECRET_KEY`.

## About the old Minecraft folder

The old root folder named `ok/` was only holding a generated example package named `Minecraft_betrayal_on_SMP_20260623_075813`. It is now grouped under `07-EXAMPLES/sample-output/`, so it is clear that this is reference output and not a special Minecraft subsystem.

## Production verification

CI and Docker checks are necessary but are not the same as proving the application works on the real machine that will run it. Before calling a deployment fully verified, run a real render, cancellation test, restart/recovery test, persistence test, and shutdown test on the target host.

See **[00-INFO/06-PRODUCTION-DEPLOYMENT.md](00-INFO/06-PRODUCTION-DEPLOYMENT.md)**.
