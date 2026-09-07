# Edit Factory v2

**AI-assisted video production and auto-editing for short-form content.**

Edit Factory takes a topic and optional raw footage, then can research, plan, script, edit, render, quality-check, and package a short video.

## New here? Start here

Read **[00-INFO/00-START-HERE.md](00-INFO/00-START-HERE.md)** first.

The repository is intentionally organized so the GitHub front page stays simple:

```text
Edit Factory v2
├── README.md                         <- you are here
├── 00-INFO/                          <- guides, documentation, project map
├── 01-MAIN-CODE/                     <- Python application + CLI runtime
├── 02-WEB-FILES/                     <- dashboard application + templates + CSS
├── 03-SIDE-CODE/                     <- helper tools and maintenance scripts
├── 04-TESTS/                         <- automated tests
├── 05-EXTENSIONS/                    <- prompts, learning data, hook scoring
├── 06-CONFIG-AND-DEPLOYMENT/        <- Docker and deployment configuration
└── 99-ARCHIVE/                       <- retired material
```

There are no source-code or sample-output files at the repository root. Hidden Git configuration folders/files still remain at the root because GitHub and development tools require them there.

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
python -m pip install -e './01-MAIN-CODE[web,dev]'
python 01-MAIN-CODE/cli.py --help
```

Run a simple job:

```bash
python 01-MAIN-CODE/cli.py "Minecraft betrayal on SMP"
```

Run the production dashboard:

```bash
gunicorn -c 06-CONFIG-AND-DEPLOYMENT/gunicorn.conf.py wsgi:app
```

Production dashboard access requires `AIVF_DASHBOARD_TOKEN` and a strong `FLASK_SECRET_KEY`.

## Where things live

- **Main application:** `01-MAIN-CODE/`
- **Dashboard and browser files:** `02-WEB-FILES/`
- **Tools and maintenance:** `03-SIDE-CODE/`
- **Tests:** `04-TESTS/`
- **Extensions/resources:** `05-EXTENSIONS/`
- **Docker/config/deployment:** `06-CONFIG-AND-DEPLOYMENT/`
- **Old material:** `99-ARCHIVE/`
