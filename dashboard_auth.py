"""Authentication and request-hardening for the single-user dashboard."""
import hashlib
import hmac
import os

from flask import abort, redirect, request, session, url_for


SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
PUBLIC_PATHS = {"/login", "/logout", "/api/health"}


def configure_dashboard_auth(app):
    # Avoid double registration when a development/test harness imports the WSGI module repeatedly.
    if app.config.get("_AIVF_AUTH_CONFIGURED"):
        return
    app.config["_AIVF_AUTH_CONFIGURED"] = True

    token = os.environ.get("AIVF_DASHBOARD_TOKEN", "").strip()
    allow_insecure_local = os.environ.get("AIVF_ALLOW_INSECURE_LOCAL", "0") == "1"
    if not token and not allow_insecure_local:
        app.logger.warning("AIVF_DASHBOARD_TOKEN is unset; dashboard access will fail closed")

    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_SECURE=os.environ.get("AIVF_COOKIE_SECURE", "0") == "1",
    )

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; media-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
            "base-uri 'self'; form-action 'self'"
        )
        return response

    @app.before_request
    def dashboard_authentication():
        path = request.path
        if path.startswith("/static/") or path in PUBLIC_PATHS:
            return None
        if session.get("aivf_authenticated"):
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
        valid = bool(token) and hmac.compare_digest(
            hashlib.sha256(supplied.encode()).digest(), hashlib.sha256(token.encode()).digest()
        )
        if valid or (allow_insecure_local and supplied == "local-development"):
            session.clear()
            session["aivf_authenticated"] = True
            return redirect(url_for("index"))
        return "Invalid dashboard token", 401

    @app.post("/logout")
    def dashboard_logout():
        session.clear()
        return redirect(url_for("dashboard_login"))
