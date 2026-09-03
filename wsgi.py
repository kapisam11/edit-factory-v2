"""Production WSGI entrypoint for Gunicorn or another WSGI server."""
from web_app_v2 import app

__all__ = ["app"]
