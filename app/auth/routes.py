from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import logout_user, login_required, current_user

from app.auth.password_auth import handle_password_login
from app.auth.face_auth import register_face_from_uploaded_file, perform_face_login, delete_face_by_user_id
from app.auth.service import get_user_by_id

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.home"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = handle_password_login(username, password)

        if user:
            if user.role_name == "super_admin":
                return redirect(url_for("organization.list_organizations"))
            return redirect(url_for("dashboard.home"))

    return render_template("auth/login.html")


@auth_bp.route("/face-login", methods=["POST"])
def face_login():
    face_file = request.files.get("face_image")

    if not face_file or face_file.filename == "":
        flash("Please choose a face image.", "danger")
        return redirect(url_for("auth.login"))

    ok, result = perform_face_login(face_file)

    if not ok:
        flash(result, "danger")
        return redirect(url_for("auth.login"))

    user = result["user"]

    flash(f"Welcome, {user.full_name}. Face login successful.", "success")

    if user.role_name == "super_admin":
        return redirect(url_for("organization.list_organizations"))

    return redirect(url_for("dashboard.home"))


@auth_bp.route("/register-face/<int:user_id>", methods=["GET", "POST"])
@login_required
def register_face(user_id):
    user = get_user_by_id(user_id)

    if not user:
        flash("User not found.", "danger")
        return redirect(url_for("dashboard.home"))

    if current_user.role_name == "org_admin" and current_user.org_id != user.org_id:
        flash("Access denied.", "danger")
        return redirect(url_for("dashboard.home"))

    if request.method == "POST":
        face_file = request.files.get("face_image")

        if not face_file or face_file.filename == "":
            flash("Please choose a face image.", "danger")
            return render_template("auth/register_face.html", user=user)

        ok, message = register_face_from_uploaded_file(user.id, face_file)

        if ok:
            flash(message, "success")
            return redirect(url_for("users.user_profile", user_id=user.id))

        flash(message, "danger")

    return render_template("auth/register_face.html", user=user)


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect("/")


@auth_bp.route("/me")
@login_required
def me():
    return {
        "id": current_user.id,
        "name": current_user.full_name,
        "username": current_user.username,
        "org_id": current_user.org_id,
        "role": current_user.role_name,
    }

@auth_bp.route("/face-login-api", methods=["POST"])
def face_login_api():
    face_file = request.files.get("face_image")

    if not face_file:
        return {"success": False, "message": "No image received.", "confidence": 0}

    ok, result = perform_face_login(face_file)

    if not ok:
        return {
            "success": False,
            "message": result.get("message", "Face login failed."),
            "confidence": result.get("confidence", 0),
            "distance": result.get("distance")
        }

    user = result["user"]

    return {
        "success": True,
        "message": f"Welcome {user.full_name}",
        "confidence": result.get("confidence", 0),
        "distance": result.get("distance"),
        "user": {
            "name": user.full_name,
            "role": user.role_name
        },
        "redirect": url_for("organization.list_organizations")
        if user.role_name == "super_admin"
        else url_for("dashboard.home")
    }

@auth_bp.route("/delete-face/<int:user_id>", methods=["POST"])
@login_required
def delete_face(user_id):
    user = get_user_by_id(user_id)

    if not user:
        flash("User not found.", "danger")
        return redirect(url_for("dashboard.home"))

    if current_user.role_name == "org_admin" and current_user.org_id != user.org_id:
        flash("Access denied.", "danger")
        return redirect(url_for("dashboard.home"))

    if current_user.role_name not in ["super_admin", "org_admin"]:
        flash("Access denied.", "danger")
        return redirect(url_for("dashboard.home"))

    delete_face_by_user_id(user_id)
    flash("Face data deleted successfully.", "success")
    return redirect(url_for("users.user_profile", user_id=user_id))

