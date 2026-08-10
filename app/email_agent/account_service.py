from app.database.connection_manager import get_master_connection


def get_organizations():
    conn = get_master_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, name
        FROM khPriority.dbo.Organizations
        ORDER BY name
    """)

    rows = cursor.fetchall()
    conn.close()

    return [{"id": r[0], "name": r[1]} for r in rows]


def get_users_by_org(org_id=None):
    conn = get_master_connection()
    cursor = conn.cursor()

    if org_id:
        cursor.execute("""
            SELECT id, full_name, username
            FROM khPriority.dbo.Users
            WHERE org_id = ?
            ORDER BY full_name
        """, org_id)
    else:
        cursor.execute("""
            SELECT id, full_name, username
            FROM khPriority.dbo.Users
            ORDER BY full_name
        """)

    rows = cursor.fetchall()
    conn.close()

    return [
        {"id": r[0], "full_name": r[1], "username": r[2]}
        for r in rows
    ]


def get_email_accounts():
    conn = get_master_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            ea.id,
            ea.org_id,
            ea.user_id,
            ea.account_name,
            ea.email_address,
            ea.smtp_server,
            ea.smtp_port,
            ea.imap_server,
            ea.imap_port,
            ea.provider,
            ea.auto_reply_enabled,
            ea.check_interval_minutes,
            ea.is_active,
            ea.created_at,
            o.name AS organization_name,
            u.full_name AS user_name
        FROM khPriority.dbo.OrganizationEmailAccounts ea
        LEFT JOIN khPriority.dbo.Organizations o
            ON ea.org_id = o.id
        LEFT JOIN khPriority.dbo.Users u
            ON ea.user_id = u.id
        ORDER BY ea.created_at DESC, ea.id DESC
    """)

    columns = [c[0] for c in cursor.description]
    rows = cursor.fetchall()
    conn.close()

    return [dict(zip(columns, row)) for row in rows]


def get_email_account_by_id(account_id):
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
            check_interval_minutes,
            is_active,
            created_at
        FROM khPriority.dbo.OrganizationEmailAccounts
        WHERE id = ?
    """, account_id)

    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    columns = [
        "id", "org_id", "user_id", "account_name", "email_address",
        "email_password", "smtp_server", "smtp_port", "imap_server",
        "imap_port", "provider", "auto_reply_enabled",
        "check_interval_minutes", "is_active", "created_at"
    ]
    return dict(zip(columns, row))


def create_email_account(data):
    conn = get_master_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO khPriority.dbo.OrganizationEmailAccounts (
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
            check_interval_minutes,
            is_active
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data["org_id"],
        data["user_id"],
        data["account_name"],
        data["email_address"],
        data["email_password"],
        data["smtp_server"],
        data["smtp_port"],
        data["imap_server"],
        data["imap_port"],
        data["provider"],
        data["auto_reply_enabled"],
        data["check_interval_minutes"],
        data["is_active"],
    ))

    conn.commit()
    conn.close()


def update_email_account(account_id, data):
    conn = get_master_connection()
    cursor = conn.cursor()

    if data.get("email_password"):
        cursor.execute("""
            UPDATE khPriority.dbo.OrganizationEmailAccounts
            SET
                org_id = ?,
                user_id = ?,
                account_name = ?,
                email_address = ?,
                email_password = ?,
                smtp_server = ?,
                smtp_port = ?,
                imap_server = ?,
                imap_port = ?,
                provider = ?,
                auto_reply_enabled = ?,
                check_interval_minutes = ?,
                is_active = ?
            WHERE id = ?
        """, (
            data["org_id"],
            data["user_id"],
            data["account_name"],
            data["email_address"],
            data["email_password"],
            data["smtp_server"],
            data["smtp_port"],
            data["imap_server"],
            data["imap_port"],
            data["provider"],
            data["auto_reply_enabled"],
            data["check_interval_minutes"],
            data["is_active"],
            account_id,
        ))
    else:
        cursor.execute("""
            UPDATE khPriority.dbo.OrganizationEmailAccounts
            SET
                org_id = ?,
                user_id = ?,
                account_name = ?,
                email_address = ?,
                smtp_server = ?,
                smtp_port = ?,
                imap_server = ?,
                imap_port = ?,
                provider = ?,
                auto_reply_enabled = ?,
                check_interval_minutes = ?,
                is_active = ?
            WHERE id = ?
        """, (
            data["org_id"],
            data["user_id"],
            data["account_name"],
            data["email_address"],
            data["smtp_server"],
            data["smtp_port"],
            data["imap_server"],
            data["imap_port"],
            data["provider"],
            data["auto_reply_enabled"],
            data["check_interval_minutes"],
            data["is_active"],
            account_id,
        ))

    conn.commit()
    conn.close()


def delete_email_account(account_id):
    conn = get_master_connection()
    cursor = conn.cursor()

    cursor.execute("""
        DELETE FROM khPriority.dbo.OrganizationEmailAccounts
        WHERE id = ?
    """, account_id)

    conn.commit()
    conn.close()