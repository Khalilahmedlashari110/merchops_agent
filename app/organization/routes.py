from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from app.organization.service import (
    get_all_organizations,
    create_organization,
    get_organization_by_id
)
from app.users.service import create_org_admin_or_user, get_users_by_org, get_users_by_org_with_face_status
organization_bp = Blueprint("organization", __name__, url_prefix="/organizations")


def super_admin_required():
    return current_user.is_authenticated and current_user.role_name == "super_admin"


def org_admin_or_super_required():
    return current_user.is_authenticated and current_user.role_name in ["super_admin", "org_admin"]


@organization_bp.route("/")
@login_required
def list_organizations():
    if not super_admin_required():
        flash("Access denied.", "danger")
        return redirect(url_for("dashboard.home"))

    orgs = get_all_organizations()
    return render_template("organization/list.html", orgs=orgs)


@organization_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_organization():
    if not super_admin_required():
        flash("Access denied.", "danger")
        return redirect(url_for("dashboard.home"))

    if request.method == "POST":
        create_organization(
            name=request.form.get("name", "").strip(),
            code=request.form.get("code", "").strip().upper(),
            db_server=request.form.get("db_server", "").strip(),
            db_name=request.form.get("db_name", "").strip(),
            db_driver=request.form.get("db_driver", "").strip() or "ODBC Driver 17 for SQL Server",
            email=request.form.get("email", "").strip(),
            smtp_server=request.form.get("smtp_server", "").strip(),
            smtp_port=int(request.form.get("smtp_port", "0") or 0),
            email_password=request.form.get("email_password", "").strip()
        )
        flash("Organization created successfully.", "success")
        return redirect(url_for("organization.list_organizations"))

    return render_template("organization/new.html")


@organization_bp.route("/<int:org_id>/users", methods=["GET", "POST"])
@login_required
def organization_users(org_id):
    if not org_admin_or_super_required():
        flash("Access denied.", "danger")
        return redirect(url_for("dashboard.home"))

    if current_user.role_name == "org_admin" and current_user.org_id != org_id:
        flash("Access denied.", "danger")
        return redirect(url_for("dashboard.home"))

    org = get_organization_by_id(org_id)

    if not org:
        flash("Organization not found.", "danger")
        return redirect(url_for("organization.list_organizations"))

    if request.method == "POST":
        role_name = request.form.get("role_name", "user").strip()

        if current_user.role_name == "org_admin" and role_name == "super_admin":
            role_name = "user"

        create_org_admin_or_user(
            org_id=org_id,
            full_name=request.form.get("full_name", "").strip(),
            email=request.form.get("email", "").strip(),
            username=request.form.get("username", "").strip(),
            password=request.form.get("password", "").strip(),
            role_name=role_name
        )
        flash("User created successfully.", "success")
        return redirect(url_for("organization.organization_users", org_id=org_id))

    users = get_users_by_org_with_face_status(org_id, include_inactive=True)
    
    return render_template("organization/users.html", org=org, users=users)

#Organization Details Page
@organization_bp.route("/<int:org_id>")
@login_required
def organization_detail(org_id):
    if current_user.role_name != "super_admin":
        flash("Access denied.", "danger")
        return redirect(url_for("dashboard.home"))

    org = get_organization_by_id(org_id)

    if not org:
        flash("Organization not found.", "danger")
        return redirect(url_for("organization.list_organizations"))

    users = get_users_by_org_with_face_status(org_id, include_inactive=True)

    return render_template("organization/detail.html", org=org, users=users)