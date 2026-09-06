# 05 — Project Map

This page answers the question: **“Which file does what?”**

You normally do not need to edit most files directly.

## Start with these

| File | Plain-English job |
|---|---|
| `README.md` | The front door: what the project is and where to go next |
| `cli.py` | Command-line entry point |
| `wsgi.py` | Production web-server entry point |
| `web_app_v2.py` | Flask dashboard/API application |
| `dashboard_worker.py` | Runs a dashboard job in its own process |
| `pyproject.toml` | Project metadata, dependencies, and installed command |
| `Dockerfile` | Instructions for building the production container |
| `docker-compose.yml` | Local/host deployment definition |

## Core application package

Everything inside `ai_video_factory/` is application code. The names are intentionally descriptive:

| File | What it is responsible for |
|---|---|
| `pipeline.py` | Orchestrates the production stages |
| `director.py` | High-level video production/director workflow |
| `composer.py` | Combines media into a finished composition |
| `model_adapter.py` | Talks to supported AI/model providers |
| `config.py` | Loads and validates application configuration |
| `asset_manager.py` | Handles runtime assets and metadata |
| `knowledge.py` / `knowledge_v2.py` | Knowledge/learning data handling |
| `learning.py` | Learning and feedback logic |
| `learning_recommender.py` | Recommendations based on learned results |
| `edit_planner.py` | Creates editing plans |
| `edit_automation.py` | Applies automated editing operations |
| `effects_engine.py` | Media effects |
| `music*.py` | Music retrieval, analysis, mixing, and timing |
| `hardware.py` | Hardware/capability detection |
| `interactive_review.py` | Human review helpers |
| `capability_registry.py` | Tracks available optional capabilities and fallbacks |

There are additional modules in this package. Their filenames should be read as implementation details; the user-facing starting points are still the CLI and dashboard.

## Tests

`tests/` contains automated checks. These protect security, configuration, media processing, retries, dashboard behavior, and other important code paths.

## Documentation

`docs/00-START-HERE.md` is the beginner entry point.

The numbered docs are intentionally arranged in the order a new person is likely to need them:

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

Technical reference documents such as architecture and release material sit beside those beginner guides so experienced developers can jump directly to them.

## What not to edit manually

Do not manually edit generated runtime files, databases, uploads, produced media, local model caches, or bundled tool directories. Those are runtime data rather than the application's source code.
