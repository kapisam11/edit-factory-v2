"""Authentication and request-hardening for the single-user dashboard."""
import hashlib
import hmac
import os

from flask import abort, redirect, request, session, url_for


SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
PUBLIC_PATHS = {"/login", "/logout", "/api/health"}


def configure_dashboard_auth(app):
    token = os.environ.get("AIVF_DASHBOARD_TOKEN", "").strip()
    allow_insecure_local = os.environ.get("AIVF_ALLOW_INSECURE_LOCAL", "0") == "1"

    if not token and not allow_insecure_local:
        app.logger.warning("AIVF_DASHBOARD_TOKEN is unset; dashboard access will fail closed")

    app.config.setdefault("SESSION_COOKIE_HTTPONLY", True)
    app.config.setdefault("SESSION_COOKIE_SAMESITE", "Strict")
    app.config["SESSION_COOKIE_SECURE"] = os.environ.get("AIVF_COOKIE_SECURE", "0") == "1"

    def authenticated():
        return bool(session.get("aivf_authenticated"))

    @app.before_request
    def dashboard_authentication():
        path = request.path
        if path.startswith("/static/") or path in PUBLIC_PATHS:
            return None
        if authenticated():
            if request.method not in SAFE_METHODS:
                origin = request.headers.get("Origin")
                if origin and origin.rstrip("/") != request.host_url.rstrip("/"):
                    abort(403)
            return None
        if path == "/":
            return redirect(url_for("dashboard_login"))
        return ("Authentication required", 401)

    @app.route("/login", methods=["GET", "POST"])
    def dashboard_login():
        if request.method == "GET":
            return """<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>AI Video Factory Login</title><style>body{font-family:system-ui;max-width:420px;margin:10vh auto;padding:24px}input,button{width:100%;padding:12px;margin-top:10px;box-sizing:border-box}button{cursor:pointer}</style></head><body><h1>AI Video Factory</h1><p>Dashboard authentication required.</p><form method='post'><input name='token' type='password' autocomplete='current-password' placeholder='Dashboard token' required><button type='submit'>Sign in</button></form></body></html>"""

        supplied = request.form.get("token", "")
        if token and hmac.compare_digest(hashlib.sha256(supplied.encode()).digest(), hashlib.sha256(token.encode()).digest()):
            session.clear()
            session["aivf_authenticated"] = True
            return redirect(url_for("index"))
        if allow_insecure_local and supplied == "local-development":
            session.clear()
            session["aivf_authenticated"] = True
            return redirect(url_for("index"))
        return "Invalid dashboard token", 401

    @app.post("/logout")
    def dashboard_logout():
        session.clear()
        return redirect(url_for("dashboard_login"))
