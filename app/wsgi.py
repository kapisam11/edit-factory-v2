"""Production WSGI entrypoint for Gunicorn or another WSGI server."""
import os

from dashboard_auth import configure_dashboard_auth
from dashboard_compat import register_dashboard_compat
from web_app_v2 import app
from werkzeug.middleware.proxy_fix import ProxyFix

if os.environ.get("AIVF_TRUST_PROXY", "0") == "1":
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_host=1, x_proto=1)

configure_dashboard_auth(app)
register_dashboard_compat(app)

__all__ = ["app"]
