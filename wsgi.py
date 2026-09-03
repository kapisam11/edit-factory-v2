"""Production WSGI entrypoint for Gunicorn or another WSGI server."""
import os

from web_app_v2 import app
from werkzeug.middleware.proxy_fix import ProxyFix

# Only trust forwarded headers when the deployment explicitly declares a
# trusted reverse proxy. This keeps same-origin and secure-cookie decisions
# tied to the public request URL without trusting arbitrary client headers.
if os.environ.get("AIVF_TRUST_PROXY", "0") == "1":
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_host=1, x_proto=1)

__all__ = ["app"]
