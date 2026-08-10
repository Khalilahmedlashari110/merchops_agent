from flask import Blueprint, jsonify, render_template, request
from flask_login import login_required

from app.ralawise.service import get_brands, get_style_detail, get_styles


ralawise_bp = Blueprint("ralawise", __name__, url_prefix="/ralawise")


@ralawise_bp.route("/")
@login_required
def index():
    return render_template("ralawise/index.html")


@ralawise_bp.route("/api/brands")
@login_required
def api_brands():
    try:
        return jsonify(get_brands(force_refresh=request.args.get("refresh") == "1"))
    except Exception as exc:
        return jsonify({"error": str(exc), "brands": [], "count": 0}), 502


@ralawise_bp.route("/api/styles")
@login_required
def api_styles():
    brand_url = request.args.get("url", "")
    brand_name = request.args.get("name", "")
    if not brand_url:
        return jsonify({"error": "Brand URL is required.", "styles": [], "count": 0}), 400
    try:
        return jsonify(
            get_styles(
                brand_url,
                brand_name=brand_name,
                force_refresh=request.args.get("refresh") == "1",
            )
        )
    except Exception as exc:
        return jsonify({"error": str(exc), "styles": [], "count": 0}), 502


@ralawise_bp.route("/api/style-detail")
@login_required
def api_style_detail():
    style_code = request.args.get("code", "")
    style_url = request.args.get("url", "")
    if not style_code:
        return jsonify({"error": "Style code is required."}), 400
    try:
        return jsonify(
            get_style_detail(
                style_code,
                style_url=style_url,
                force_refresh=request.args.get("refresh") == "1",
            )
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502
