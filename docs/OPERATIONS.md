# Operations

## Local development

Install the project from `pyproject.toml` with the needed extras. Keep `uv.lock` committed for reproducible resolution.

FFmpeg and optional model/OCR assets are runtime dependencies. Do not commit generated media, model weights, local FFmpeg bundles, SQLite state, or knowledge-base data.

## Dashboard

Run the dashboard with a single web worker. For production, use the supplied Gunicorn configuration or Docker image. Set a strong `FLASK_SECRET_KEY` and configure API credentials through environment/process-memory settings rather than source control.

The dashboard automatically reconciles abandoned running jobs after a restart and periodically removes output older than `AIVF_RETENTION_DAYS` (default 7 days). Set `AIVF_DISABLE_AUTO_CLEANUP=1` to disable the background retention loop.

## Cancellation and shutdown

Cancelling a job terminates its dedicated worker process. This is substantially stronger than cancelling a queued future, but operating-system subprocess behavior can still vary for descendants spawned by third-party tools.

SIGTERM and SIGINT cause the dashboard to terminate active workers and mark them `interrupted`.

## Docker

`docker compose up --build` starts the FFmpeg-enabled dashboard with one Gunicorn worker. Runtime output, uploads, knowledge data, and state use named volumes so they survive container replacement.
