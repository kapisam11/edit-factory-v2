# Edit Factory v2 — Start Here

Welcome. This project turns a topic and optional raw video into an edited short-video package.

You do **not** need to understand every Python file before using it. Start here, then follow the path that matches what you want to do.

## What this project does

```text
Topic + optional video
        ↓
 AI planning/research
        ↓
 script + hooks
        ↓
 editing decisions
        ↓
 FFmpeg processing
        ↓
 final video package
```

The web dashboard adds a browser interface for creating jobs and watching progress.

## Your first five minutes

1. Read this page.
2. Read `01-INSTALL.md`.
3. Run `python cli.py --help`.
4. Try one small topic job.
5. Open `05-PROJECT-MAP.md` when you need to know where something lives.

## The important entry points

### `aivf`
The normal installed command-line interface.

### `cli.py`
The direct Python CLI launcher kept at the repository root for compatibility. The real CLI implementation is `app/cli.py`.

### `wsgi.py`
The production web-dashboard launcher kept at the repository root. The real WSGI implementation is `app/wsgi.py`.

### `web_app_v2.py`
The compatibility dashboard launcher. The real Flask dashboard implementation is `app/web_app_v2.py`.

### `dashboard_worker.py`
The compatibility worker launcher. The real worker implementation is `app/dashboard_worker.py`.

## The project folders

```text
00-INFO/                       ← documentation and project knowledge
01-MAIN-CODE/                  ← explanation of core application code
02-WEB-FILES/                  ← explanation of browser/web resources
03-SIDE-CODE/                  ← helper tools and maintenance scripts
04-TESTS/                      ← automated tests
05-EXTENSIONS/                 ← prompts, learning data, scoring resources
06-CONFIG-AND-DEPLOYMENT/     ← deployment/configuration guide
07-EXAMPLES/                   ← sample/reference output
99-ARCHIVE/                    ← retired material

app/                           ← canonical CLI/web runtime implementations
ai_video_factory/              ← core video-production Python package
templates/                     ← Flask dashboard templates (runtime path)
static/                        ← browser CSS/assets (runtime path)
knowledge_base_v2/             ← persistent learning data (runtime path)
```

The numbered folders are there to make the repository easier for people to navigate. The Python runtime packages and Flask asset directories keep their normal import/runtime locations so the application remains straightforward to run.

## Where generated data goes

Generated videos and job state live in runtime directories such as `output/`, `uploads/`, and `state/`. Those are not source code.

## Need a specific answer?

| I want to... | Read this |
|---|---|
| Install and run it | `01-INSTALL.md` |
| Understand the pipeline | `02-HOW-IT-WORKS.md` |
| Use the CLI | `03-USING-THE-CLI.md` |
| Run the dashboard | `04-USING-THE-DASHBOARD.md` |
| Find a file | `05-PROJECT-MAP.md` |
| Deploy it | `06-PRODUCTION-DEPLOYMENT.md` |
| Fix a problem | `07-TROUBLESHOOTING.md` |
| Understand learning | `08-LEARNING-SYSTEM.md` |
| Change code | `09-DEVELOPER-GUIDE.md` |
| Upgrade | `10-UPGRADING.md` |
