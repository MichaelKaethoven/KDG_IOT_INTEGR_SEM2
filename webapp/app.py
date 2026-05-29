import os
from dotenv import load_dotenv

load_dotenv()

from flask import Flask
from extensions import csrf, limiter


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = os.environ["SECRET_KEY"]
    app.config["GRAFANA_URL"] = os.environ.get("GRAFANA_URL", "http://localhost:3001")

    csrf.init_app(app)
    limiter.init_app(app)

    from blueprints.auth import auth_bp
    from blueprints.dashboard import dashboard_bp
    from blueprints.customers import customers_bp
    from blueprints.orders import orders_bp
    from blueprints.trackers import trackers_bp
    from blueprints.settings import settings_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(customers_bp, url_prefix="/customers")
    app.register_blueprint(orders_bp, url_prefix="/orders")
    app.register_blueprint(trackers_bp, url_prefix="/trackers")
    app.register_blueprint(settings_bp, url_prefix="/settings")

    return app


if __name__ == "__main__":
    port = int(os.environ.get("WEBAPP_PORT", 8080))
    app = create_app()
    app.run(host="0.0.0.0", port=port)
