import os


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "super-secret-key-change-this")

    APP_NAME = "AI System Control Center"
    DEBUG = True

    SQL_SERVER = os.getenv("SQL_SERVER", "MIS-LAPTOP")
    SQL_DATABASE = os.getenv("SQL_DATABASE", "khPriority")
    SQL_DRIVER = os.getenv("SQL_DRIVER", "ODBC Driver 17 for SQL Server")

    SQL_TRUSTED = os.getenv("SQL_TRUSTED", "yes")

    CONNECTION_STRING = (
        f"DRIVER={{{SQL_DRIVER}}};"
        f"SERVER={SQL_SERVER};"
        f"DATABASE={SQL_DATABASE};"
        f"Trusted_Connection={SQL_TRUSTED};"
    )

    FACE_DATA_DIR = os.path.join("static", "face_data")
    ORG_ASSETS_DIR = os.path.join("static", "org_assets")
