from app.database.connection_manager import get_master_connection


def normalize_email(email):
    return str(email or "").strip().lower()


# ── Schema bootstrap ──────────────────────────────────────────────────────────

def _ensure_sender_tables_table():
    """Create EmailAgentSenderTables (many-to-many sender → table) if absent."""
    conn = get_master_connection()
    cursor = conn.cursor()
    cursor.execute("""
        IF NOT EXISTS (
            SELECT 1 FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_NAME = 'EmailAgentSenderTables'
        )
        CREATE TABLE khPriority.dbo.EmailAgentSenderTables (
            id          INT IDENTITY(1,1) PRIMARY KEY,
            sender_id   INT          NOT NULL,
            table_name  NVARCHAR(256) NOT NULL,
            assigned_at DATETIME     DEFAULT GETDATE(),
            CONSTRAINT UQ_SenderTable UNIQUE (sender_id, table_name)
        )
    """)
    conn.commit()
    conn.close()


_tables_table_ensured = False


def _ensure_once():
    global _tables_table_ensured
    if not _tables_table_ensured:
        _ensure_sender_tables_table()
        _tables_table_ensured = True


# ── Live table discovery ───────────────────────────────────────────────────────

def get_available_inventory_tables():
    """Return every base table on the live connected server (all schemas)."""
    conn = get_master_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT TABLE_SCHEMA, TABLE_NAME
        FROM khPriority.INFORMATION_SCHEMA.TABLES
        WHERE TABLE_TYPE = 'BASE TABLE'
        ORDER BY TABLE_SCHEMA, TABLE_NAME
    """)
    rows = cursor.fetchall()
    conn.close()
    return [{"schema": r[0], "table": r[1], "full_name": f"{r[0]}.{r[1]}"} for r in rows]


# ── Sender table assignments ───────────────────────────────────────────────────

def get_sender_tables(sender_id):
    """Return list of table_name strings assigned to this sender."""
    _ensure_once()
    conn = get_master_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT table_name
        FROM khPriority.dbo.EmailAgentSenderTables
        WHERE sender_id = ?
        ORDER BY assigned_at
    """, sender_id)
    rows = cursor.fetchall()
    conn.close()
    return [r[0] for r in rows]


def add_sender_table(sender_id, table_name):
    """Assign a table to a sender (idempotent)."""
    _ensure_once()
    conn = get_master_connection()
    cursor = conn.cursor()
    cursor.execute("""
        IF NOT EXISTS (
            SELECT 1 FROM khPriority.dbo.EmailAgentSenderTables
            WHERE sender_id = ? AND table_name = ?
        )
        INSERT INTO khPriority.dbo.EmailAgentSenderTables (sender_id, table_name)
        VALUES (?, ?)
    """, sender_id, table_name, sender_id, table_name)
    conn.commit()
    conn.close()


def remove_sender_table(sender_id, table_name):
    """Remove a table assignment from a sender."""
    _ensure_once()
    conn = get_master_connection()
    cursor = conn.cursor()
    cursor.execute("""
        DELETE FROM khPriority.dbo.EmailAgentSenderTables
        WHERE sender_id = ? AND table_name = ?
    """, sender_id, table_name)
    conn.commit()
    conn.close()


# ── Core sender queries ────────────────────────────────────────────────────────

def is_sender_approved(org_id, sender_email):
    sender_email = normalize_email(sender_email)
    conn = get_master_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT TOP 1 id
        FROM khPriority.dbo.EmailAgentApprovedSenders
        WHERE org_id = ?
          AND LOWER(LTRIM(RTRIM(sender_email))) = ?
          AND is_active = 1
    """, org_id, sender_email)
    row = cursor.fetchone()
    conn.close()
    return row is not None


def get_sender_by_email(org_id, sender_email):
    """Return full approved sender record including assigned tables, or None."""
    sender_email = normalize_email(sender_email)
    conn = get_master_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT *
        FROM khPriority.dbo.EmailAgentApprovedSenders
        WHERE org_id = ?
          AND LOWER(LTRIM(RTRIM(sender_email))) = ?
          AND is_active = 1
    """, org_id, sender_email)
    columns = [c[0] for c in cursor.description]
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    record = dict(zip(columns, row))
    record["tables"] = get_sender_tables(record["id"])
    return record


def get_approved_sender_by_id(sender_id, org_id=None):
    conn = get_master_connection()
    cursor = conn.cursor()
    if org_id:
        cursor.execute("""
            SELECT *
            FROM khPriority.dbo.EmailAgentApprovedSenders
            WHERE id = ? AND org_id = ?
        """, sender_id, org_id)
    else:
        cursor.execute("""
            SELECT *
            FROM khPriority.dbo.EmailAgentApprovedSenders
            WHERE id = ?
        """, sender_id)
    columns = [c[0] for c in cursor.description]
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    record = dict(zip(columns, row))
    record["tables"] = get_sender_tables(record["id"])
    return record


