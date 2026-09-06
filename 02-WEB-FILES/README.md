# Web files

This section explains the browser side of Edit Factory.

- `app/web_app_v2.py` — dashboard and API implementation
- `app/wsgi.py` — production web entrypoint implementation
- `templates/` at the repository root — dashboard HTML/templates
- `static/` at the repository root — browser CSS/assets

The two asset directories intentionally remain at the root because the Flask runtime and Docker image use those standard paths. The root compatibility launchers are also kept so existing commands continue to work.
