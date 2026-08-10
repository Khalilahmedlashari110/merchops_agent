from flask import Flask, redirect, url_for, request
from flask_login import current_user
from .extensions import init_extensions


def create_app():
    app = Flask(__name__)
    app.config.from_object("config.Config")

    init_extensions(app)

    def whole_number(value):
        try:
            return f"{float(value or 0):,.0f}"
        except (TypeError, ValueError):
            return "0"

    app.jinja_env.filters["whole_number"] = whole_number

    @app.before_request
    def gate_unauthenticated():
        open_prefixes = ("auth.", "static")
        open_endpoints = ("lan_health",)
        if request.endpoint is None:
            return
        if request.endpoint in open_endpoints:
            return
        if any(request.endpoint.startswith(p) for p in open_prefixes):
            return
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))

    from app.auth.routes import auth_bp
    from app.dashboard.routes import dashboard_bp
    from app.organization.routes import organization_bp
    from app.users.routes import users_bp
    from app.email_agent.routes import email_agent_bp
    from app.data_chatbot.routes import data_chatbot_bp
    from app.inventory.routes import inventory_bp
    from app.ralawise.routes import ralawise_bp
    from app.a4.routes import a4_bp
    from app.email_agent.scheduler import start_email_scheduler

    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(organization_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(email_agent_bp)
    app.register_blueprint(data_chatbot_bp)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(ralawise_bp)
    app.register_blueprint(a4_bp)

    start_email_scheduler()
   
    return app
