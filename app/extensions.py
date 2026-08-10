from flask_login import LoginManager
import pyodbc
from app.auth.service import get_user_by_id

login_manager = LoginManager()


def init_extensions(app):
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = ""


@login_manager.user_loader
def load_user(user_id):
    try:
        return get_user_by_id(user_id)
    except pyodbc.Error:
        return None
