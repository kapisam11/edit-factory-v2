"""Production WSGI entrypoint for Gunicorn or another WSGI server."""
import os
import sys

from app import web_app_v2 as _web_app_v2
from werkzeug.middleware.proxy_fix import ProxyFix

# Legacy modules import `web_app_v2`; point that name at the canonical implementation.
sys.modules.setdefault("web_app_v2", _web_app_v2)

app = _web_app_v2.app

if os.environ.get("AIVF_TRUST_PROXY", "0") == "1":
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_host=1, x_proto=1)

from dashboard_auth import configure_dashboard_auth
from dashboard_compat import register_dashboard_compat

configure_dashboard_auth(app)
register_dashboard_compat(app)

__all__ = ["app"]
