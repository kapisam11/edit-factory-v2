# 05 — Project Map

This page answers: **“Which part does what?”**

You normally do not need to edit most files directly.

## Start here

| Location | Plain-English job |
|---|---|
| `README.md` | The front door: what the project is and where to go next |
| `00-INFO/` | Beginner guides, architecture, operations, deployment, and history |
| `app/` | Canonical CLI/dashboard/WSGI/worker implementations |
| `ai_video_factory/` | Core video-production pipeline and supporting Python code |
| `templates/` | Flask dashboard HTML/templates |
| `static/` | Dashboard CSS and browser assets |
| `03-SIDE-CODE/tools/` | Reusable developer/helper tools |
| `03-SIDE-CODE/scripts/` | Checks, verification, and maintenance scripts |
| `04-TESTS/tests/` | Automated tests |
| `05-EXTENSIONS/` | Prompt library, learning data, and hook scoring resources |
| `99-ARCHIVE/legacy/` | Retired compatibility/demo material |
| `pyproject.toml` | Project metadata, dependencies, and installed command |
| `Dockerfile` | Production container build instructions |
| `docker-compose.yml` | Local/host deployment definition |

## Runtime entrypoints

The four root files below are intentionally small compatibility launchers:

- `cli.py` → real CLI in `app/cli.py`
- `wsgi.py` → real WSGI application in `app/wsgi.py`
- `web_app_v2.py` → real dashboard in `app/web_app_v2.py`
- `dashboard_worker.py` → real worker in `app/dashboard_worker.py`

The root locations are kept so existing commands and integrations such as `python cli.py`, `wsgi:app`, and older imports continue to work.

## Core application

Everything in `ai_video_factory/` is core application code. Useful starting modules include:

| File | Responsibility |
|---|---|
| `pipeline.py` | Orchestrates production stages |
| `director.py` | High-level video production workflow |
| `composer.py` | Combines media into a finished composition |
| `model_adapter.py` | AI/model provider adapters |
| `config.py` | Configuration models and safe persistence |
| `asset_manager.py` | Runtime assets and metadata |
| `knowledge.py` / `knowledge_v2.py` | Knowledge and learning data |
| `learning.py` | Learning and feedback logic |
| `learning_recommender.py` | Recommendations from learned results |
| `edit_planner.py` | Editing plans |
| `edit_automation.py` | Automated editing operations |
| `effects_engine.py` | Media effects |
| `music*.py` | Music retrieval, analysis, mixing, and timing |
| `hardware.py` | Capability detection |
| `interactive_review.py` | Human-review helpers |

## Documentation

The human-facing documentation lives under `00-INFO/` and is intentionally numbered in the order a new person is likely to need it.

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

Technical reference pages such as architecture, operations, hardening, release checks, and history are also kept in `00-INFO/`.

## What not to edit manually

Do not manually edit generated runtime files, databases, uploads, produced media, local model caches, or downloaded tool bundles. Those are runtime data rather than application source code.
