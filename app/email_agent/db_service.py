from app.database.connection_manager import get_master_connection


def is_email_already_drafted(external_message_id):
    if not external_message_id:
        return False
    conn = get_master_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*)
        FROM khPriority.dbo.EmailAgentMessageLog l
        INNER JOIN khPriority.dbo.EmailAgentDrafts d
            ON l.id = d.log_id
        WHERE l.external_message_id = ?
    """, external_message_id)
    row = cursor.fetchone()
    conn.close()
    return (row[0] > 0) if row else False


def get_active_email_accounts():
    conn = get_master_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            ea.id,
            ea.org_id,
            ea.user_id,
            ea.account_name,
            ea.email_address,
            ea.email_password,
            ea.smtp_server,
            ea.smtp_port,
            ea.imap_server,
            ea.imap_port,
            ea.provider,
            ea.auto_reply_enabled,
            ea.check_interval_minutes,
            o.name AS organization_name
        FROM khPriority.dbo.OrganizationEmailAccounts ea
        LEFT JOIN khPriority.dbo.Organizations o
            ON ea.org_id = o.id
        WHERE ea.is_active = 1
          AND ea.auto_reply_enabled = 1
    """)

    columns = [c[0] for c in cursor.description]
    rows = cursor.fetchall()
    conn.close()

    return [dict(zip(columns, row)) for row in rows]


def save_incoming_email_log(
    org_id,
    user_id,
    email_account_id,
    external_message_id,
    sender_email,
    subject_line,
    body_text,
    detected_intent,
    matched_skus,
    auto_reply_generated,
    reply_subject,
    reply_body,
):
    conn = get_master_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO khPriority.dbo.EmailAgentMessageLog (
            org_id,
            user_id,
            email_account_id,
            external_message_id,
            sender_email,
            subject_line,
            body_text,
            detected_intent,
            matched_skus,
            auto_reply_generated,
            reply_subject,
            reply_body,
            status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        org_id,
        user_id,
        email_account_id,
        external_message_id,
        sender_email,
        subject_line,
        body_text,
        detected_intent,
        matched_skus,
        1 if auto_reply_generated else 0,
        reply_subject,
        reply_body,
        "Received"
    ))

    conn.commit()

    cursor.execute("SELECT @@IDENTITY")
    row = cursor.fetchone()
    conn.close()

    return int(row[0]) if row else None


