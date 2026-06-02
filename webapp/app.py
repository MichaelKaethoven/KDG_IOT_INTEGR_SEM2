import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

from flask import Flask, render_template
from extensions import csrf, limiter


# CSP source list. Grafana is reverse-proxied under same-origin /grafana, so
# 'self' covers the iframe. Bootstrap + Bootstrap Icons load from jsdelivr.
# 'unsafe-inline' is needed because templates use inline event handlers
# (onchange="this.form.submit()") and inline style attributes throughout.
_CDN = "https://cdn.jsdelivr.net"
_CSP = "; ".join([
    "default-src 'self'",
    f"script-src 'self' {_CDN} 'unsafe-inline'",
    f"style-src 'self' {_CDN} 'unsafe-inline'",
    f"font-src 'self' {_CDN} data:",
    "img-src 'self' data:",
    "frame-src 'self'",
    "frame-ancestors 'self'",
    "base-uri 'self'",
    "form-action 'self'",
    "connect-src 'self'",
    "object-src 'none'",
])


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def create_app() -> Flask:
    app = Flask(__name__)
    secret_key = os.environ["SECRET_KEY"]
    # Catch the .env.example placeholder and obviously-weak keys before they
    # ship to production. Treat short/known values as a hard error in production.
    if len(secret_key) < 32 or secret_key.lower().startswith("change-me"):
        if os.environ.get("FLASK_ENV") == "production" or os.environ.get("FLY_APP_NAME"):
            raise RuntimeError(
                "SECRET_KEY is too weak. Generate with: "
                "python -c \"import secrets; print(secrets.token_hex(32))\""
            )
    app.secret_key = secret_key

    app.config.update(
        SESSION_COOKIE_SECURE=_env_bool("SESSION_COOKIE_SECURE", True),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    )

    csrf.init_app(app)
    limiter.init_app(app)

    from blueprints.auth import auth_bp
    from blueprints.dashboard import dashboard_bp
    from blueprints.customers import customers_bp
    from blueprints.orders import orders_bp
    from blueprints.trackers import trackers_bp
    from blueprints.settings import settings_bp
    from blueprints.grafana_proxy import grafana_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(customers_bp, url_prefix="/customers")
    app.register_blueprint(orders_bp, url_prefix="/orders")
    app.register_blueprint(trackers_bp, url_prefix="/trackers")
    app.register_blueprint(settings_bp, url_prefix="/settings")
    app.register_blueprint(grafana_bp)
    # The proxy forwards Grafana's own API calls (JSON POSTs etc.); CSRF is
    # enforced on the portal's own forms, not on proxied Grafana traffic.
    csrf.exempt(grafana_bp)
    # A single Grafana dashboard load fans out into dozens of proxied sub-requests
    # (JS bundles, datasource queries, the auto-refresh), so the global 200/day
    # default limit is exhausted almost immediately ("Too Many Requests"). The
    # proxy is already gated by login_required, so it is not an open abuse vector —
    # exempt it from rate limiting; the portal's own routes keep the default.
    limiter.exempt(grafana_bp)

    @app.after_request
    def _security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        if app.config["SESSION_COOKIE_SECURE"]:
            resp.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        # Grafana's own responses come back through the /grafana proxy. The
        # embedded UI relies on inline scripts/styles and websockets we cannot
        # tighten further; leave the proxy responses as Grafana returned them.
        if not resp.headers.get("Content-Security-Policy") \
                and not _is_proxy_response(resp):
            resp.headers["Content-Security-Policy"] = _CSP
        return resp

    @app.errorhandler(404)
    def _not_found(_e):
        return render_template("error.html", code=404, message="Not found"), 404

    @app.errorhandler(500)
    def _server_error(_e):
        return render_template("error.html", code=500, message="Server error"), 500

    return app


def _is_proxy_response(resp) -> bool:
    # Grafana iframe payloads come back via the grafana_proxy blueprint; they
    # are not HTML our templates produced, so don't overwrite their headers.
    from flask import request
    return request.path.startswith("/grafana")


if __name__ == "__main__":
    port = int(os.environ.get("WEBAPP_PORT", 8080))
    app = create_app()
    app.run(host="0.0.0.0", port=port)
