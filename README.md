# Edit Factory v2

**AI-assisted video production and auto-editing for short-form content.**

Edit Factory takes a topic and optional raw footage, then can research, plan, script, edit, render, quality-check, and package a short video.

## New here? Start here

Read **[00-INFO/00-START-HERE.md](00-INFO/00-START-HERE.md)** first.

The repository is organized so the GitHub front page is simple and the files are grouped by purpose:

```text
Edit Factory v2
├── README.md                         <- you are here
├── pyproject.toml                    <- canonical Python packaging configuration
├── 00-INFO/                          <- guides, documentation, project map
├── 01-MAIN-CODE/                     <- core Python application + CLI runtime
├── 02-WEB-FILES/                     <- dashboard application + HTML/CSS
├── 03-SIDE-CODE/                     <- helper tools + maintenance scripts
├── 04-TESTS/                         <- automated tests
├── 05-EXTENSIONS/                    <- prompts, learning, scoring resources
├── 06-CONFIG-AND-DEPLOYMENT/        <- Docker, Gunicorn, Compose, configuration
└── 99-ARCHIVE/                       <- retired material
```

There are no source-code or sample-output files at the repository root. Hidden Git/editor configuration files remain there because the development tools need them.

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

From the repository root:

```bash
python -m venv .venv
python -m pip install -e '.[web,dev]'
python 01-MAIN-CODE/cli.py --help
```

Run a simple job:

```bash
python 01-MAIN-CODE/cli.py "Minecraft betrayal on SMP"
```

The installed CLI is also available as:

```bash
aivf --help
```

Run the production dashboard:

```bash
gunicorn -c 06-CONFIG-AND-DEPLOYMENT/gunicorn.conf.py wsgi:app
```

The canonical package now builds from the repository root. The dashboard remains a source-tree deployment component under `02-WEB-FILES/`; the launcher in `01-MAIN-CODE/wsgi.py` wires that dashboard into Gunicorn without package discovery through `../` paths.

Production dashboard access requires `AIVF_DASHBOARD_TOKEN` and a strong `FLASK_SECRET_KEY`.

## Where things live

- **Main application:** `01-MAIN-CODE/`
- **Dashboard and browser files:** `02-WEB-FILES/`
- **Tools and maintenance:** `03-SIDE-CODE/`
- **Tests:** `04-TESTS/`
- **Extensions/resources:** `05-EXTENSIONS/`
- **Docker/config/deployment:** `06-CONFIG-AND-DEPLOYMENT/`
- **Old material:** `99-ARCHIVE/`

For a file-by-file explanation, read **[00-INFO/05-PROJECT-MAP.md](00-INFO/05-PROJECT-MAP.md)**.
