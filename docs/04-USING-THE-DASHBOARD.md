# 04 — Using the Dashboard

The dashboard is the browser version of Edit Factory.

## How the dashboard is started

The production entry point is:

```text
wsgi.py
```

It is intended to run behind Gunicorn with one web worker.

Example:

```bash
gunicorn --workers 1 --bind 0.0.0.0:5000 --timeout 0 wsgi:app
```

## What you do in the dashboard

The normal flow is:

```text
Open dashboard
     ↓
Sign in
     ↓
Create a job
     ↓
Upload/choose input
     ↓
Watch progress and logs
     ↓
Wait for Done / Error / Cancelled
     ↓
Open the generated package
```

## Why jobs use a separate process

Video encoding and other media work can be expensive. The dashboard creates a dedicated spawned worker process for active jobs rather than doing the heavy work directly inside the web request process.

This also makes cancellation real: the application can terminate the dedicated worker process instead of only cancelling a Python scheduling object.

## Login and security

Production access requires `AIVF_DASHBOARD_TOKEN` and a real Flask secret key. Mutating browser requests are protected by same-origin checks, and the application adds security headers.

For local development only, an explicit insecure-local mode is available. Never use that mode for an internet-facing deployment.

## If a job is cancelled

A running job is moved through the cancellation flow and the worker process is terminated. Terminal jobs should no longer continue changing state after cancellation.

## If the server restarts

The web process cannot magically resume an in-memory worker. Outstanding jobs are reconciled as `interrupted` so they are visible rather than silently pretending they continued.

## Live production verification

A successful import or Docker build is not proof that the dashboard works on your real server. Before calling a deployment production-ready, perform a real render, cancellation test, restart test, and persistence test on the target machine. See [06 — Production Deployment](06-PRODUCTION-DEPLOYMENT.md).
