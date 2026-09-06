# Web files

The browser side is split into:

- `../app/web_app_v2.py` — Flask dashboard/API implementation
- `../templates/` — HTML and dashboard templates
- `../static/` — CSS and browser assets
- `../app/wsgi.py` — production WSGI application entrypoint

The root `web_app_v2.py` and `wsgi.py` files are compatibility launchers so existing commands keep working.
