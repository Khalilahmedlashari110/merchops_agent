import json
import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from flask import Blueprint, flash, jsonify, redirect, render_template, request, send_file, session, url_for
from flask_login import current_user, login_required

from app.data_chatbot.service import (
    assign_table,
    build_chat_response,
    discover_tables,
    ensure_chatbot_tables,
    export_path,
    get_assignment_rows,
    get_assigned_tables,
    get_chatbot_users,
    remove_table,
)


data_chatbot_bp = Blueprint("data_chatbot", __name__, url_prefix="/data-chatbot")
HISTORY_DIR = Path(__file__).resolve().parents[2] / "data" / "chatbot_history"


def history_file_path():
    raw_user_id = re.sub(r"[^0-9a-zA-Z_-]", "", str(current_user.id))
    conversation_id = session.get("data_chatbot_conversation_id")
    if not conversation_id or not re.match(r"^[a-f0-9]{32}$", str(conversation_id)):
        conversation_id = uuid.uuid4().hex
        session["data_chatbot_conversation_id"] = conversation_id
        session.modified = True
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    return HISTORY_DIR / f"{raw_user_id}_{conversation_id}.json"


def load_chat_history():
    path = history_file_path()
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_chat_history(history):
    path = history_file_path()
    with path.open("w", encoding="utf-8") as handle:
        json.dump(make_json_safe((history or [])[-20:]), handle, ensure_ascii=True)


def make_json_safe(value):
    if isinstance(value, dict):
        return {str(key): make_json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [make_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [make_json_safe(item) for item in value]
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def compact_response_snapshot(result):
    rows = result.get("rows") or []
    columns = result.get("columns") or []
    return {
        "answer": result.get("answer") or "",
        "rows": make_json_safe(rows[:40]),
        "columns": make_json_safe(columns),
        "chart": make_json_safe(result.get("chart")),
        "sql": result.get("sql") or "",
        "export_id": result.get("export_id"),
        "row_count": result.get("row_count") or len(rows),
        "shown_count": min(result.get("shown_count") or len(rows), 40),
    }


@data_chatbot_bp.route("/")
@login_required
def index():
    ensure_chatbot_tables()
    return render_template(
        "data_chatbot/index.html",
        assigned_tables=get_assigned_tables(user_id=current_user.id),
        chat_history=load_chat_history(),
    )


def admin_required():
    return current_user.is_authenticated and current_user.role_name in ["super_admin", "org_admin"]


@data_chatbot_bp.route("/assignments")
@login_required
def assignments():
    if not admin_required():
        flash("Only admins can manage chatbot table assignments.", "warning")
        return redirect(url_for("data_chatbot.index"))
    search = (request.args.get("search") or "").strip()
    selected_user_id = (request.args.get("user_id") or "").strip()
    ensure_chatbot_tables()
    users = get_chatbot_users(current_user)
    if selected_user_id and selected_user_id not in {str(user["id"]) for user in users}:
        selected_user_id = ""
    return render_template(
        "data_chatbot/assignments.html",
        assigned_tables=get_assignment_rows(current_user),
        available_tables=discover_tables(search),
        users=users,
        search=search,
        selected_user_id=selected_user_id,
    )


@data_chatbot_bp.route("/assign", methods=["POST"])
@login_required
def assign():
    if not admin_required():
        flash("Only admins can assign chatbot tables.", "warning")
        return redirect(url_for("data_chatbot.index"))
    table_name = (request.form.get("table_name") or "").strip()
    display_name = (request.form.get("display_name") or "").strip()
    user_id = (request.form.get("user_id") or "").strip()
    allowed_users = {str(user["id"]) for user in get_chatbot_users(current_user)}
    if user_id and user_id not in allowed_users:
        flash("That user is not available for your admin scope.", "danger")
        return redirect(url_for("data_chatbot.assignments"))
    if table_name:
        assign_table(table_name, display_name, user_id=user_id, assigned_by_user_id=current_user.id)
        flash(f"Assigned table {table_name} to the selected chatbot user.", "success")
    return redirect(url_for("data_chatbot.assignments", user_id=user_id))


@data_chatbot_bp.route("/remove", methods=["POST"])
@login_required
def remove():
    if not admin_required():
        flash("Only admins can remove chatbot table assignments.", "warning")
        return redirect(url_for("data_chatbot.index"))
    table_name = (request.form.get("table_name") or "").strip()
    user_id = (request.form.get("user_id") or "").strip()
    if table_name:
        remove_table(table_name, user_id=user_id)
        flash(f"Removed table {table_name} from chatbot access.", "success")
    return redirect(url_for("data_chatbot.assignments"))


@data_chatbot_bp.route("/chat", methods=["POST"])
@login_required
def chat():
    payload = request.get_json(silent=True) or {}
    message = (payload.get("message") or "").strip()
    if not message:
        return jsonify({"success": False, "message": "Please type a question."}), 400
    try:
        history = load_chat_history()
        result = build_chat_response(message, user_id=current_user.id, history=history)
        history.append({"role": "user", "content": message})
        history.append({
            "role": "assistant",
            "content": result.get("answer") or "",
            "response": compact_response_snapshot(result),
        })
        save_chat_history(history)
        result["success"] = True
        return jsonify(result)
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@data_chatbot_bp.route("/history/clear", methods=["POST"])
@login_required
def clear_history():
    path = history_file_path()
    if path.exists():
        path.unlink()
    session.pop("data_chatbot_conversation_id", None)
    session.modified = True
    return jsonify({"success": True})


@data_chatbot_bp.route("/download/<export_id>")
@login_required
def download(export_id):
    path = export_path(export_id)
    if not path:
        flash("Export file was not found. Please generate a new answer.", "warning")
        return redirect(url_for("data_chatbot.index"))
    return send_file(
        path,
        as_attachment=True,
        download_name="data_chatbot_result.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
