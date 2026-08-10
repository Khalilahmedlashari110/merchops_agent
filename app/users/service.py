from werkzeug.security import generate_password_hash
from app.database.connection_manager import get_master_connection
from app.users.models import User
from app.auth.face_auth import get_face_record_by_user_id


def get_users_by_org(org_id, include_inactive=False):
    conn = get_master_connection()
    cursor = conn.cursor()

    if include_inactive:
        cursor.execute("""
            SELECT id, org_id, full_name, email, username, password_hash, role_name, is_active
            FROM dbo.Users
            WHERE org_id = ?
            ORDER BY full_name
        """, org_id)
    else:
        cursor.execute("""
            SELECT id, org_id, full_name, email, username, password_hash, role_name, is_active
            FROM dbo.Users
            WHERE org_id = ? AND is_active = 1
            ORDER BY full_name
        """, org_id)

    rows = cursor.fetchall()
    conn.close()

    return [
        User(
            id=row.id,
            org_id=row.org_id,
            full_name=row.full_name,
            email=row.email,
            username=row.username,
            password_hash=row.password_hash,
            role_name=row.role_name,
            is_active=row.is_active
        )
        for row in rows
    ]

def create_org_admin_or_user(org_id, full_name, email, username, password, role_name):
    conn = get_master_connection()
    cursor = conn.cursor()

    password_hash = generate_password_hash(password)

    cursor.execute("""
        INSERT INTO dbo.Users (
            org_id, full_name, email, username, password_hash, role_name, is_active
        )
        VALUES (?, ?, ?, ?, ?, ?, 1)
    """, (
        org_id, full_name, email, username, password_hash, role_name
    ))

    conn.commit()
    conn.close()


def get_users_by_org_with_face_status(org_id, include_inactive=False):
    users = get_users_by_org(org_id, include_inactive=include_inactive)

    results = []
    for user in users:
        face_record = get_face_record_by_user_id(user.id)
        results.append({
            "user": user,
            "face_registered": True if face_record else False,
            "face_record": face_record
        })

    return results


def set_user_active_status(user_id, is_active):
    conn = get_master_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE dbo.Users
        SET is_active = ?
        WHERE id = ?
    """, 1 if is_active else 0, user_id)

    conn.commit()
    conn.close()