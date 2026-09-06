# Edit Factory v2 — Start Here

Welcome. This project turns a topic and optional raw video into an edited short-video package.

You do **not** need to understand every Python file before using it. Start with this document, then follow the path that matches what you want to do.

## What this project does

At a high level:

```text
You give it a topic + optional video
            ↓
      AI planning/research
            ↓
      editing decisions
            ↓
      FFmpeg media processing
            ↓
       final video package
```

The web dashboard adds a browser interface for creating jobs and watching their progress.

## Choose your path

| I want to... | Read this |
|---|---|
| Install and run it | [01 — Install](01-INSTALL.md) |
| Understand how it works | [02 — How It Works](02-HOW-IT-WORKS.md) |
| Use the command line | [03 — Using the CLI](03-USING-THE-CLI.md) |
| Run the web dashboard | [04 — Using the Dashboard](04-USING-THE-DASHBOARD.md) |
| Understand the project files | [05 — Project Map](05-PROJECT-MAP.md) |
| Deploy it on a server | [06 — Production Deployment](06-PRODUCTION-DEPLOYMENT.md) |
| Troubleshoot a problem | [07 — Troubleshooting](07-TROUBLESHOOTING.md) |
| Understand the learning system | [08 — Learning System](08-LEARNING-SYSTEM.md) |
| Develop/change the code | [09 — Developer Guide](09-DEVELOPER-GUIDE.md) |
| Upgrade from an older copy | [10 — Upgrading](10-UPGRADING.md) |

## The three important entry points

### `aivf`

The normal installed command-line interface.

### `cli.py`

The same project's direct Python CLI entry point. It is useful when you are working directly from the repository.

### `wsgi.py`

The production web-dashboard entry point. It is normally run by Gunicorn.

## The most important folders

```text
ai_video_factory/   ← the actual application code
web templates/      ← browser UI
static/             ← browser assets
scripts/tools/      ← helper tools
 tests/             ← automated tests
 docs/              ← human documentation
 state/output/...   ← generated runtime data (not source code)
```

Runtime directories may vary by configuration. Generated media, uploads, databases, model files, and local tool bundles should not be treated as source files.

## Before you share this project

A new developer should be able to answer these questions after reading the docs:

1. What does the application do?
2. How do I install it?
3. How do I run one job?
4. What happens after I submit a job?
5. Where do outputs and state live?
6. How do I safely deploy it?

That is the purpose of the numbered documentation in this folder.

> **Tip:** GitHub shows `README.md` first, so the README contains the short version. This folder contains the full beginner-friendly path. GitHub recommends using the README to explain what the project does and how to get started. citeturn136955search0turn136955search1
