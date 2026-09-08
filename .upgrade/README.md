# Upgrade notes

This directory is the quick migration reference for the current Edit Factory architecture.

## Current state

The browser dashboard is a control panel, not a separate legacy application. The current browser UI is `02-WEB-FILES/templates/index.html`, backed by `02-WEB-FILES/app/web_app_v2.py` and lifecycle/compatibility routes in `01-MAIN-CODE/dashboard_compat.py`.

The current production path uses the organized `01-MAIN-CODE/ai_video_factory` package. Older launchers and historical implementation notes remain only for compatibility/documentation.

## Important upgrade changes

- Dashboard UI and API contracts have been aligned.
- Canonical workflows are `default`, `fast`, and `package_only`.
- Target duration is validated from 15–120 seconds at multiple boundaries.
- Dashboard settings are type/range validated.
- Raw video uploads are checked for type, size, media dimensions, duration, and available disk space.
- Jobs have persisted queue state and live logs, with real worker-process cancellation.
- Package browsing supports video preview, scripts, thumbnails, and package files.
- Runtime application code no longer installs Python packages or downloads optional NLP models during execution.
- The production web deployment remains intentionally single-host/single-worker at the Gunicorn process level.

## Upgrade checklist

1. Back up state, uploads, and generated output.
2. Update the checkout.
3. Reinstall the project dependencies.
4. Verify `python 01-MAIN-CODE/cli.py --help` and `aivf --help`.
5. Start the dashboard with the supported WSGI/Gunicorn configuration.
6. Test creating a job, queueing, live logs, cancellation, and package inspection.
7. Verify settings persistence and server-restart recovery.
8. For production, run a real render on the target host.

See `00-INFO/10-UPGRADING.md` for the full upgrade procedure and `00-INFO/04-USING-THE-DASHBOARD.md` for the control-panel guide.

## Do not confuse upgrades with history cleanup

Normal upgrades change the current tree only. Git history purging is a separate operation that rewrites commit history and must be handled independently.