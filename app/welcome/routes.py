from flask import Blueprint, render_template, request, jsonify, redirect, url_for
from flask_login import current_user

from app.welcome.service import (
    recognize_face,
    save_visitor,
    chat_with_aria,
    get_all_visitors,
)

welcome_bp = Blueprint("welcome", __name__, url_prefix="/welcome")


@welcome_bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.home"))
    return render_template("welcome/welcome.html")


@welcome_bp.route("/api/recognize", methods=["POST"])
def api_recognize():
    data = request.get_json(silent=True) or {}
    image_b64 = data.get("image")
    if not image_b64:
        return jsonify({"recognized": False})

    visitor_id, name = recognize_face(image_b64)
    if name:
        return jsonify({"recognized": True, "name": name, "visitor_id": visitor_id})
    return jsonify({"recognized": False})


@welcome_bp.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    visitor_name = data.get("visitor_name")
    history = data.get("history") or []

    if not message:
        return jsonify({"reply": ""})

    reply = chat_with_aria(message, visitor_name=visitor_name, history=history)
    return jsonify({"reply": reply})


@welcome_bp.route("/api/save-visitor", methods=["POST"])
def api_save_visitor():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    image_b64 = data.get("image")

    if not name:
        return jsonify({"success": False, "error": "Name is required"})

    visitor_id = save_visitor(name, image_b64)
    return jsonify({"success": True, "visitor_id": visitor_id, "name": name})


@welcome_bp.route("/api/history")
def api_history():
    return jsonify(get_all_visitors())
