# Changelog

## 2.3.0 — 2026-09-03

### Reliability and security
- Moved dashboard job execution into the spawn-safe `worker.py` process boundary.
- Added real OS-level worker cancellation instead of relying on `Future.cancel()`.
- Reconciled jobs that were left `running` after a dashboard restart as `interrupted`.
- Enabled SQLite WAL mode and busy timeouts for concurrent dashboard/worker access.
- Added timing-safe plaintext admin-password comparison with `hmac.compare_digest`.
- Added video signature validation and optional `ffprobe` validation for uploads.
- Centralized workflow and target-duration validation for CLI and dashboard.
- Added graceful SIGTERM/SIGINT worker shutdown handling.
- Added a single-web-worker guard for the process-local dashboard architecture.
- Added automatic output retention cleanup.
- Added security headers and production health reporting.

### Tooling and deployment
- Raised the supported Python floor to 3.10.
- Added Dockerfile, Docker Compose, Docker context exclusions, and Gunicorn configuration.
- Removed runtime FFmpeg/model bundles and generated `ok/` output from the current repository tree.
- Tightened `.gitignore` for runtime state, generated media, local tools, and models.
- Added structured CLI logging, tracebacks, progress/ETA, and batch CSV/JSON support.

### Documentation
- Consolidated operational documentation under `docs/`.
- Historical Git objects containing old binaries are documented as a separate, coordinated migration task rather than rewritten automatically.
