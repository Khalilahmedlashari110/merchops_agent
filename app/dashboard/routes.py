import os
import time

import anthropic
from flask import Blueprint, jsonify, render_template, redirect, url_for
from flask_login import login_required, current_user

from app.inventory.service import get_top_high_sales_risky_inventory
from app.email_agent.db_service import get_email_response_analysis

dashboard_bp = Blueprint("dashboard", __name__)

# Cache for 60 s — aligns with Anthropic's per-minute rate-limit window
_credits_cache: dict = {"data": None, "ts": 0.0}
_CACHE_TTL = 60


@dashboard_bp.route("/")
def home():
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))
    top_sales_rows = []
    try:
        top_sales_rows = get_top_high_sales_risky_inventory()
    except Exception:
        top_sales_rows = []

    try:
        email_analysis = get_email_response_analysis(
            limit=6,
            org_id=current_user.org_id if current_user.org_id else None,
            reminder_hours=24,
        )
    except Exception:
        email_analysis = {
            "summary": {
                "total_received": 0,
                "responses_prepared": 0,
                "responses_sent": 0,
                "drafts_waiting": 0,
                "no_response": 0,
                "overdue": 0,
                "inventory_requests": 0,
                "response_rate": 0,
                "reminder_hours": 24,
            },
            "pending": [],
            "recommendations": ["Email response analysis is temporarily unavailable."],
        }

    return render_template(
        "dashboard/home.html",
        top_sales_rows=top_sales_rows,
        email_analysis=email_analysis,
    )


@dashboard_bp.route("/api/credits")
@login_required
def api_credits():
    """Return live Anthropic rate-limit quota read from response headers.
    Uses a 1-token Haiku call (cheapest model) and caches for 60 s."""
    now = time.time()
    if _credits_cache["data"] and (now - _credits_cache["ts"]) < _CACHE_TTL:
        return jsonify(_credits_cache["data"])

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    try:
        client = anthropic.Anthropic(api_key=api_key)
        raw = client.messages.with_raw_response.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1,
            messages=[{"role": "user", "content": "1"}],
        )
        h = dict(raw.headers)
        data = {
            "status": "ok",
            "requests_limit":          h.get("anthropic-ratelimit-requests-limit"),
            "requests_remaining":      h.get("anthropic-ratelimit-requests-remaining"),
            "requests_reset":          h.get("anthropic-ratelimit-requests-reset"),
            "tokens_limit":            h.get("anthropic-ratelimit-tokens-limit"),
            "tokens_remaining":        h.get("anthropic-ratelimit-tokens-remaining"),
            "tokens_reset":            h.get("anthropic-ratelimit-tokens-reset"),
            "input_tokens_limit":      h.get("anthropic-ratelimit-input-tokens-limit"),
            "input_tokens_remaining":  h.get("anthropic-ratelimit-input-tokens-remaining"),
            "output_tokens_limit":     h.get("anthropic-ratelimit-output-tokens-limit"),
            "output_tokens_remaining": h.get("anthropic-ratelimit-output-tokens-remaining"),
            "cached_at": int(now),
        }
        _credits_cache["data"] = data
        _credits_cache["ts"]   = now
        return jsonify(data)

    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500