def toggle_sender_active(sender_id):
    conn = get_master_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE khPriority.dbo.EmailAgentApprovedSenders
        SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END
        WHERE id = ?
    """, sender_id)
    conn.commit()
    conn.close()


def add_approved_sender(org_id, sender_email, sender_name=None):
    sender_email = normalize_email(sender_email)
    sender_name = str(sender_name or "").strip() or None
    conn = get_master_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT TOP 1 id
        FROM khPriority.dbo.EmailAgentApprovedSenders
        WHERE org_id = ?
          AND LOWER(LTRIM(RTRIM(sender_email))) = ?
        ORDER BY id DESC
    """, org_id, sender_email)
    existing = cursor.fetchone()
    if existing:
        cursor.execute("""
            UPDATE khPriority.dbo.EmailAgentApprovedSenders
            SET sender_name = COALESCE(?, sender_name),
                is_active = 1
            WHERE id = ?
        """, sender_name, existing.id)
        sender_id = existing.id
    else:
        cursor.execute("""
            INSERT INTO khPriority.dbo.EmailAgentApprovedSenders
                (org_id, sender_email, sender_name, is_active)
            OUTPUT INSERTED.id
            VALUES (?, ?, ?, 1)
        """, org_id, sender_email, sender_name)
        sender_id = cursor.fetchone()[0]
    conn.commit()
    conn.close()
    return sender_id


def delete_approved_sender(sender_id, org_id=None):
    _ensure_once()
    conn = get_master_connection()
    cursor = conn.cursor()
    if org_id:
        cursor.execute("""
            SELECT 1
            FROM khPriority.dbo.EmailAgentApprovedSenders
            WHERE id = ? AND org_id = ?
        """, sender_id, org_id)
        if not cursor.fetchone():
            conn.close()
            return False
    cursor.execute("""
        DELETE FROM khPriority.dbo.EmailAgentSenderTables
        WHERE sender_id = ?
    """, sender_id)
    cursor.execute("""
        DELETE FROM khPriority.dbo.EmailAgentApprovedSenders
        WHERE id = ?
    """, sender_id)
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    return deleted > 0


def get_approved_senders(org_id=None):
    conn = get_master_connection()
    cursor = conn.cursor()
    if org_id:
        cursor.execute("""
            SELECT *
            FROM khPriority.dbo.EmailAgentApprovedSenders
            WHERE org_id = ?
            ORDER BY created_at DESC, id DESC
        """, org_id)
    else:
        cursor.execute("""
            SELECT *
            FROM khPriority.dbo.EmailAgentApprovedSenders
            ORDER BY created_at DESC, id DESC
        """)
    columns = [c[0] for c in cursor.description]
    rows = cursor.fetchall()
    conn.close()
    result = [dict(zip(columns, row)) for row in rows]
    for r in result:
        r["tables"] = get_sender_tables(r["id"])
    return result


# ── Unregistered senders ───────────────────────────────────────────────────────

def add_or_update_unregistered_sender(org_id, email_account_id, sender_email, sender_name, subject_line, body_text):
    sender_email = normalize_email(sender_email)
    conn = get_master_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT TOP 1 id, seen_count
        FROM khPriority.dbo.EmailAgentUnregisteredSenders
        WHERE org_id = ?
          AND email_account_id = ?
          AND LOWER(LTRIM(RTRIM(sender_email))) = ?
          AND status = 'Pending'
    """, org_id, email_account_id, sender_email)
    row = cursor.fetchone()
    if row:
        record_id = row[0]
        seen_count = int(row[1] or 0) + 1
        cursor.execute("""
            UPDATE khPriority.dbo.EmailAgentUnregisteredSenders
            SET last_seen_at = GETDATE(),
                seen_count = ?,
                subject_line = ?,
                first_message_body = ?
            WHERE id = ?
        """, seen_count, subject_line, body_text, record_id)
    else:
        cursor.execute("""
            INSERT INTO khPriority.dbo.EmailAgentUnregisteredSenders (
                org_id, email_account_id, sender_email, sender_name,
                subject_line, first_message_body, status
            )
            VALUES (?, ?, ?, ?, ?, ?, 'Pending')
        """, org_id, email_account_id, sender_email, sender_name, subject_line, body_text)
    conn.commit()
    conn.close()


def get_unregistered_senders(org_id=None):
    conn = get_master_connection()
    cursor = conn.cursor()
    if org_id:
        cursor.execute("""
            SELECT *
            FROM khPriority.dbo.EmailAgentUnregisteredSenders
            WHERE org_id = ? AND status='Pending'
            ORDER BY last_seen_at DESC, id DESC
        """, org_id)
    else:
        cursor.execute("""
            SELECT *
            FROM khPriority.dbo.EmailAgentUnregisteredSenders
            WHERE status='Pending'
            ORDER BY last_seen_at DESC, id DESC
        """)
    columns = [c[0] for c in cursor.description]
    rows = cursor.fetchall()
    conn.close()
    return [dict(zip(columns, row)) for row in rows]


def approve_unregistered_sender(record_id):
    conn = get_master_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT org_id, sender_email, sender_name
        FROM khPriority.dbo.EmailAgentUnregisteredSenders
        WHERE id = ?
    """, record_id)
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False
    org_id, sender_email, sender_name = row
    cursor.execute("""
        INSERT INTO khPriority.dbo.EmailAgentApprovedSenders
            (org_id, sender_email, sender_name, is_active)
        VALUES (?, ?, ?, 1)
    """, org_id, sender_email, sender_name)
    cursor.execute("""
        UPDATE khPriority.dbo.EmailAgentUnregisteredSenders
        SET status = 'Approved'
        WHERE id = ?
    """, record_id)
    conn.commit()
    conn.close()
    return True
