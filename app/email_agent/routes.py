from email.utils import parsedate_to_datetime
from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user

from app.email_agent.service import process_all_active_accounts
from app.email_agent.db_service import (
    get_email_logs,
    get_email_drafts,
    get_email_draft_by_id,
    update_email_draft,
    get_email_account_by_id,
    mark_email_draft_sent,
    get_recent_notifications,
    get_email_response_analysis,
)
from app.email_agent.mailer import send_html_email
from app.email_agent.account_service import (
    get_email_accounts,
    get_organizations,
    get_users_by_org,
    create_email_account,
    update_email_account,
    delete_email_account,
)
from app.email_agent.sender_service import (
    get_unregistered_senders,
    get_approved_senders,
    get_approved_sender_by_id,
    approve_unregistered_sender,
    get_available_inventory_tables,
    add_approved_sender,
    delete_approved_sender,
    add_sender_table,
    remove_sender_table,
    toggle_sender_active,
)
email_agent_bp = Blueprint("email_agent", __name__, url_prefix="/email-agent")


@email_agent_bp.route("/inbox")
@login_required
def inbox():
    def _date_key(e):
        try:
            return parsedate_to_datetime(e.get("date") or "")
        except Exception:
            from datetime import datetime, timezone
            return datetime.min.replace(tzinfo=timezone.utc)

    try:
        data = process_all_active_accounts()
        registered_emails = []
        unregistered_emails = []

        for acc in data:
            for e in acc["emails"]:
                if e.get("approved_sender"):
                    registered_emails.append(e)
                else:
                    unregistered_emails.append(e)

        registered_emails.sort(key=_date_key, reverse=True)
        unregistered_emails.sort(key=_date_key, reverse=True)

    except Exception as e:
        registered_emails = []
        unregistered_emails = []
        flash(str(e), "danger")

    return render_template(
        "email/inbox.html",
        registered_emails=registered_emails,
        unregistered_emails=unregistered_emails,
    )


@email_agent_bp.route("/notifications/json")
@login_required
def notifications_json():
    org_id = current_user.org_id if current_user.org_id else None
    try:
        rows = get_recent_notifications(org_id=org_id, limit=8)
    except Exception:
        rows = []
    return jsonify({"count": len(rows), "recent": rows})


@email_agent_bp.route("/email/<mail_id>")
@login_required
def email_detail(mail_id):
    try:
        data = process_all_active_accounts()
        selected = None

        for acc in data:
            for e in acc["emails"]:
                if str(e["mail_id"]) == str(mail_id):
                    selected = e
                    break

        if not selected:
            flash("Email not found.", "warning")
            return redirect(url_for("email_agent.inbox"))

        return render_template("email/email_detail.html", email_item=selected)

    except Exception as e:
        flash(str(e), "danger")
        return redirect(url_for("email_agent.inbox"))


@email_agent_bp.route("/drafts")
@login_required
def drafts():
    try:
        drafts = get_email_drafts(limit=200)
    except Exception as e:
        drafts = []
        flash(str(e), "danger")

    return render_template("email/drafts.html", drafts=drafts)


@email_agent_bp.route("/draft/<int:draft_id>", methods=["GET", "POST"])
@login_required
def draft_detail(draft_id):
    draft = get_email_draft_by_id(draft_id)

    if not draft:
        flash("Draft not found.", "warning")
        return redirect(url_for("email_agent.drafts"))

    if request.method == "POST":
        recipient_email = request.form.get("recipient_email", "").strip()
        subject_line = request.form.get("subject_line", "").strip()
        reply_body = request.form.get("reply_body", "").strip()

        try:
            update_email_draft(
                draft_id=draft_id,
                recipient_email=recipient_email,
                subject_line=subject_line,
                reply_body=reply_body
            )
            flash("Draft updated successfully.", "success")
            return redirect(url_for("email_agent.draft_detail", draft_id=draft_id))
        except Exception as e:
            flash(str(e), "danger")

    draft = get_email_draft_by_id(draft_id)
    return render_template("email/draft_detail.html", draft=draft)


