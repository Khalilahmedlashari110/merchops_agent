from datetime import datetime

from flask import render_template

from app.database.connection_manager import get_master_connection
from app.inventory.service import get_latest_presentation_batch, get_top_high_sales_risky_inventory
from app.email_agent.mailer import send_html_email


def get_email_settings_for_org(org_id=None):
    conn = get_master_connection()
    cursor = conn.cursor()

    if org_id:
        cursor.execute("""
            SELECT TOP 1 email, smtp_server, smtp_port, email_password
            FROM Organizations
            WHERE id = ?
        """, org_id)
    else:
        cursor.execute("""
            SELECT TOP 1 email, smtp_server, smtp_port, email_password
            FROM Organizations
            WHERE email IS NOT NULL
            ORDER BY id
        """)

    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    return {
        "email": row.email,
        "smtp_server": row.smtp_server,
        "smtp_port": row.smtp_port,
        "email_password": row.email_password,
    }


def log_email_alert(alert_type, recipient_email, subject_line, batch_id, total_rows, status="Sent", remarks=None):
    conn = get_master_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO khPriority.dbo.InventoryEmailAlertLog (
            alert_type,
            recipient_email,
            subject_line,
            batch_id,
            total_rows,
            status,
            remarks
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        alert_type,
        recipient_email,
        subject_line,
        batch_id,
        total_rows,
        status,
        remarks
    ))

    conn.commit()
    conn.close()


def build_top_risky_email_html(rows, alert_type="Daily"):
    return render_template(
        "email/top_risky_alert.html",
        rows=rows,
        alert_type=alert_type,
        generated_at=datetime.now().strftime("%d-%b-%Y %I:%M %p")
    )


def send_top_risky_inventory_email(recipient_email, org_id=None, alert_type="Daily"):
    batch_id = get_latest_presentation_batch()
    rows = get_top_high_sales_risky_inventory(batch_id=batch_id, limit=50)

    if not rows:
        return {
            "success": False,
            "message": "No risky inventory rows found for email."
        }

    settings = get_email_settings_for_org(org_id)
    if not settings:
        return {
            "success": False,
            "message": "Email settings not found."
        }

    subject = f"{alert_type} Inventory Alert - Top Risky High-Sales SKUs"
    html_body = build_top_risky_email_html(rows, alert_type=alert_type)

    try:
        send_html_email(
            smtp_server=settings["smtp_server"],
            smtp_port=int(settings["smtp_port"]),
            sender_email=settings["email"],
            sender_password=settings["email_password"],
            recipient_email=recipient_email,
            subject=subject,
            html_body=html_body
        )

        log_email_alert(
            alert_type=alert_type,
            recipient_email=recipient_email,
            subject_line=subject,
            batch_id=batch_id,
            total_rows=len(rows),
            status="Sent"
        )

        return {
            "success": True,
            "message": f"{alert_type} email alert sent successfully.",
            "rows": len(rows)
        }

    except Exception as e:
        log_email_alert(
            alert_type=alert_type,
            recipient_email=recipient_email,
            subject_line=subject,
            batch_id=batch_id,
            total_rows=len(rows),
            status="Failed",
            remarks=str(e)
        )

        return {
            "success": False,
            "message": str(e)
        }