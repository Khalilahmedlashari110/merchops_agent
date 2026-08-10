from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required

from app.carrier.service import (
    RAW_EXTENSIONS,
    backfill_actual_billing_fdm4_details,
    backfill_actual_billing_invoice_months,
    backfill_actual_billing_tracking_numbers,
    backfill_actual_billing_total_charged,
    combine_ups_folder,
    empty_billing_analysis,
    empty_ups_billing_report,
    get_ups_billing_analysis,
    get_ups_billing_report,
    load_actual_billing_path,
    load_actual_billing_upload,
    normalize_ups_report_keys,
    upload_actual_billing_rows,
    upload_ups_rows,
)
from app.carrier.smart_audit import DEFAULT_UPS_CONTRACT_PATH, run_smart_audit


carrier_bp = Blueprint("carrier", __name__, url_prefix="/carrier")


@carrier_bp.route("/ups", methods=["GET", "POST"])
@login_required
def ups():
    if request.method == "POST":
        folder_path = (request.form.get("raw_folder") or "").strip()
        if folder_path:
            session["ups_raw_folder"] = folder_path
            flash("UPS raw-data folder saved.", "success")
        else:
            session.pop("ups_raw_folder", None)
            flash("UPS raw-data folder cleared.", "info")
        return redirect(url_for("carrier.ups"))

    folder_path = session.get("ups_raw_folder", "")
    actual_billing_path = session.get("ups_actual_billing_path", "")
    combined = {
        "files": [],
        "rows": [],
        "columns": [],
        "errors": [],
        "total_size_kb": 0,
    }
    actual_billing = {
        "rows": [],
        "columns": [],
        "errors": [],
        "source_file": actual_billing_path,
    }
    if folder_path:
        combined = combine_ups_folder(folder_path, max_rows=100)
    try:
        billing_analysis = get_ups_billing_analysis()
    except Exception as exc:
        billing_analysis = empty_billing_analysis(str(exc))

    return render_template(
        "carrier/ups.html",
        folder_path=folder_path,
        actual_billing_path=actual_billing_path,
        raw_files=combined["files"],
        preview_rows=combined["rows"][:100],
        preview_columns=combined["columns"][:30],
        actual_preview_rows=actual_billing["rows"][:100],
        actual_preview_columns=actual_billing["columns"][:30],
        actual_total_rows=len(actual_billing["rows"]),
        actual_total_columns=max(0, len(actual_billing["columns"]) - 2),
        actual_billing_errors=actual_billing["errors"],
        actual_billing_source_file=actual_billing["source_file"],
        billing_analysis=billing_analysis,
        total_rows=len(combined["rows"]),
        total_columns=max(0, len(combined["columns"]) - 2),
        scan_errors=combined["errors"],
        total_size_kb=combined["total_size_kb"],
        allowed_extensions=sorted(ext.lstrip(".").upper() for ext in RAW_EXTENSIONS),
    )


@carrier_bp.route("/ups/actual-billing-path", methods=["POST"])
@login_required
def save_actual_billing_path():
    file_path = (request.form.get("actual_billing_path") or "").strip()
    if file_path:
        session["ups_actual_billing_path"] = file_path
        flash("UPS actual billing file path saved.", "success")
    else:
        session.pop("ups_actual_billing_path", None)
        flash("UPS actual billing file path cleared.", "info")
    return redirect(url_for("carrier.ups"))


@carrier_bp.route("/ups/upload-actual-billing", methods=["POST"])
@login_required
def upload_actual_billing():
    uploaded_file = request.files.get("actual_billing_file")
    file_path = session.get("ups_actual_billing_path", "")

    if uploaded_file and uploaded_file.filename:
        actual_billing = load_actual_billing_upload(uploaded_file)
    elif file_path:
        actual_billing = load_actual_billing_path(file_path)
    else:
        flash("Choose an actual billing CSV/Excel file or save a readable file path first.", "warning")
        return redirect(url_for("carrier.ups"))

    if actual_billing["errors"]:
        flash("Fix actual billing file read errors before uploading.", "danger")
        return redirect(url_for("carrier.ups"))
    if not actual_billing["rows"]:
        flash("No actual billing rows were found to upload.", "warning")
        return redirect(url_for("carrier.ups"))

    try:
        user_id = int(current_user.id) if str(getattr(current_user, "id", "")).isdigit() else None
        batch_id = upload_actual_billing_rows(
            actual_billing["rows"],
            source_file=actual_billing["source_file"],
            uploaded_by=user_id,
        )
        backfill_actual_billing_invoice_months()
        normalize_ups_report_keys()
        flash(f"UPS actual billing uploaded successfully. Batch: {batch_id}", "success")
    except Exception as exc:
        flash(f"UPS actual billing upload failed: {exc}", "danger")

    return redirect(url_for("carrier.ups"))


