from flask import request
from werkzeug.security import check_password_hash
from app.database.connection_manager import get_master_connection
from app.users.models import User


def build_user_from_row(row):
    return User(
        id=row.id,
        org_id=row.org_id,
        full_name=row.full_name,
        email=row.email,
        username=row.username,
        password_hash=row.password_hash,
        role_name=row.role_name,
        is_active=row.is_active
    )

def get_user_by_id(user_id):
    conn = get_master_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, org_id, full_name, email, username, password_hash, role_name, is_active
        FROM dbo.Users
        WHERE id = ?
    """, user_id)

    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    return build_user_from_row(row)


def get_user_by_username(username):
    conn = get_master_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, org_id, full_name, email, username, password_hash, role_name, is_active
        FROM dbo.Users
        WHERE username = ? AND is_active = 1
    """, username)

    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    return build_user_from_row(row)

def validate_password_login(username, password):
    user = get_user_by_username(username)
    if not user:
        return None
    if not check_password_hash(user.password_hash, password):
        return None
    return user


def log_login_attempt(user_id, org_id, login_method, status):
    conn = get_master_connection()
    cursor = conn.cursor()

    ip_address = request.remote_addr if request else None

    cursor.execute("""
        INSERT INTO UserLoginHistory (
            user_id, org_id, login_method, ip_address, status
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        user_id,
        org_id if org_id else None,
        login_method,
        ip_address,
        status
    ))

    conn.commit()
    conn.close()