def update_reply_log(log_id, auto_reply_sent=False, status="Processed"):
    conn = get_master_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE khPriority.dbo.EmailAgentMessageLog
        SET auto_reply_sent = ?,
            status = ?
        WHERE id = ?
    """, (
        1 if auto_reply_sent else 0,
        status,
        log_id
    ))

    conn.commit()
    conn.close()


def get_recent_notifications(org_id=None, limit=8):
    conn = get_master_connection()
    cursor = conn.cursor()
    if org_id:
        cursor.execute(f"""
            SELECT TOP {limit}
                l.id,
                l.sender_email,
                l.subject_line,
                l.detected_intent,
                l.created_at,
                d.id AS draft_id
            FROM khPriority.dbo.EmailAgentMessageLog l
            LEFT JOIN khPriority.dbo.EmailAgentDrafts d ON l.id = d.log_id
            INNER JOIN khPriority.dbo.EmailAgentApprovedSenders s
                ON l.org_id = s.org_id
                AND LOWER(LTRIM(RTRIM(l.sender_email))) = LOWER(LTRIM(RTRIM(s.sender_email)))
                AND s.is_active = 1
            WHERE l.org_id = ?
            ORDER BY l.created_at DESC
        """, org_id)
    else:
        cursor.execute(f"""
            SELECT TOP {limit}
                l.id,
                l.sender_email,
                l.subject_line,
                l.detected_intent,
                l.created_at,
                d.id AS draft_id
            FROM khPriority.dbo.EmailAgentMessageLog l
            LEFT JOIN khPriority.dbo.EmailAgentDrafts d ON l.id = d.log_id
            INNER JOIN khPriority.dbo.EmailAgentApprovedSenders s
                ON l.org_id = s.org_id
                AND LOWER(LTRIM(RTRIM(l.sender_email))) = LOWER(LTRIM(RTRIM(s.sender_email)))
                AND s.is_active = 1
            ORDER BY l.created_at DESC
        """)
    columns = [c[0] for c in cursor.description]
    rows = cursor.fetchall()
    conn.close()
    result = []
    for row in rows:
        r = dict(zip(columns, row))
        if r.get('created_at') and hasattr(r['created_at'], 'strftime'):
            r['created_at'] = r['created_at'].strftime('%Y-%m-%dT%H:%M:%S')
        result.append(r)
    return result


def get_email_logs(limit=200):
    conn = get_master_connection()
    cursor = conn.cursor()

    cursor.execute(f"""
        SELECT TOP {limit}
            l.id,
            l.sender_email,
            l.subject_line,
            l.detected_intent,
            l.matched_skus,
            l.auto_reply_generated,
            l.auto_reply_sent,
            l.status,
            l.created_at,
            o.name as organization_name
        FROM khPriority.dbo.EmailAgentMessageLog l
        LEFT JOIN khPriority.dbo.Organizations o
            ON l.org_id = o.id
        ORDER BY l.created_at DESC
    """)

    columns = [c[0] for c in cursor.description]
    rows = cursor.fetchall()
    conn.close()

    return [dict(zip(columns, row)) for row in rows]


def get_email_response_analysis(limit=8, org_id=None, reminder_hours=24):
    limit = max(1, min(int(limit or 8), 50))
    reminder_hours = max(1, int(reminder_hours or 24))

    conn = get_master_connection()
    cursor = conn.cursor()

    where_sql = "WHERE l.org_id = ?" if org_id else ""
    params = [org_id] if org_id else []

    cursor.execute(f"""
        SELECT
            COUNT(*) AS total_received,
            SUM(CASE WHEN d.id IS NOT NULL THEN 1 ELSE 0 END) AS responses_prepared,
            SUM(CASE WHEN ISNULL(d.status, '') = 'Sent' OR ISNULL(l.auto_reply_sent, 0) = 1 THEN 1 ELSE 0 END) AS responses_sent,
            SUM(CASE WHEN d.id IS NOT NULL AND ISNULL(d.status, '') <> 'Sent' THEN 1 ELSE 0 END) AS drafts_waiting,
            SUM(CASE WHEN d.id IS NULL AND ISNULL(l.auto_reply_sent, 0) = 0 THEN 1 ELSE 0 END) AS no_response,
            SUM(CASE
                    WHEN ISNULL(l.auto_reply_sent, 0) = 0
                     AND (d.id IS NULL OR ISNULL(d.status, '') <> 'Sent')
                     AND DATEDIFF(hour, l.created_at, GETDATE()) >= ?
                    THEN 1 ELSE 0
                END) AS overdue,
            SUM(CASE WHEN l.detected_intent IN ('inventory', 'data_request') THEN 1 ELSE 0 END) AS inventory_requests
        FROM khPriority.dbo.EmailAgentMessageLog l
        LEFT JOIN khPriority.dbo.EmailAgentDrafts d
            ON l.id = d.log_id
        INNER JOIN khPriority.dbo.EmailAgentApprovedSenders s
            ON l.org_id = s.org_id
            AND LOWER(LTRIM(RTRIM(l.sender_email))) = LOWER(LTRIM(RTRIM(s.sender_email)))
            AND s.is_active = 1
        {where_sql}
    """, *([reminder_hours] + params))

    summary_cols = [c[0] for c in cursor.description]
    summary_row = cursor.fetchone()
    summary = dict(zip(summary_cols, summary_row)) if summary_row else {}

    row_params = [reminder_hours] + params
    cursor.execute(f"""
        SELECT TOP {limit}
            l.id,
            l.sender_email,
            l.subject_line,
            l.detected_intent,
            l.created_at,
            DATEDIFF(hour, l.created_at, GETDATE()) AS age_hours,
            d.id AS draft_id,
            d.status AS draft_status,
            d.sent_at,
            o.name AS organization_name,
            CASE
                WHEN ISNULL(d.status, '') = 'Sent' OR ISNULL(l.auto_reply_sent, 0) = 1
                    THEN 'Already answered'
                WHEN d.id IS NOT NULL AND ISNULL(d.status, '') <> 'Sent'
                    THEN 'Review and send the prepared draft'
                WHEN DATEDIFF(hour, l.created_at, GETDATE()) >= ?
                    THEN 'Reminder: prepare a response now'
                WHEN l.detected_intent IN ('inventory', 'data_request')
                    THEN 'Create an inventory reply'
                ELSE 'Review and decide if a response is needed'
            END AS recommendation
        FROM khPriority.dbo.EmailAgentMessageLog l
        LEFT JOIN khPriority.dbo.EmailAgentDrafts d
            ON l.id = d.log_id
        INNER JOIN khPriority.dbo.EmailAgentApprovedSenders s
            ON l.org_id = s.org_id
            AND LOWER(LTRIM(RTRIM(l.sender_email))) = LOWER(LTRIM(RTRIM(s.sender_email)))
            AND s.is_active = 1
        LEFT JOIN khPriority.dbo.Organizations o
            ON l.org_id = o.id
        {where_sql}
          {"AND" if where_sql else "WHERE"} ISNULL(l.auto_reply_sent, 0) = 0
          AND (d.id IS NULL OR ISNULL(d.status, '') <> 'Sent')
        ORDER BY
            CASE WHEN DATEDIFF(hour, l.created_at, GETDATE()) >= ? THEN 0 ELSE 1 END,
            l.created_at ASC
    """, *(row_params + [reminder_hours]))

    columns = [c[0] for c in cursor.description]
    rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
    conn.close()

    total = int(summary.get("total_received") or 0)
    sent = int(summary.get("responses_sent") or 0)
    waiting = int(summary.get("drafts_waiting") or 0)
    no_response = int(summary.get("no_response") or 0)
    overdue = int(summary.get("overdue") or 0)
    response_rate = round((sent / total) * 100, 1) if total else 0

    recommendations = []
    if overdue:
        recommendations.append(f"{overdue} email(s) are past the {reminder_hours} hour reminder window.")
    if waiting:
        recommendations.append(f"{waiting} prepared draft(s) are waiting to be sent.")
    if no_response:
        recommendations.append(f"{no_response} received email(s) do not have a prepared response yet.")
    if total and response_rate < 80:
        recommendations.append("Response completion is below 80%; review pending mail before new polling cycles.")
    if not recommendations:
        recommendations.append("No urgent follow-up needed right now.")

    return {
        "summary": {
            "total_received": total,
            "responses_prepared": int(summary.get("responses_prepared") or 0),
            "responses_sent": sent,
            "drafts_waiting": waiting,
            "no_response": no_response,
            "overdue": overdue,
            "inventory_requests": int(summary.get("inventory_requests") or 0),
            "response_rate": response_rate,
            "reminder_hours": reminder_hours,
        },
        "pending": rows,
        "recommendations": recommendations,
    }


def save_email_draft(log_id, org_id, user_id, email_account_id, recipient_email, subject_line, reply_body):
    conn = get_master_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO khPriority.dbo.EmailAgentDrafts (
            log_id,
            org_id,
            user_id,
            email_account_id,
            recipient_email,
            subject_line,
            reply_body,
            status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        log_id,
        org_id,
        user_id,
        email_account_id,
        recipient_email,
        subject_line,
        reply_body,
        "Draft"
    ))

    conn.commit()
    cursor.execute("SELECT @@IDENTITY")
    row = cursor.fetchone()
    conn.close()

    return int(row[0]) if row else None


def get_email_drafts(limit=200):
    conn = get_master_connection()
    cursor = conn.cursor()

    cursor.execute(f"""
        SELECT TOP {limit}
            d.id,
            d.log_id,
            d.recipient_email,
            d.subject_line,
            d.reply_body,
            d.status,
            d.created_at,
            o.name AS organization_name,
            s.sender_name
        FROM khPriority.dbo.EmailAgentDrafts d
        LEFT JOIN khPriority.dbo.Organizations o
            ON d.org_id = o.id
        INNER JOIN khPriority.dbo.EmailAgentApprovedSenders s
            ON d.org_id = s.org_id
            AND LOWER(LTRIM(RTRIM(d.recipient_email))) = LOWER(LTRIM(RTRIM(s.sender_email)))
            AND s.is_active = 1
        ORDER BY d.created_at DESC, d.id DESC
    """)

    columns = [c[0] for c in cursor.description]
    rows = cursor.fetchall()
    conn.close()

    return [dict(zip(columns, row)) for row in rows]


def get_email_draft_by_id(draft_id):
    conn = get_master_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            d.id,
            d.log_id,
            d.org_id,
            d.user_id,
            d.email_account_id,
            d.recipient_email,
            d.subject_line,
            d.reply_body,
            d.status,
            d.created_at,
            d.sent_at,
            o.name AS organization_name
        FROM khPriority.dbo.EmailAgentDrafts d
        LEFT JOIN khPriority.dbo.Organizations o
            ON d.org_id = o.id
        WHERE d.id = ?
    """, draft_id)

    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    columns = [
        "id", "log_id", "org_id", "user_id", "email_account_id",
        "recipient_email", "subject_line", "reply_body", "status",
        "created_at", "sent_at", "organization_name"
    ]
    return dict(zip(columns, row))

