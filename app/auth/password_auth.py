from flask import flash
from flask_login import login_user
import pyodbc

from app.auth.service import validate_password_login, log_login_attempt


def handle_password_login(username, password):
    try:
        user = validate_password_login(username, password)
    except pyodbc.Error:
        flash("Database connection is unavailable. Please check the SQL Server connection and try again.", "danger")
        return None

    if not user:
        flash("Invalid username or password.", "danger")
        return None

    login_user(user)
    try:
        log_login_attempt(user.id, user.org_id, "password", "success")
    except pyodbc.Error:
        pass
    return user
