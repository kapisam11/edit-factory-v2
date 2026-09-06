# Structure notes

The repository keeps beginner documentation in `00-INFO/` and the canonical CLI/web runtime implementations in `app/`.

Deployment files stay at the repository root so standard Python and Docker tooling can find them.

Root `cli.py`, `wsgi.py`, `web_app_v2.py`, and `dashboard_worker.py` remain compatibility entrypoints for existing commands and integrations.
