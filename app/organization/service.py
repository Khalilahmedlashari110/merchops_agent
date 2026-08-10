from app.database.connection_manager import get_master_connection
from .models import Organization


def get_all_organizations():
    conn = get_master_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM Organizations
        WHERE is_active = 1
        ORDER BY name
    """)

    rows = cursor.fetchall()
    conn.close()

    return [Organization(row) for row in rows]


def create_organization(
    name,
    code,
    db_server,
    db_name,
    db_driver,
    email,
    smtp_server,
    smtp_port,
    email_password
):
    conn = get_master_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO Organizations (
            name, code, db_server, db_name, db_driver,
            email, smtp_server, smtp_port, email_password, is_active
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
    """, (
        name, code, db_server, db_name, db_driver,
        email, smtp_server, smtp_port, email_password
    ))

    conn.commit()
    conn.close()


def get_organization_by_id(org_id):
    conn = get_master_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM Organizations
        WHERE id = ? AND is_active = 1
    """, org_id)

    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    return Organization(row)