#!/usr/bin/env python3
"""
DocTracker – local tracker for documents and their expiry dates.

Run:
    python app.py

Access at:  http://127.0.0.1:5004

The app never reads the scans themselves.  It stores only metadata (who,
what, issue/expiry dates, last 4 characters of the number) plus a Google
Drive link; clicking the link opens the scan in Drive under your normal
Google login.
"""

import os

from flask import Flask, abort, request
from werkzeug.middleware.proxy_fix import ProxyFix

PORT = 5004

# Requests must address the app by one of these names.  Rejecting anything
# else blocks DNS-rebinding attacks, where a malicious site points its own
# hostname at 127.0.0.1 to read this app from your browser.
#
# EXTRA_HOSTS (comma-separated, set by start-all.ps1) adds this machine's
# Tailscale names/IP and Wi-Fi IP, so the phone can reach it too.
HOSTNAMES = ["127.0.0.1", "localhost"] + [
    h.strip() for h in os.environ.get("EXTRA_HOSTS", "").split(",") if h.strip()
]
ALLOWED_HOSTS = {f"{h}:{PORT}" for h in HOSTNAMES}
ALLOWED_ORIGINS = {f"http://{h}" for h in ALLOWED_HOSTS}



def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    # Behind the login gateway (dashboard/gateway/gateway.py) the app lives under a path
    # prefix such as /bdays; X-Forwarded-Prefix makes url_for() include it.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=0, x_proto=0, x_host=0, x_port=0, x_prefix=1)

    app.secret_key = os.environ.get("SECRET_KEY") or os.urandom(32)

    from routes.documents import docs_bp
    from services.expiry import fmt_date

    app.register_blueprint(docs_bp)
    app.add_template_filter(fmt_date, "fmt_date")

    @app.before_request
    def guard_request():
        if request.host not in ALLOWED_HOSTS:
            abort(400)
        # Any website you visit can make your browser POST to localhost, so
        # refuse writes that don't come from this app's own pages.  Modern
        # browsers say so via Sec-Fetch-Site; Origin is the fallback (it can
        # legitimately be "null" on same-origin posts, so it isn't trusted
        # when Sec-Fetch-Site is present).
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            fetch_site = request.headers.get("Sec-Fetch-Site")
            if fetch_site is not None:
                if fetch_site not in ("same-origin", "none"):
                    abort(403)
            else:
                origin = request.headers.get("Origin")
                if origin is not None and origin not in ALLOWED_ORIGINS:
                    abort(403)

    @app.after_request
    def security_headers(resp):
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "frame-ancestors 'none'; "
            "form-action 'self'; base-uri 'none'"
        )
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        # same-origin, not no-referrer: with no-referrer Chrome sends
        # "Origin: null" on this app's own form posts.  Outbound links (Drive)
        # still get no referrer either way.
        resp.headers["Referrer-Policy"] = "same-origin"
        resp.headers["Cache-Control"] = "no-store"
        return resp

    return app


if __name__ == "__main__":
    app = create_app()
    # debug stays off: the Werkzeug debugger is a remote-code console.
    app.run(host="127.0.0.1", port=PORT, debug=False)
