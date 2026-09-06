"""Compatibility module for the canonical dashboard implementation."""
import sys

from app import web_app_v2 as _implementation

# Keep existing imports/tests working while the real implementation lives in app/.
sys.modules[__name__] = _implementation

if __name__ == "__main__":
    from dashboard_auth import configure_dashboard_auth
    from dashboard_compat import register_dashboard_compat

    configure_dashboard_auth(_implementation.app)
    register_dashboard_compat(_implementation.app)
    _implementation.app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