@carrier_bp.route("/ups/refresh-report", methods=["POST"])
@login_required
def refresh_ups_report():
    try:
        backfill_actual_billing_total_charged()
        backfill_actual_billing_tracking_numbers()
        backfill_actual_billing_invoice_months()
        normalize_ups_report_keys()
        fdm4_updated = backfill_actual_billing_fdm4_details()
        flash(f"UPS report indexes refreshed successfully. FDM4 details updated on {fdm4_updated:,} row(s).", "success")
    except Exception as exc:
        flash(f"UPS report refresh failed: {exc}", "danger")
    next_url = request.form.get("next") or request.args.get("next")
    if next_url and next_url.startswith("/carrier/"):
        return redirect(next_url)
    return redirect(url_for("carrier.ups", tab="billing"))


@carrier_bp.route("/ups/backfill-fdm4-details", methods=["POST"])
@login_required
def backfill_ups_fdm4_details():
    try:
        normalize_ups_report_keys()
        updated_count = backfill_actual_billing_fdm4_details()
        flash(f"FDM4 receiver, postal, state, and billed weight details updated on {updated_count:,} row(s).", "success")
    except Exception as exc:
        flash(f"FDM4 detail update failed: {exc}", "danger")
    next_url = request.form.get("next") or request.args.get("next")
    if next_url and next_url.startswith("/carrier/"):
        return redirect(next_url)
    return redirect(url_for("carrier.ups", tab="billing"))


@carrier_bp.route("/ups/billing-report")
@login_required
def ups_billing_report():
    try:
        report = get_ups_billing_report()
    except Exception as exc:
        report = empty_ups_billing_report(str(exc))
    return render_template("carrier/ups_billing_report.html", report=report)


@carrier_bp.route("/ups/smart-audit", methods=["GET", "POST"])
@login_required
def ups_smart_audit():
    origin_zip = session.get("ups_audit_origin_zip", "10001")
    contract_path = session.get("ups_audit_contract_path", DEFAULT_UPS_CONTRACT_PATH)
    limit = int(session.get("ups_audit_limit", 250))
    use_ai = False
    report = None

    if request.method == "POST":
        origin_zip = (request.form.get("origin_zip") or "").strip() or origin_zip
        contract_path = (request.form.get("contract_path") or "").strip()
        limit = int(request.form.get("limit") or 250)
        limit = max(25, min(limit, 2000))
        use_ai = request.form.get("use_ai") == "1"
        session["ups_audit_origin_zip"] = origin_zip
        session["ups_audit_contract_path"] = contract_path
        session["ups_audit_limit"] = limit

    try:
        report = run_smart_audit(
            origin_zip=origin_zip,
            contract_path=contract_path,
            limit=limit,
            use_ai=use_ai,
        )
    except Exception as exc:
        report = {
            "origin_zip": origin_zip,
            "contract_path": contract_path,
            "contract_error": None,
            "contract_loaded": False,
            "contract_rules": {"rule_count": 0},
            "counters": {
                "total": 0,
                "ok": 0,
                "billed_tested": 0,
                "correct": 0,
                "overbilled": 0,
                "underbilled": 0,
                "need_contract_rate": 0,
                "need_billing_match": 0,
                "skipped_zero": 0,
                "billing_exceptions": 0,
                "zone_review": 0,
                "missing_zip": 0,
                "missing_weight": 0,
                "missing_charge": 0,
            },
            "rows": [],
            "billing_exceptions": [],
            "ai_summary": "",
            "ai_error": str(exc),
        }

    return render_template("carrier/ups_smart_audit.html", report=report, limit=limit)


@carrier_bp.route("/ups/upload", methods=["POST"])
@login_required
def upload_ups():
    folder_path = session.get("ups_raw_folder", "")
    if not folder_path:
        flash("Set the UPS raw-data folder before uploading.", "warning")
        return redirect(url_for("carrier.ups"))

    combined = combine_ups_folder(folder_path)
    if combined["errors"]:
        flash("Fix file read errors before uploading UPS data.", "danger")
        return redirect(url_for("carrier.ups"))
    if not combined["rows"]:
        flash("No UPS rows were found to upload.", "warning")
        return redirect(url_for("carrier.ups"))

    try:
        user_id = int(current_user.id) if str(getattr(current_user, "id", "")).isdigit() else None
        batch_id = upload_ups_rows(folder_path, combined["rows"], uploaded_by=user_id)
        normalize_ups_report_keys()
        flash(f"UPS data uploaded successfully. Batch: {batch_id}", "success")
    except Exception as exc:
        flash(f"UPS upload failed: {exc}", "danger")

    return redirect(url_for("carrier.ups"))
