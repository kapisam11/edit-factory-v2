# Architecture

Edit Factory has two supported entry points: the CLI and the Flask dashboard. Both use the same validation and pipeline definitions.

## CLI

`cli.py` validates the requested workflow and target duration, builds a `PipelineContext`, and runs `build_director_pipeline()`. Progress callbacks provide elapsed time and ETA. Batch mode accepts CSV or JSON input.

## Dashboard

`web_app_v2.py` owns HTTP, SQLite state, uploads, and job lifecycle. It does **not** create a process pool at import time. Each submitted job is started as a separate `multiprocessing` worker from `worker.py` using the `spawn` context, which is safe for Windows.

The worker writes progress and logs to SQLite. The parent tracks its `Process` object so a cancellation request can terminate the worker rather than merely marking a future cancelled.

## State

SQLite uses WAL mode and a busy timeout. Jobs have explicit `queued`, `running`, `done`, `error`, `cancelled`, and `interrupted` lifecycle states. Startup reconciliation marks jobs that were running during a process restart as `interrupted`.

API keys entered through the dashboard are process-lifetime secrets and are never persisted in SQLite job records. They are passed to the worker only in memory.

## Runtime assets

FFmpeg, MobileNet-SSD weights, generated media, uploads, and knowledge data are runtime assets, not source-controlled application dependencies. The repository ignores these paths and Docker does not copy them into the image.

## Deployment

Use one Gunicorn/web worker for the current process-local job registry. Docker and Docker Compose are provided for a reproducible FFmpeg-enabled runtime. A shared queue (Redis/Celery/RQ/etc.) should be introduced before enabling multiple web workers.