def update_email_draft(draft_id, recipient_email, subject_line, reply_body):
    conn = get_master_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE khPriority.dbo.EmailAgentDrafts
        SET recipient_email = ?,
            subject_line = ?,
            reply_body = ?,
            updated_at = GETDATE()
        WHERE id = ?
    """, (
        recipient_email,
        subject_line,
        reply_body,
        draft_id
    ))

    conn.commit()
    conn.close()

def mark_email_draft_sent(draft_id):
    conn = get_master_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE khPriority.dbo.EmailAgentDrafts
        SET status = 'Sent',
            sent_at = GETDATE(),
            updated_at = GETDATE()
        WHERE id = ?
    """, draft_id)

    conn.commit()
    conn.close()


def get_distinct_colours():
    conn = get_master_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DISTINCT LOWER(LTRIM(RTRIM(Colour)))
        FROM Proline.dbo.MerStyleMasterDetail
        WHERE Colour IS NOT NULL
          AND ColourDiscontinue = 0
          AND BodyCombo IN ('Body Fabric', 'Combo A')
        ORDER BY 1
    """)
    rows = cursor.fetchall()
    conn.close()
    return [r[0] for r in rows if r[0]]


def get_distinct_sizes():
    conn = get_master_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DISTINCT LOWER(LTRIM(RTRIM(SSize)))
        FROM Proline.dbo.MerStyleMasterDetail
        WHERE SSize IS NOT NULL
          AND ColourDiscontinue = 0
          AND BodyCombo IN ('Body Fabric', 'Combo A')
        ORDER BY 1
    """)
    rows = cursor.fetchall()
    conn.close()
    return [r[0] for r in rows if r[0]]


def get_email_account_by_id(email_account_id):
    conn = get_master_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            id,
            org_id,
            user_id,
            account_name,
            email_address,
            email_password,
            smtp_server,
            smtp_port,
            imap_server,
            imap_port,
            provider,
            auto_reply_enabled,
            check_interval_minutes
        FROM khPriority.dbo.OrganizationEmailAccounts
        WHERE id = ?
    """, email_account_id)

    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    columns = [
        "id", "org_id", "user_id", "account_name", "email_address",
        "email_password", "smtp_server", "smtp_port", "imap_server",
        "imap_port", "provider", "auto_reply_enabled", "check_interval_minutes"
    ]
    return dict(zip(columns, row))