@email_agent_bp.route("/draft/<int:draft_id>/send", methods=["POST"])
@login_required
def send_draft(draft_id):
    draft = get_email_draft_by_id(draft_id)

    if not draft:
        flash("Draft not found.", "warning")
        return redirect(url_for("email_agent.drafts"))

    if str(draft.get("status")) == "Sent":
        flash("This draft has already been sent.", "warning")
        return redirect(url_for("email_agent.draft_detail", draft_id=draft_id))

    account = get_email_account_by_id(draft["email_account_id"])
    if not account:
        flash("Linked email account not found.", "danger")
        return redirect(url_for("email_agent.draft_detail", draft_id=draft_id))

    try:
        send_html_email(
            smtp_server=account["smtp_server"],
            smtp_port=int(account["smtp_port"]),
            sender_email=account["email_address"],
            sender_password=account["email_password"],
            recipient_email=draft["recipient_email"],
            subject=draft["subject_line"],
            html_body=draft["reply_body"]
        )

        mark_email_draft_sent(draft_id)
        flash("Draft sent successfully.", "success")

    except Exception as e:
        flash(str(e), "danger")

    return redirect(url_for("email_agent.draft_detail", draft_id=draft_id))


@email_agent_bp.route("/monitor")
@login_required
def monitor():
    try:
        logs = get_email_logs(limit=200)
        analysis = get_email_response_analysis(
            limit=10,
            org_id=current_user.org_id if current_user.org_id else None,
            reminder_hours=24,
        )
    except Exception as e:
        logs = []
        analysis = {
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
        flash(str(e), "danger")

    return render_template("email/monitor.html", logs=logs, analysis=analysis)


@email_agent_bp.route("/accounts")
@login_required
def accounts():
    try:
        accounts = get_email_accounts()
    except Exception as e:
        accounts = []
        flash(str(e), "danger")

    return render_template("email/accounts.html", accounts=accounts)


@email_agent_bp.route("/accounts/new", methods=["GET", "POST"])
@login_required
def account_new():
    organizations = get_organizations()
    users = get_users_by_org()

    if request.method == "POST":
        try:
            org_id = int(request.form.get("org_id"))
            user_id_raw = request.form.get("user_id", "").strip()

            data = {
                "org_id": org_id,
                "user_id": int(user_id_raw) if user_id_raw else None,
                "account_name": request.form.get("account_name", "").strip(),
                "email_address": request.form.get("email_address", "").strip(),
                "email_password": request.form.get("email_password", "").strip(),
                "smtp_server": request.form.get("smtp_server", "").strip(),
                "smtp_port": int(request.form.get("smtp_port", 587)),
                "imap_server": request.form.get("imap_server", "").strip(),
                "imap_port": int(request.form.get("imap_port", 993)),
                "provider": request.form.get("provider", "custom").strip(),
                "auto_reply_enabled": 1 if request.form.get("auto_reply_enabled") == "on" else 0,
                "check_interval_minutes": int(request.form.get("check_interval_minutes", 5)),
                "is_active": 1 if request.form.get("is_active") == "on" else 0,
            }

            create_email_account(data)
            flash("Email account registered successfully.", "success")
            return redirect(url_for("email_agent.accounts"))

        except Exception as e:
            flash(str(e), "danger")

    return render_template(
        "email/account_form.html",
        mode="new",
        account=None,
        organizations=organizations,
        users=users,
    )


@email_agent_bp.route("/accounts/<int:account_id>/edit", methods=["GET", "POST"])
@login_required
def account_edit(account_id):
    account = get_email_account_by_id(account_id)
    if not account:
        flash("Email account not found.", "warning")
        return redirect(url_for("email_agent.accounts"))

    organizations = get_organizations()
    users = get_users_by_org(account.get("org_id"))

    if request.method == "POST":
        try:
            org_id = int(request.form.get("org_id"))
            user_id_raw = request.form.get("user_id", "").strip()

            data = {
                "org_id": org_id,
                "user_id": int(user_id_raw) if user_id_raw else None,
                "account_name": request.form.get("account_name", "").strip(),
                "email_address": request.form.get("email_address", "").strip(),
                "email_password": request.form.get("email_password", "").strip(),
                "smtp_server": request.form.get("smtp_server", "").strip(),
                "smtp_port": int(request.form.get("smtp_port", 587)),
                "imap_server": request.form.get("imap_server", "").strip(),
                "imap_port": int(request.form.get("imap_port", 993)),
                "provider": request.form.get("provider", "custom").strip(),
                "auto_reply_enabled": 1 if request.form.get("auto_reply_enabled") == "on" else 0,
                "check_interval_minutes": int(request.form.get("check_interval_minutes", 5)),
                "is_active": 1 if request.form.get("is_active") == "on" else 0,
            }

            update_email_account(account_id, data)
            flash("Email account updated successfully.", "success")
            return redirect(url_for("email_agent.accounts"))

        except Exception as e:
            flash(str(e), "danger")

    return render_template(
        "email/account_form.html",
        mode="edit",
        account=account,
        organizations=organizations,
        users=users,
    )


@email_agent_bp.route("/accounts/<int:account_id>/delete", methods=["POST"])
@login_required
def account_delete(account_id):
    try:
        delete_email_account(account_id)
        flash("Email account deleted successfully.", "success")
    except Exception as e:
        flash(str(e), "danger")

    return redirect(url_for("email_agent.accounts"))

@email_agent_bp.route("/unregistered")
@login_required
def unregistered():
    try:
        rows = get_unregistered_senders()
    except Exception as e:
        rows = []
        flash(str(e), "danger")

    return render_template("email/unregistered.html", rows=rows)


@email_agent_bp.route("/approved-senders")
@login_required
def approved_senders():
    is_super_admin = getattr(current_user, "role_name", "") == "super_admin"
    can_manage_senders = getattr(current_user, "role_name", "") in ["super_admin", "org_admin"]
    org_id = None if is_super_admin else getattr(current_user, "org_id", None)
    try:
        rows = get_approved_senders(org_id=org_id) if (is_super_admin or org_id) else []
    except Exception as e:
        rows = []
        flash(str(e), "danger")

    available_tables = []
    organizations = []
    if can_manage_senders:
        try:
            available_tables = get_available_inventory_tables()
        except Exception as e:
            flash(f"Could not load live tables: {e}", "warning")
    if is_super_admin:
        try:
            organizations = get_organizations()
        except Exception as e:
            flash(f"Could not load organizations: {e}", "warning")

    return render_template(
        "email/approved_senders.html",
        rows=rows,
        available_tables=available_tables,
        organizations=organizations,
        is_super_admin=is_super_admin,
        can_manage_senders=can_manage_senders,
    )


@email_agent_bp.route("/approved-senders/add", methods=["POST"])
@login_required
def approved_sender_add():
    if getattr(current_user, "role_name", "") not in ["super_admin", "org_admin"]:
        flash("Only admins can add approved senders.", "danger")
        return redirect(url_for("email_agent.approved_senders"))

    sender_email = (request.form.get("sender_email") or "").strip().lower()
    sender_name = (request.form.get("sender_name") or "").strip()
    org_id = request.form.get("org_id") if getattr(current_user, "role_name", "") == "super_admin" else getattr(current_user, "org_id", None)

    if not org_id:
        flash("Choose an organization before adding the sender.", "warning")
        return redirect(url_for("email_agent.approved_senders"))
    if "@" not in sender_email or "." not in sender_email.split("@")[-1]:
        flash("Enter a valid sender email address.", "warning")
        return redirect(url_for("email_agent.approved_senders"))

    try:
        add_approved_sender(int(org_id), sender_email, sender_name)
        flash(f"{sender_email} added to approved senders.", "success")
    except Exception as e:
        flash(str(e), "danger")

    return redirect(url_for("email_agent.approved_senders"))


@email_agent_bp.route("/approved-senders/<int:sender_id>/delete", methods=["POST"])
@login_required
def approved_sender_delete(sender_id):
    if getattr(current_user, "role_name", "") not in ["super_admin", "org_admin"]:
        flash("Only admins can delete approved senders.", "danger")
        return redirect(url_for("email_agent.approved_senders"))

    try:
        org_id = None if getattr(current_user, "role_name", "") == "super_admin" else getattr(current_user, "org_id", None)
        if delete_approved_sender(sender_id, org_id=org_id):
            flash("Approved sender deleted.", "success")
        else:
            flash("Approved sender not found.", "warning")
    except Exception as e:
        flash(str(e), "danger")

    return redirect(url_for("email_agent.approved_senders"))


def _validate_table_name(table_name):
    """Return True if table_name exists on the live server (whitelist check)."""
    try:
        allowed = {t["table"] for t in get_available_inventory_tables()}
        return table_name in allowed
    except Exception:
        return False


@email_agent_bp.route("/approved-senders/<int:sender_id>/tables/add", methods=["POST"])
@login_required
def sender_table_add(sender_id):
    if getattr(current_user, "role_name", "") not in ["super_admin", "org_admin"]:
        flash("Only admins can assign inventory tables.", "danger")
        return redirect(url_for("email_agent.approved_senders"))

    org_id = None if getattr(current_user, "role_name", "") == "super_admin" else getattr(current_user, "org_id", None)
    sender = get_approved_sender_by_id(sender_id, org_id=org_id)
    if not sender:
        flash("Approved sender not found for your organization.", "danger")
        return redirect(url_for("email_agent.approved_senders"))

    table_name = request.form.get("table_name", "").strip()
    if not table_name:
        flash("No table selected.", "warning")
        return redirect(url_for("email_agent.approved_senders"))

    if not _validate_table_name(table_name):
        flash("Invalid table — not found on connected server.", "danger")
        return redirect(url_for("email_agent.approved_senders"))

    try:
        add_sender_table(sender_id, table_name)
        flash(f"Table '{table_name}' added.", "success")
    except Exception as e:
        flash(str(e), "danger")

    return redirect(url_for("email_agent.approved_senders"))


@email_agent_bp.route("/approved-senders/<int:sender_id>/tables/remove", methods=["POST"])
@login_required
def sender_table_remove(sender_id):
    if getattr(current_user, "role_name", "") not in ["super_admin", "org_admin"]:
        flash("Only admins can remove inventory tables.", "danger")
        return redirect(url_for("email_agent.approved_senders"))

    org_id = None if getattr(current_user, "role_name", "") == "super_admin" else getattr(current_user, "org_id", None)
    sender = get_approved_sender_by_id(sender_id, org_id=org_id)
    if not sender:
        flash("Approved sender not found for your organization.", "danger")
        return redirect(url_for("email_agent.approved_senders"))

    table_name = request.form.get("table_name", "").strip()
    if not table_name:
        flash("No table specified.", "warning")
        return redirect(url_for("email_agent.approved_senders"))

    try:
        remove_sender_table(sender_id, table_name)
        flash(f"Table '{table_name}' removed.", "success")
    except Exception as e:
        flash(str(e), "danger")

    return redirect(url_for("email_agent.approved_senders"))


@email_agent_bp.route("/approved-senders/<int:sender_id>/toggle", methods=["POST"])
@login_required
def toggle_sender(sender_id):
    if getattr(current_user, "role_name", "") != "super_admin":
        flash("Only super admins can change sender status.", "danger")
        return redirect(url_for("email_agent.approved_senders"))

    try:
        toggle_sender_active(sender_id)
        flash("Sender status updated.", "success")
    except Exception as e:
        flash(str(e), "danger")

    return redirect(url_for("email_agent.approved_senders"))


@email_agent_bp.route("/unregistered/<int:record_id>/approve", methods=["POST"])
@login_required
def approve_sender(record_id):
    try:
        ok = approve_unregistered_sender(record_id)
        if ok:
            flash("Sender approved successfully.", "success")
        else:
            flash("Sender record not found.", "warning")
    except Exception as e:
        flash(str(e), "danger")

    return redirect(url_for("email_agent.unregistered"))
