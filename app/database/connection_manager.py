import os

import pyodbc

def get_master_connection():
    driver = os.getenv("SQL_DRIVER", "ODBC Driver 17 for SQL Server")
    server = os.getenv("SQL_SERVER", "MIS-LAPTOP")
    database = os.getenv("SQL_DATABASE", "khPriority")
    trusted = os.getenv("SQL_TRUSTED", "yes")

    return pyodbc.connect(
        f"DRIVER={{{driver}}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"Trusted_Connection={trusted};"
        "Encrypt=no;"
        "TrustServerCertificate=yes;"
    )

def get_org_connection(org):
    return pyodbc.connect(org.get_connection_string())
