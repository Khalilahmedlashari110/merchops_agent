from flask import Blueprint, jsonify, render_template, request
from flask_login import login_required

from app.a4.service import get_categories, get_style_detail, get_styles


a4_bp = Blueprint("a4", __name__, url_prefix="/a4")


@a4_bp.route("/")
@login_required
def index():
    return render_template("a4/index.html")


@a4_bp.route("/api/categories")
@login_required
def api_categories():
    try:
        return jsonify(get_categories(force_refresh=request.args.get("refresh") == "1"))
    except Exception as exc:
        return jsonify({"error": str(exc), "categories": [], "count": 0}), 502


@a4_bp.route("/api/styles")
@login_required
def api_styles():
    category_url = request.args.get("url", "")
    category_name = request.args.get("name", "")
    if not category_url:
        return jsonify({"error": "Category URL is required.", "styles": [], "count": 0}), 400
    try:
        return jsonify(
            get_styles(
                category_url,
                category_name=category_name,
                force_refresh=request.args.get("refresh") == "1",
            )
        )
    except Exception as exc:
        return jsonify({"error": str(exc), "styles": [], "count": 0}), 502


@a4_bp.route("/api/style-detail")
@login_required
def api_style_detail():
    style_url = request.args.get("url", "")
    style_code = request.args.get("code", "")
    if not style_url:
        return jsonify({"error": "Style URL is required."}), 400
    try:
        return jsonify(
            get_style_detail(
                style_url,
                style_code=style_code,
                force_refresh=request.args.get("refresh") == "1",
            )
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502
