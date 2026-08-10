from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user


from app.auth.face_auth import get_face_record_by_user_id
from app.auth.service import get_user_by_id
from app.users.service import set_user_active_status

users_bp = Blueprint("users", __name__, url_prefix="/users")


@users_bp.route("/<int:user_id>")
@login_required
def user_profile(user_id):
    user = get_user_by_id(user_id)

    if not user:
        flash("User not found.", "danger")
        return redirect(url_for("dashboard.home"))

    if current_user.role_name == "org_admin" and current_user.org_id != user.org_id:
        flash("Access denied.", "danger")
        return redirect(url_for("dashboard.home"))

    face_record = get_face_record_by_user_id(user_id)

    return render_template("users/profile.html", user=user, face_record=face_record)


@users_bp.route("/<int:user_id>/status", methods=["POST"])
@login_required
def update_user_status(user_id):
    user = get_user_by_id(user_id)

    if not user:
        flash("User not found.", "danger")
        return redirect(url_for("dashboard.home"))

    if current_user.role_name not in ["super_admin", "org_admin"]:
        flash("Access denied.", "danger")
        return redirect(url_for("dashboard.home"))

    if current_user.role_name == "org_admin" and current_user.org_id != user.org_id:
        flash("Access denied.", "danger")
        return redirect(url_for("dashboard.home"))

    new_status = request.form.get("is_active", "1")
    set_user_active_status(user_id, new_status == "1")

    flash("User status updated successfully.", "success")
    return redirect(url_for("users.user_profile", user_id=user_id))