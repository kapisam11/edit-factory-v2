# Production Hardening Status

This branch is the canonical hardening pass for the dashboard and local single-host deployment.

## Implemented

- SQLite WAL and busy timeout.
- Append-only job logs instead of read/modify/write JSON logs.
- Startup reconciliation marks interrupted in-flight jobs explicitly.
- Spawned per-job processes with explicit lifecycle tracking.
- Running jobs can be terminated instead of pretending that `Future.cancel()` stopped them.
- Cancelled jobs are terminal and SSE streams close for all terminal states.
- Job secrets are kept out of SQLite job records and API responses.
- Dashboard uploads use `secure_filename`, UUID storage names, extension allowlists, size limits, and ffprobe validation.
- Topic text cannot control package filesystem paths.
- Package resolution is contained inside the configured output root.
- Nested configuration dataclasses are reconstructed correctly on JSON load.
- Config persistence redacts API credentials.
- Model-provider credentials never fall through from Groq to OpenAI.
- Docker no longer copies the nonexistent `worker.py`.
- Persistent SQLite state is stored under `/app/state`.
- CI builds the Docker image and smoke-tests dashboard imports.
- Runtime/generated directories are ignored going forward.

## Operational constraints

This project intentionally remains a single-host application. It does not require Redis,
Celery, Kubernetes, or microservices. Run one Gunicorn worker because active job-process
bookkeeping is intentionally process-local.

## Still required before declaring a literal 10/10

A full release gate should run the complete test suite, Docker build, real FFmpeg integration,
and manual end-to-end cancellation/restart testing on both Windows and Linux. A score should
only be upgraded after those checks pass against the final merged commit.
