from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required

from app.alerts.service import (
    generate_alerts_from_latest_batches,
    get_inventory_alerts,
    resolve_inventory_alert,
    get_alert_summary,
)

alerts_bp = Blueprint("alerts", __name__, url_prefix="/alerts")


@alerts_bp.route("/")
@login_required
def index():
    show_resolved = request.args.get("show_resolved", "0") == "1"

    alerts = get_inventory_alerts(show_resolved=show_resolved)
    summary = get_alert_summary(alerts)

    return render_template(
        "alerts/index.html",
        alerts=alerts,
        summary=summary,
        show_resolved=show_resolved,
        last_sync=datetime.now().strftime("%d-%b-%Y %I:%M %p"),
    )


@alerts_bp.route("/generate", methods=["POST"])
@login_required
def generate():
    result = generate_alerts_from_latest_batches()

    if result["success"]:
        flash(result["message"], "success")
    else:
        flash(result["message"], "warning")

    return redirect(url_for("alerts.index"))


@alerts_bp.route("/resolve/<int:alert_id>", methods=["POST"])
@login_required
def resolve(alert_id):
    try:
        resolve_inventory_alert(alert_id)
        flash("Alert resolved successfully.", "success")
    except Exception as e:
        flash(str(e), "danger")

    return redirect(url_for("alerts.index"))