# 04 — Using the Dashboard

The dashboard is the browser control panel for Edit Factory. It is the main place to start jobs, watch the queue, cancel work, inspect generated packages, and change runtime defaults.

## How the dashboard is started

The production WSGI implementation lives at:

```text
02-WEB-FILES/app/wsgi.py
```

The browser control panel is:

```text
02-WEB-FILES/templates/index.html
```

The Flask dashboard/API implementation is:

```text
02-WEB-FILES/app/web_app_v2.py
```

Queue compatibility, lifecycle maintenance, cancellation, presets, and package helper routes are registered by:

```text
01-MAIN-CODE/dashboard_compat.py
```

The production Gunicorn configuration lives at:

```text
06-CONFIG-AND-DEPLOYMENT/gunicorn.conf.py
```

Start it from the repository root with:

```bash
gunicorn -c 06-CONFIG-AND-DEPLOYMENT/gunicorn.conf.py wsgi:app
```

## Normal control-panel flow

```text
Open dashboard
     ↓
Sign in / pass dashboard authentication
     ↓
Choose topic, target length, and workflow
     ↓
Optionally upload raw video
     ↓
Start production
     ↓
Watch queue + live logs
     ↓
Cancel when necessary, or wait for completion
     ↓
Open the generated package
     ↓
Preview video / edit script / inspect thumbnails / open files
```

## Production controls

### Target length

The dashboard accepts a target duration from **15 to 120 seconds**. The same contract is enforced again at the worker/pipeline boundary so direct calls cannot silently bypass the UI restriction.

### Workflows

The current canonical workflow names are:

- `default` — full normal pipeline
- `fast` — reduced pipeline for quicker production
- `package_only` — planning/package-oriented workflow without the full expensive stages

Older dashboard aliases such as `director` and `legacy` are normalized for compatibility, but new UI/configuration should use the canonical names.

### Queue and concurrency

The dashboard maintains a persisted SQLite job queue and starts heavy media work in spawned worker processes. The `max_concurrent_jobs` setting limits how many workers are active at once; additional jobs remain queued.

### Cancellation

The **Cancel Job** control requests cancellation through the dashboard lifecycle layer. Terminal states are protected from being overwritten by a late worker completion.

## Settings

The control panel can persist these job defaults:

- default target duration
- default workflow
- default skip-QC behavior
- default Groq usage
- maximum concurrent jobs

The server upload request limit is controlled by `AIVF_MAX_UPLOAD_MB`. It is shown in the dashboard as an informational value rather than a dynamically editable setting because Flask's request limit is configured when the application starts.

API keys can be supplied through the control panel. Their values are kept in process memory and are not returned by the settings API.

## Upload validation

When a raw video is uploaded, the dashboard checks the extension, request size, available disk space, and the actual media stream with `ffprobe`. The current validation rejects invalid video streams, dimensions above 7680×7680, and videos longer than one hour.

## Generated packages

The package browser reads the output directory and lets you inspect generated artifacts. It can show the rendered video, script, thumbnails, and the complete package file list. Paths are resolved under the configured output root before serving files.

## Why jobs use a separate process

Video encoding and other media work can be expensive. The dashboard creates a dedicated spawned worker process for active jobs instead of doing heavy work directly inside the web request process.

This also makes cancellation real: the application can terminate the dedicated worker process instead of only cancelling a Python scheduling object.

## Login and security

Production access requires the configured dashboard authentication and a real Flask secret key. Mutating browser requests are protected by same-origin checks, and the application adds security headers and rate limiting to job creation.

For local development only, an explicit insecure-local mode is available. Never use that mode for an internet-facing deployment.

## If a server restarts

The web process cannot magically resume an in-memory worker. Outstanding jobs are reconciled as `interrupted` so they remain visible instead of silently pretending they continued.

## Live production verification

A successful import or Docker build is not proof that the control panel works on a real server. Before calling a deployment production-ready, perform a real render, upload validation test, cancellation test, restart test, settings persistence test, and package/browser verification on the target machine. See [06 — Production Deployment](06-PRODUCTION-DEPLOYMENT.md).
