import json
import re
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from app.database.connection_manager import get_master_connection


RAW_EXTENSIONS = {".csv", ".xlsx", ".xls", ".txt", ".json", ".xml"}
UPS_TABLE = "khPriority.dbo.CarrierUPSRawData"
UPS_ACTUAL_BILLING_TABLE = "khPriority.dbo.CarrierUPSActualBilling"
SQL_NUMERIC_TYPES = {
    "bigint",
    "decimal",
    "float",
    "int",
    "money",
    "numeric",
    "real",
    "smallint",
    "smallmoney",
    "tinyint",
}
SQL_INTEGER_TYPES = {"bigint", "int", "smallint", "tinyint"}
SQL_DATE_TYPES = {"date", "datetime", "datetime2", "datetimeoffset", "smalldatetime", "time"}


def empty_billing_analysis(error=None):
    return {
        "error": error,
        "manifest_tracking_count": 0,
        "billing_tracking_count": 0,
        "matched_tracking_count": 0,
        "manifest_missing_count": 0,
        "billing_unmatched_count": 0,
        "missing_invoice_number_count": 0,
        "total_payment_amount": 0,
        "total_billing_packages": 0,
        "monthly_payments": [],
        "source_files": [],
        "manifest_missing_rows": [],
        "billing_unmatched_rows": [],
        "missing_invoice_rows": [],
    }


def empty_ups_billing_report(error=None):
    return {
        "error": error,
        "total_months": 0,
        "total_invoices": 0,
        "total_packages": 0,
        "total_billed": 0,
        "verified": {
            "total_verified": 0,
            "total_difference": 0,
            "verified_packages": 0,
            "review_packages": 0,
            "months": [],
        },
        "months": [],
        "year_trends": [],
        "month_trends": [],
        "missing_date_rows": 0,
        "missing_date_sources": [],
    }


def clean_column_name(value):
    text = str(value or "").strip()
    if not text:
        return "Column"
    cleaned = []
    previous_underscore = False
    for char in text:
        if char.isalnum():
            cleaned.append(char)
            previous_underscore = False
        elif not previous_underscore:
            cleaned.append("_")
            previous_underscore = True
    result = "".join(cleaned).strip("_")
    return result or "Column"


def make_unique_columns(columns):
    seen = {}
    unique = []
    for column in columns:
        base = clean_column_name(column)
        count = seen.get(base, 0)
        seen[base] = count + 1
        unique.append(base if count == 0 else f"{base}_{count + 1}")
    return unique


def scan_raw_folder(folder_path):
    folder = Path(folder_path).expanduser()
    if not folder.exists() or not folder.is_dir():
        return [], "Folder path does not exist or is not a directory."

    files = []
    for item in sorted(folder.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not item.is_file() or item.suffix.lower() not in RAW_EXTENSIONS:
            continue
        stat = item.stat()
        files.append(
            {
                "path": item,
                "name": item.name,
                "extension": item.suffix.lower().lstrip(".").upper(),
                "size_kb": round(stat.st_size / 1024, 1),
                "modified": stat.st_mtime,
            }
        )
    return files, None


def read_raw_file(path):
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    if suffix == ".txt":
        return pd.read_csv(path, sep=None, engine="python")
    if suffix == ".json":
        return pd.read_json(path)
    if suffix == ".xml":
        return pd.read_xml(path)
    raise ValueError(f"Unsupported file type: {suffix}")


def read_file_like(file_obj, filename):
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(file_obj)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(file_obj)
    if suffix == ".txt":
        return pd.read_csv(file_obj, sep=None, engine="python")
    raise ValueError(f"Unsupported file type: {suffix}")


def normalize_value(value):
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, default=str)
    if pd.isna(value):
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value.item() if hasattr(value, "item") else value


def normalize_dataframe(df, source_file):
    df = df.copy()
    df.columns = make_unique_columns(df.columns)
    df = df.dropna(how="all")

    rows = []
    for index, row in df.iterrows():
        cleaned = {column: normalize_value(row[column]) for column in df.columns}
        if not any(value not in (None, "") for value in cleaned.values()):
            continue
        cleaned["_SourceFile"] = source_file
        cleaned["_RowNumber"] = int(index) + 2
        rows.append(cleaned)
    return rows


def combine_ups_folder(folder_path, max_rows=None):
    files, scan_error = scan_raw_folder(folder_path)
    if scan_error:
        return {
            "files": [],
            "rows": [],
            "columns": [],
            "errors": [scan_error],
            "total_size_kb": 0,
        }

    combined_rows = []
    errors = []
    all_columns = ["_SourceFile", "_RowNumber"]

    for file_info in files:
        path = file_info["path"]
        try:
            rows = normalize_dataframe(read_raw_file(path), file_info["name"])
            if max_rows is not None:
                remaining = max_rows - len(combined_rows)
                if remaining <= 0:
                    break
                rows = rows[:remaining]
            combined_rows.extend(rows)
            for row in rows:
                for column in row.keys():
                    if column not in all_columns:
                        all_columns.append(column)
            if max_rows is not None and len(combined_rows) >= max_rows:
                break
        except Exception as exc:
            errors.append(f"{file_info['name']}: {exc}")

    return {
        "files": files,
        "rows": combined_rows,
        "columns": all_columns,
        "errors": errors,
        "total_size_kb": round(sum(file_info["size_kb"] for file_info in files), 1),
    }


def load_actual_billing_path(file_path):
    path = Path(file_path).expanduser()
    if not path.exists() or not path.is_file():
        return {
            "rows": [],
            "columns": [],
            "errors": ["Actual billing file path does not exist or is not readable."],
            "source_file": str(file_path or ""),
        }

    try:
        rows = normalize_dataframe(read_raw_file(path), path.name)
    except Exception as exc:
        return {
            "rows": [],
            "columns": [],
            "errors": [f"{path.name}: {exc}"],
            "source_file": path.name,
        }

    return {
        "rows": rows,
        "columns": list(rows[0].keys()) if rows else [],
        "errors": [],
        "source_file": path.name,
    }


def load_actual_billing_upload(file_storage):
    filename = file_storage.filename or "uploaded_actual_billing"
    try:
        rows = normalize_dataframe(read_file_like(file_storage, filename), filename)
    except Exception as exc:
        return {
            "rows": [],
            "columns": [],
            "errors": [f"{filename}: {exc}"],
            "source_file": filename,
        }

    return {
        "rows": rows,
        "columns": list(rows[0].keys()) if rows else [],
        "errors": [],
        "source_file": filename,
    }


def first_matching(row, candidates):
    normalized = {clean_column_name(key).lower(): key for key in row.keys()}
    for candidate in candidates:
        key = normalized.get(clean_column_name(candidate).lower())
        if key:
            return row.get(key)
    return None


def ensure_ups_table():
    conn = get_master_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        IF OBJECT_ID('khPriority.dbo.CarrierUPSRawData', 'U') IS NULL
        BEGIN
            CREATE TABLE khPriority.dbo.CarrierUPSRawData (
                id INT IDENTITY(1,1) PRIMARY KEY,
                upload_batch_id NVARCHAR(64) NOT NULL,
                source_folder NVARCHAR(MAX) NULL,
                source_file NVARCHAR(500) NULL,
                source_row_number INT NULL,
                tracking_key NVARCHAR(255) NULL,
                invoice_number NVARCHAR(255) NULL,
                tracking_number NVARCHAR(255) NULL,
                shipment_date NVARCHAR(120) NULL,
                recipient_name NVARCHAR(500) NULL,
                city NVARCHAR(255) NULL,
                state_code NVARCHAR(80) NULL,
                zip_code NVARCHAR(80) NULL,
                zone NVARCHAR(80) NULL,
                billed_weight DECIMAL(18, 4) NULL,
                residential_flag NVARCHAR(80) NULL,
                service_level NVARCHAR(255) NULL,
                shipment_status NVARCHAR(255) NULL,
                charge_amount DECIMAL(18, 4) NULL,
                cod_amount DECIMAL(18, 4) NULL,
                declared_value DECIMAL(18, 4) NULL,
                add_on_cost DECIMAL(18, 4) NULL,
                raw_payload NVARCHAR(MAX) NOT NULL,
                uploaded_by INT NULL,
                uploaded_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
            )
        END
        """
    )
    for column_name, column_type in {
        "source_folder": "NVARCHAR(MAX) NULL",
        "source_file": "NVARCHAR(500) NULL",
        "tracking_key": "NVARCHAR(255) NULL",
        "invoice_number": "NVARCHAR(255) NULL",
        "tracking_number": "NVARCHAR(255) NULL",
        "shipment_date": "NVARCHAR(120) NULL",
        "recipient_name": "NVARCHAR(500) NULL",
        "city": "NVARCHAR(255) NULL",
        "state_code": "NVARCHAR(80) NULL",
        "zip_code": "NVARCHAR(80) NULL",
        "zone": "NVARCHAR(80) NULL",
        "residential_flag": "NVARCHAR(80) NULL",
        "service_level": "NVARCHAR(255) NULL",
        "shipment_status": "NVARCHAR(255) NULL",
    }.items():
        cursor.execute(
            f"""
            IF COL_LENGTH('khPriority.dbo.CarrierUPSRawData', '{column_name}') IS NOT NULL
            BEGIN
                ALTER TABLE khPriority.dbo.CarrierUPSRawData
                ALTER COLUMN {column_name} {column_type}
            END
            """
        )
    for column_name, column_type in {
        "tracking_key": "NVARCHAR(255) NULL",
        "invoice_number": "NVARCHAR(255) NULL",
        "city": "NVARCHAR(255) NULL",
        "state_code": "NVARCHAR(80) NULL",
        "zip_code": "NVARCHAR(80) NULL",
        "zone": "NVARCHAR(80) NULL",
        "billed_weight": "DECIMAL(18, 4) NULL",
        "residential_flag": "NVARCHAR(80) NULL",
        "cod_amount": "DECIMAL(18, 4) NULL",
        "declared_value": "DECIMAL(18, 4) NULL",
        "add_on_cost": "DECIMAL(18, 4) NULL",
    }.items():
        cursor.execute(
            f"""
            IF COL_LENGTH('khPriority.dbo.CarrierUPSRawData', '{column_name}') IS NULL
            BEGIN
                ALTER TABLE khPriority.dbo.CarrierUPSRawData
                ADD {column_name} {column_type}
            END
            """
        )
    cursor.execute(
        """
        IF NOT EXISTS (
            SELECT 1 FROM sys.indexes
            WHERE name = 'IX_CarrierUPSRawData_tracking_key'
              AND object_id = OBJECT_ID('khPriority.dbo.CarrierUPSRawData')
        )
        BEGIN
            CREATE INDEX IX_CarrierUPSRawData_tracking_key
            ON khPriority.dbo.CarrierUPSRawData (tracking_key)
        END
        """
    )
    conn.commit()
    conn.close()


def text_or_none(value, max_length=None):
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    if max_length and len(text) > max_length:
        return text[:max_length]
    return text


def tracking_key(value):
    text = text_or_none(value, 255)
    if not text:
        return None
    return "".join(text.upper().split())


def decimal_or_none(value):
    try:
        if value in (None, ""):
            return None
        return float(str(value).replace(",", "").replace("$", "").strip())
    except Exception:
        return None


def parsed_date_or_none(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = text_or_none(value, 120)
    if not text:
        return None
    text = text.strip()

    if re.fullmatch(r"\d{5}(?:\.0+)?", text):
        try:
            return (datetime(1899, 12, 30) + timedelta(days=int(float(text)))).date()
        except (ValueError, OverflowError):
            pass

    formats = (
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%d-%m-%Y",
        "%m-%d-%Y",
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y%m%d",
        "%d/%m/%y",
        "%m/%d/%y",
        "%d-%m-%y",
        "%m-%d-%y",
        "%d %b %Y",
        "%d %B %Y",
        "%b %d %Y",
        "%B %d %Y",
    )
    candidates = [text]
    if "T" in text:
        candidates.append(text.split("T", 1)[0].strip())
    if " " in text:
        candidates.append(text.split()[0].strip())

    for candidate in dict.fromkeys(candidate for candidate in candidates if candidate):
        for fmt in formats:
            try:
                return datetime.strptime(candidate, fmt).date()
            except ValueError:
                pass
    return None


def date_text_for_storage(value):
    parsed = parsed_date_or_none(value)
    if not parsed:
        return text_or_none(value, 120)
    return f"{parsed.year}-{parsed.month}-{parsed.day}"


def parse_invoice_month(value):
    text = text_or_none(value, 120)
    if not text:
        return None
    parsed = parsed_date_or_none(text)
    if parsed:
        return parsed.strftime("%Y-%m")
    text = text.strip()
    if re.fullmatch(r"\d{5}(?:\.0+)?", text):
        try:
            excel_date = datetime(1899, 12, 30) + timedelta(days=int(float(text)))
            return excel_date.strftime("%Y-%m")
        except (ValueError, OverflowError):
            pass
    formats = (
        "%m/%d/%Y",
        "%d/%m/%Y",
        "%m-%d-%Y",
        "%d-%m-%Y",
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y%m%d",
        "%m/%d/%y",
        "%d/%m/%y",
        "%m-%d-%y",
        "%d-%m-%y",
        "%m/%Y",
        "%m-%Y",
        "%b %Y",
        "%B %Y",
        "%b %d %Y",
        "%B %d %Y",
    )
    candidates = [text]
    if "T" in text:
        candidates.append(text.split("T", 1)[0].strip())
    if " " in text:
        candidates.append(text.split()[0].strip())

    for candidate in dict.fromkeys(candidate for candidate in candidates if candidate):
        for fmt in formats:
            try:
                return datetime.strptime(candidate, fmt).strftime("%Y-%m")
            except ValueError:
                pass

    match = re.search(r"\b(\d{4})[-/](\d{1,2})\b", text)
    if match:
        return f"{match.group(1)}-{int(match.group(2)):02d}"
    match = re.search(r"\b(\d{1,2})[-/](\d{4})\b", text)
    if match:
        return f"{match.group(2)}-{int(match.group(1)):02d}"
    return None


INVOICE_DATE_CANDIDATES = [
    "Invoice Date",
    "InvoiceDate",
    "Invoice_Date",
    "Invoice Dt",
    "InvoiceDt",
    "Invoice_Dt",
    "Inv Date",
    "InvDate",
    "Inv_Date",
    "Bill Dt",
    "BillDt",
    "Bill_Dt",
    "Bill Date",
    "Billing Date",
    "Bill_Date",
    "Billing_Date",
    "Billed Date",
    "BilledDate",
    "Billed_Date",
    "Statement Date",
    "StatementDate",
    "Statement_Date",
    "Document Date",
    "DocumentDate",
    "Document_Date",
    "Transaction Date",
    "Transaction_Date",
    "TransactionDate",
    "Transaction Dt",
    "TransactionDt",
    "Transaction_Dt",
    "Charge Date",
    "ChargeDate",
    "Charge_Date",
    "Shipment Date",
    "Shipment_Date",
    "ShipmentDate",
    "Ship Date",
    "Ship_Date",
    "ShipDate",
    "Pickup Date",
    "Pickup_Date",
    "PickupDate",
]

CHARGE_TOTAL_CANDIDATES = [
    "Charge Total",
    "Charge_Total",
    "raw_Charge_Total",
    "Total Charged",
    "TotalCharged",
    "Total_Charged",
    "Total Billed Charge",
    "TotalBilledCharge",
    "Total_Billed_Charge",
    "Total Charge",
    "TotalCharge",
    "Total_Charge",
    "Total Charges",
    "Invoice Amount",
    "InvoiceAmount",
    "Invoice_Amount",
    "Net Amount",
    "NetAmount",
    "Net_Amount",
    "Amount",
]


def sql_identifier(name):
    return f"[{name}]"


def raw_billing_column_name(source_column, used_names):
    base = f"raw_{clean_column_name(source_column)}"[:120].strip("_") or "raw_Column"
    candidate = base
    counter = 2
    while candidate.lower() in used_names:
        suffix = f"_{counter}"
        candidate = f"{base[:120 - len(suffix)]}{suffix}"
        counter += 1
    used_names.add(candidate.lower())
    return candidate


def get_sql_column_type(cursor, column_name):
    cursor.execute(
        """
        SELECT DATA_TYPE
        FROM khPriority.INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = 'dbo'
          AND TABLE_NAME = 'CarrierUPSActualBilling'
          AND COLUMN_NAME = ?
        """,
        column_name,
    )
    row = cursor.fetchone()
    return row.DATA_TYPE.lower() if row and row.DATA_TYPE else "nvarchar"


def value_for_sql(value, sql_type):
    if sql_type in SQL_DATE_TYPES:
        return parsed_date_or_none(value)
    if sql_type in SQL_NUMERIC_TYPES:
        number = decimal_or_none(value)
        if number is None:
            return None
        return int(number) if sql_type in SQL_INTEGER_TYPES else number
    return text_or_none(value)


def raw_value_for_sql(value, sql_type):
    return value_for_sql(value, sql_type)


def ensure_actual_billing_raw_columns(cursor, rows):
    if not rows:
        return []

    source_columns = [
        column
        for column in rows[0].keys()
        if column not in {"_SourceFile", "_RowNumber"}
    ]
    used_names = set()
    column_map = []

    for source_column in source_columns:
        sql_column = raw_billing_column_name(source_column, used_names)
        column_map.append((source_column, sql_column))
        cursor.execute(
            f"""
            IF COL_LENGTH('khPriority.dbo.CarrierUPSActualBilling', '{sql_column}') IS NULL
            BEGIN
                ALTER TABLE khPriority.dbo.CarrierUPSActualBilling
                ADD {sql_identifier(sql_column)} NVARCHAR(MAX) NULL
            END
            """
        )
        sql_type = get_sql_column_type(cursor, sql_column)
        column_map[-1] = (source_column, sql_column, sql_type)

    return column_map


def ensure_actual_billing_table():
    conn = get_master_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        IF OBJECT_ID('khPriority.dbo.CarrierUPSActualBilling', 'U') IS NULL
        BEGIN
            CREATE TABLE khPriority.dbo.CarrierUPSActualBilling (
                id INT IDENTITY(1,1) PRIMARY KEY,
                upload_batch_id NVARCHAR(64) NOT NULL,
                source_file NVARCHAR(500) NULL,
                source_row_number INT NULL,
                invoice_number NVARCHAR(255) NULL,
                invoice_date NVARCHAR(120) NULL,
                invoice_month NVARCHAR(20) NULL,
                account_number NVARCHAR(255) NULL,
                tracking_number NVARCHAR(255) NULL,
                billing_tracking_key NVARCHAR(255) NULL,
                ship_date NVARCHAR(120) NULL,
                service_level NVARCHAR(255) NULL,
                zone NVARCHAR(80) NULL,
                billed_weight DECIMAL(18, 4) NULL,
                published_charge DECIMAL(18, 4) NULL,
                transportation_charge DECIMAL(18, 4) NULL,
                fuel_surcharge DECIMAL(18, 4) NULL,
                residential_surcharge DECIMAL(18, 4) NULL,
                other_accessorial_charge DECIMAL(18, 4) NULL,
                total_billed_charge DECIMAL(18, 4) NULL,
                currency NVARCHAR(40) NULL,
                raw_payload NVARCHAR(MAX) NOT NULL,
                uploaded_by INT NULL,
                uploaded_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
            )
        END
        """
    )
    cursor.execute(
        """
        IF COL_LENGTH('khPriority.dbo.CarrierUPSActualBilling', 'invoice_month') IS NULL
        BEGIN
            ALTER TABLE khPriority.dbo.CarrierUPSActualBilling
            ADD invoice_month NVARCHAR(20) NULL
        END
        """
    )
    cursor.execute(
        """
        IF COL_LENGTH('khPriority.dbo.CarrierUPSActualBilling', 'raw_Tracking_No') IS NULL
        BEGIN
            ALTER TABLE khPriority.dbo.CarrierUPSActualBilling
            ADD raw_Tracking_No NVARCHAR(255) NULL
        END
        """
    )
    cursor.execute(
        """
        IF COL_LENGTH('khPriority.dbo.CarrierUPSActualBilling', 'raw_Charge_Total') IS NULL
        BEGIN
            ALTER TABLE khPriority.dbo.CarrierUPSActualBilling
            ADD raw_Charge_Total NVARCHAR(MAX) NULL
        END
        """
    )
    cursor.execute(
        """
        IF COL_LENGTH('khPriority.dbo.CarrierUPSActualBilling', 'billing_tracking_key') IS NULL
        BEGIN
            ALTER TABLE khPriority.dbo.CarrierUPSActualBilling
            ADD billing_tracking_key NVARCHAR(255) NULL
        END
        """
    )
    cursor.execute(
        """
        IF NOT EXISTS (
            SELECT 1 FROM sys.indexes
            WHERE name = 'IX_CarrierUPSActualBilling_tracking_key'
              AND object_id = OBJECT_ID('khPriority.dbo.CarrierUPSActualBilling')
        )
        BEGIN
            CREATE INDEX IX_CarrierUPSActualBilling_tracking_key
            ON khPriority.dbo.CarrierUPSActualBilling (billing_tracking_key)
        END
        """
    )
    cursor.execute(
        """
        IF NOT EXISTS (
            SELECT 1 FROM sys.indexes
            WHERE name = 'IX_CarrierUPSActualBilling_invoice_month'
              AND object_id = OBJECT_ID('khPriority.dbo.CarrierUPSActualBilling')
        )
        BEGIN
            CREATE INDEX IX_CarrierUPSActualBilling_invoice_month
            ON khPriority.dbo.CarrierUPSActualBilling (invoice_month)
            INCLUDE (invoice_number, billing_tracking_key, total_billed_charge, invoice_date)
        END
        """
    )
    cursor.execute(
        """
        IF NOT EXISTS (
            SELECT 1 FROM sys.indexes
            WHERE name = 'IX_CarrierUPSActualBilling_invoice_number'
              AND object_id = OBJECT_ID('khPriority.dbo.CarrierUPSActualBilling')
        )
        BEGIN
            CREATE INDEX IX_CarrierUPSActualBilling_invoice_number
            ON khPriority.dbo.CarrierUPSActualBilling (invoice_number)
            INCLUDE (invoice_month, billing_tracking_key, total_billed_charge, invoice_date)
        END
        """
    )
    conn.commit()
    conn.close()


def upload_actual_billing_rows(rows, source_file=None, uploaded_by=None):
    ensure_actual_billing_table()
    batch_id = str(uuid.uuid4())
    conn = get_master_connection()
    cursor = conn.cursor()
    raw_column_map = ensure_actual_billing_raw_columns(cursor, rows)
    raw_sql_columns = [sql_identifier(sql_column) for _, sql_column, _ in raw_column_map]
    raw_placeholders = ["?"] * len(raw_column_map)
    cursor.fast_executemany = False
    insert_params = []
    fixed_columns = [
        "upload_batch_id",
        "source_file",
        "source_row_number",
        "invoice_number",
        "invoice_date",
        "invoice_month",
        "account_number",
        "tracking_number",
        "billing_tracking_key",
        "ship_date",
        "service_level",
        "zone",
        "billed_weight",
        "published_charge",
        "transportation_charge",
        "fuel_surcharge",
        "residential_surcharge",
        "other_accessorial_charge",
        "total_billed_charge",
        "currency",
        "raw_payload",
        "uploaded_by",
    ]
    fixed_column_types = {
        column: get_sql_column_type(cursor, column)
        for column in fixed_columns
    }

    for row in rows:
        tracking_no = text_or_none(first_matching(row, ["Tracking No", "TrackingNo", "Tracking Number", "Tracking ID", "TrackingNumber", "Tracking", "Package Tracking Number", "Shipment Number", "ShipmentNumber"]), 255)
        invoice_date_value = date_text_for_storage(first_matching(row, INVOICE_DATE_CANDIDATES))
        ship_date_value = date_text_for_storage(first_matching(row, ["Ship Date", "ShipDate", "Shipment Date", "Pickup Date", "Date"]))
        raw_fixed_values = [
            batch_id,
            text_or_none(source_file or row.get("_SourceFile"), 500),
            row.get("_RowNumber"),
            text_or_none(first_matching(row, ["Invoice Number", "InvoiceNumber", "Invoice No", "InvoiceNo", "Invoice"]), 255),
            invoice_date_value,
            parse_invoice_month(invoice_date_value),
            text_or_none(first_matching(row, ["Account Number", "AccountNumber", "UPS Account", "Shipper Account"]), 255),
            tracking_no,
            tracking_key(tracking_no),
            ship_date_value,
            text_or_none(first_matching(row, ["Service", "Service Level", "ServiceLevel", "Service Type", "UPS Service"]), 255),
            text_or_none(first_matching(row, ["Zone", "UPS Zone"]), 80),
            decimal_or_none(first_matching(row, ["Billed Weight", "BilledWeight", "Billable Weight", "Weight", "Actual Weight"])),
            decimal_or_none(first_matching(row, ["Published Charge", "PublishedCharge", "Published Rate", "List Charge"])),
            decimal_or_none(first_matching(row, ["Transportation Charge", "TransportationCharge", "Base Charge", "Freight Charge", "Net Charge"])),
            decimal_or_none(first_matching(row, ["Fuel Surcharge", "FuelSurcharge", "Fuel"])),
            decimal_or_none(first_matching(row, ["Residential Surcharge", "ResidentialSurcharge", "Residential"])),
            decimal_or_none(first_matching(row, ["Other Accessorial Charge", "OtherAccessorialCharge", "Accessorial Charge", "Accessorials", "Other Charge"])),
            decimal_or_none(first_matching(row, CHARGE_TOTAL_CANDIDATES)),
            text_or_none(first_matching(row, ["Currency", "Currency Code"]), 40),
            json.dumps(row, ensure_ascii=False, default=str),
            uploaded_by,
        ]
        fixed_values = [
            value_for_sql(value, fixed_column_types[column])
            for column, value in zip(fixed_columns, raw_fixed_values)
        ]
        raw_values = [
            raw_value_for_sql(row.get(source_column), sql_type)
            for source_column, _, sql_type in raw_column_map
        ]
        insert_params.append(fixed_values + raw_values)

    columns_sql = ",\n                ".join(fixed_columns + raw_sql_columns)
    placeholders_sql = ", ".join(["?"] * len(fixed_columns) + raw_placeholders)
    cursor.executemany(
        f"""
        INSERT INTO khPriority.dbo.CarrierUPSActualBilling (
            {columns_sql}
        )
        VALUES ({placeholders_sql})
        """,
        insert_params,
    )

    conn.commit()
    conn.close()
    return batch_id


def read_payload_value(payload, candidates):
    try:
        data = json.loads(payload or "{}")
    except Exception:
        return None
    return first_matching(data, candidates)


def read_payload_invoice_date(payload):
    try:
        data = json.loads(payload or "{}")
    except Exception:
        return None

    candidate_value = first_matching(data, INVOICE_DATE_CANDIDATES)
    if parse_invoice_month(candidate_value):
        return candidate_value

    for key, value in data.items():
        clean_key = clean_column_name(key).lower()
        looks_like_invoice_date = (
            ("invoice" in clean_key or "billing" in clean_key or "bill" in clean_key or "statement" in clean_key)
            and ("date" in clean_key or clean_key.endswith("_dt") or clean_key.endswith("dt"))
        )
        if looks_like_invoice_date and parse_invoice_month(value):
            return value
    return None


def read_payload_charge_total(payload):
    try:
        data = json.loads(payload or "{}")
    except Exception:
        return None

    candidate_value = first_matching(data, CHARGE_TOTAL_CANDIDATES)
    if decimal_or_none(candidate_value) is not None:
        return candidate_value

    for key, value in data.items():
        clean_key = clean_column_name(key).lower()
        looks_like_total_charge = (
            ("charge" in clean_key or "amount" in clean_key or "billed" in clean_key)
            and ("total" in clean_key or "invoice" in clean_key or "net" in clean_key)
        )
        if looks_like_total_charge and decimal_or_none(value) is not None:
            return value
    return None


def resolve_billed_amount(total_billed_charge, raw_charge_total=None, raw_payload=None):
    stored_amount = decimal_or_none(total_billed_charge)
    raw_amount = decimal_or_none(raw_charge_total) or decimal_or_none(read_payload_charge_total(raw_payload))
    if raw_amount not in (None, 0) and (stored_amount in (None, 0)):
        return raw_amount
    return stored_amount or 0


def backfill_actual_billing_total_charged(limit=None):
    ensure_actual_billing_table()
    conn = get_master_connection()
    cursor = conn.cursor()
    try:
        top_clause = "TOP (?)" if limit else ""
        params = (limit,) if limit else ()
        cursor.execute(
            f"""
            SELECT {top_clause}
                id,
                raw_payload,
                raw_Charge_Total,
                total_billed_charge
            FROM khPriority.dbo.CarrierUPSActualBilling
            WHERE total_billed_charge IS NULL
               OR total_billed_charge = 0
            ORDER BY id DESC
            """,
            *params,
        )
        rows = cursor.fetchall()
        for row in rows:
            total_charged = decimal_or_none(
                row.raw_Charge_Total
                or read_payload_charge_total(row.raw_payload)
            )
            stored_amount = decimal_or_none(row.total_billed_charge)
            if total_charged is not None and total_charged != stored_amount:
                cursor.execute(
                    """
                    UPDATE khPriority.dbo.CarrierUPSActualBilling
                    SET total_billed_charge = ?
                    WHERE id = ?
                    """,
                    total_charged,
                    row.id,
                )
        conn.commit()
    finally:
        conn.close()


def backfill_actual_billing_tracking_numbers(limit=5000):
    ensure_actual_billing_table()
    conn = get_master_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"""
            SELECT TOP (?)
                id,
                raw_payload,
                raw_Tracking_No
            FROM khPriority.dbo.CarrierUPSActualBilling
            WHERE NULLIF(LTRIM(RTRIM(tracking_number)), '') IS NULL
               OR NULLIF(LTRIM(RTRIM(raw_Tracking_No)), '') IS NULL
            ORDER BY id DESC
            """,
            limit,
        )
        rows = cursor.fetchall()
        for row in rows:
            tracking_no = text_or_none(
                row.raw_Tracking_No
                or read_payload_value(
                    row.raw_payload,
                    ["Tracking No", "TrackingNo", "Tracking_No", "Tracking Number", "Tracking ID", "TrackingNumber", "Tracking"],
                ),
                255,
            )
            if tracking_no:
                cursor.execute(
                    """
                    UPDATE khPriority.dbo.CarrierUPSActualBilling
                    SET tracking_number = COALESCE(NULLIF(LTRIM(RTRIM(tracking_number)), ''), ?),
                        raw_Tracking_No = COALESCE(NULLIF(LTRIM(RTRIM(raw_Tracking_No)), ''), ?),
                        billing_tracking_key = COALESCE(NULLIF(LTRIM(RTRIM(billing_tracking_key)), ''), ?)
                    WHERE id = ?
                    """,
                    tracking_no,
                    tracking_no,
                    tracking_key(tracking_no),
                    row.id,
                )
        conn.commit()
    finally:
        conn.close()


def backfill_actual_billing_invoice_months(limit=None):
    ensure_actual_billing_table()
    conn = get_master_connection()
    cursor = conn.cursor()
    try:
        top_clause = "TOP (?)" if limit else ""
        params = (limit,) if limit else ()
        cursor.execute(
            f"""
            SELECT {top_clause}
                id,
                invoice_date,
                raw_payload
            FROM khPriority.dbo.CarrierUPSActualBilling
            WHERE NULLIF(LTRIM(RTRIM(invoice_month)), '') IS NULL
               OR NULLIF(LTRIM(RTRIM(invoice_date)), '') IS NULL
            ORDER BY id DESC
            """,
            *params,
        )
        rows = cursor.fetchall()
        for row in rows:
            invoice_date_value = text_or_none(row.invoice_date, 120) or text_or_none(
                read_payload_invoice_date(row.raw_payload),
                120,
            )
            invoice_month = parse_invoice_month(invoice_date_value)
            if invoice_date_value or invoice_month:
                cursor.execute(
                    """
                    UPDATE khPriority.dbo.CarrierUPSActualBilling
                    SET invoice_date = COALESCE(NULLIF(LTRIM(RTRIM(invoice_date)), ''), ?),
                        invoice_month = COALESCE(NULLIF(LTRIM(RTRIM(invoice_month)), ''), ?)
                    WHERE id = ?
                    """,
                    invoice_date_value,
                    invoice_month,
                    row.id,
                )
        conn.commit()
    finally:
        conn.close()


def normalize_ups_report_keys(limit=20000):
    ensure_ups_table()
    ensure_actual_billing_table()
    conn = get_master_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            WITH pending AS (
                SELECT TOP (?) id
                FROM khPriority.dbo.CarrierUPSRawData
                WHERE NULLIF(LTRIM(RTRIM(tracking_number)), '') IS NOT NULL
                  AND (tracking_key IS NULL OR tracking_key <> UPPER(REPLACE(LTRIM(RTRIM(tracking_number)), ' ', '')))
                ORDER BY id DESC
            )
            UPDATE r
            SET tracking_key = UPPER(REPLACE(LTRIM(RTRIM(r.tracking_number)), ' ', ''))
            FROM khPriority.dbo.CarrierUPSRawData r
            INNER JOIN pending p ON p.id = r.id
            """,
            limit,
        )
        cursor.execute(
            """
            WITH pending AS (
                SELECT TOP (?) id
                FROM khPriority.dbo.CarrierUPSActualBilling
                WHERE COALESCE(NULLIF(LTRIM(RTRIM(tracking_number)), ''), NULLIF(LTRIM(RTRIM(raw_Tracking_No)), '')) IS NOT NULL
                  AND (
                        billing_tracking_key IS NULL
                        OR billing_tracking_key <> UPPER(REPLACE(LTRIM(RTRIM(COALESCE(NULLIF(tracking_number, ''), NULLIF(raw_Tracking_No, '')))), ' ', ''))
                  )
                ORDER BY id DESC
            )
            UPDATE b
            SET billing_tracking_key = UPPER(REPLACE(LTRIM(RTRIM(COALESCE(NULLIF(b.tracking_number, ''), NULLIF(b.raw_Tracking_No, '')))), ' ', ''))
            FROM khPriority.dbo.CarrierUPSActualBilling b
            INNER JOIN pending p ON p.id = b.id
            """,
            limit,
        )
        conn.commit()
    finally:
        conn.close()


def backfill_actual_billing_fdm4_details():
    """Fill missing actual billing receiver/weight details from uploaded UPS raw data."""
    ensure_ups_table()
    ensure_actual_billing_table()
    conn = get_master_connection()
    cursor = conn.cursor()
    try:
        for column_name, sql_type in {
            "raw_Receiver_Name": "NVARCHAR(MAX) NULL",
            "raw_Receiver_Postal_Code": "NVARCHAR(MAX) NULL",
            "raw_Receiver_State": "NVARCHAR(MAX) NULL",
            "raw_Package_Ref_No": "NVARCHAR(MAX) NULL",
        }.items():
            cursor.execute(
                f"""
                IF COL_LENGTH('khPriority.dbo.CarrierUPSActualBilling', '{column_name}') IS NULL
                BEGIN
                    ALTER TABLE khPriority.dbo.CarrierUPSActualBilling
                    ADD {sql_identifier(column_name)} {sql_type}
                END
                """
            )

        cursor.execute(
            """
            WITH fdm4Data AS (
                SELECT
                    tracking_number,
                    LEFT(invoice_number, 8) AS orderNo,
                    recipient_name,
                    zip_code,
                    billed_weight,
                    state_code
                FROM khPriority.dbo.CarrierUPSRawData
                WHERE NULLIF(LTRIM(RTRIM(tracking_number)), '') IS NOT NULL
                  AND NULLIF(LTRIM(RTRIM(invoice_number)), '') IS NOT NULL
            )
            UPDATE ca
            SET
                ca.raw_Receiver_Name = COALESCE(NULLIF(LTRIM(RTRIM(ca.raw_Receiver_Name)), ''), nd.recipient_name),
                ca.raw_Receiver_Postal_Code = COALESCE(NULLIF(LTRIM(RTRIM(ca.raw_Receiver_Postal_Code)), ''), nd.zip_code),
                ca.raw_Receiver_State = COALESCE(NULLIF(LTRIM(RTRIM(ca.raw_Receiver_State)), ''), nd.state_code),
                ca.billed_weight = COALESCE(ca.billed_weight, nd.billed_weight)
            FROM khPriority.dbo.CarrierUPSActualBilling AS ca
            INNER JOIN fdm4Data nd
                ON ca.tracking_number = nd.tracking_number
               AND LEFT(ca.raw_Package_Ref_No, 8) = nd.orderNo
            WHERE
                NULLIF(LTRIM(RTRIM(nd.tracking_number)), '') IS NOT NULL
                AND (
                    NULLIF(LTRIM(RTRIM(ca.raw_Receiver_Name)), '') IS NULL
                    OR NULLIF(LTRIM(RTRIM(ca.raw_Receiver_Postal_Code)), '') IS NULL
                    OR NULLIF(LTRIM(RTRIM(ca.raw_Receiver_State)), '') IS NULL
                    OR ca.billed_weight IS NULL
                )
            """
        )
        updated_count = max(cursor.rowcount or 0, 0)
        conn.commit()
        return updated_count
    finally:
        conn.close()


def report_month_from_values(invoice_date, invoice_month):
    parsed_month = parse_invoice_month(invoice_date)
    if parsed_month:
        return parsed_month
    parsed_month = parse_invoice_month(invoice_month)
    if parsed_month:
        return parsed_month
    return "Missing Invoice Date"


def report_tracking_value(row):
    return text_or_none(
        getattr(row, "billing_tracking_key", None)
        or getattr(row, "tracking_number", None)
        or getattr(row, "raw_Tracking_No", None),
        255,
    )


def sort_report_months(months):
    valid_months = [row for row in months if row["invoice_month"] != "Missing Invoice Date"]
    missing_months = [row for row in months if row["invoice_month"] == "Missing Invoice Date"]
    return sorted(valid_months, key=lambda row: row["invoice_month"], reverse=True) + missing_months


def build_ups_verified_report(cursor, base_months=None):
    from app.carrier.smart_audit import (
        DEFAULT_UPS_CONTRACT_PATH,
        contract_expected_charge,
        estimated_zone_from_zip,
        extract_contract_rules,
        normalize_zip,
        payload_value,
        parse_number,
        read_contract_text,
    )

    contract_text, contract_error = read_contract_text(DEFAULT_UPS_CONTRACT_PATH)
    contract_rules = extract_contract_rules(contract_text)
    cursor.execute(
        """
        SELECT
            COALESCE(NULLIF(LTRIM(RTRIM(invoice_month)), ''), 'Missing Invoice Date') AS invoice_month,
            COALESCE(NULLIF(LTRIM(RTRIM(invoice_number)), ''), 'Missing Invoice') AS invoice_number,
            invoice_date,
            COALESCE(NULLIF(LTRIM(RTRIM(tracking_number)), ''), NULLIF(LTRIM(RTRIM(raw_Tracking_No)), '')) AS tracking_number,
            service_level,
            zone,
            billed_weight,
            published_charge,
            transportation_charge,
            fuel_surcharge,
            residential_surcharge,
            other_accessorial_charge,
            total_billed_charge,
            raw_Charge_Total,
            raw_payload AS billing_payload
        FROM khPriority.dbo.CarrierUPSActualBilling
        WHERE published_charge IS NOT NULL
          AND total_billed_charge IS NOT NULL
        """
    )

    month_lookup = {}
    invoice_lookup = {}
    for base_month in base_months or []:
        month = {
            "invoice_month": base_month["invoice_month"],
            "invoice_count": base_month["invoice_count"],
            "package_count": base_month["package_count"],
            "total_billed": base_month["total_billed"],
            "total_verified": 0.0,
            "total_difference": 0.0,
            "verified_packages": 0,
            "review_packages": base_month["package_count"],
            "invoices": [],
        }
        month_lookup[month["invoice_month"]] = month
        for base_invoice in base_month.get("invoices", []):
            invoice = {
                "invoice_number": base_invoice["invoice_number"],
                "package_count": base_invoice["package_count"],
                "total_billed": base_invoice["total_billed"],
                "total_verified": 0.0,
                "total_difference": 0.0,
                "verified_packages": 0,
                "review_packages": base_invoice["package_count"],
                "top_rows": [],
            }
            month["invoices"].append(invoice)
            invoice_lookup[(month["invoice_month"], invoice["invoice_number"])] = invoice

    total_verified = 0.0
    total_difference = 0.0
    verified_packages = 0

    for row in cursor.fetchall():
        try:
            billing_payload = json.loads(row.billing_payload or "{}")
        except Exception:
            billing_payload = {}
        payload = billing_payload

        actual_billed = parse_number(row.total_billed_charge)
        if actual_billed is None:
            actual_billed = parse_number(row.raw_Charge_Total)

        service_name = row.service_level or payload_value(payload, ["Service", "Service Level", "Service_Type", "ServiceType", "UPS Service"])
        stored_zone = parse_number(row.zone)
        if stored_zone is None:
            stored_zone = parse_number(payload_value(payload, ["Zone", "Zone_Short", "UPS Zone"]))
        destination_zip = normalize_zip(payload_value(payload, ["ZIP", "Zip Code", "Postal Code", "Destination ZIP"]))
        estimated_zone = estimated_zone_from_zip("29556", destination_zip)
        audit_zone = int(stored_zone) if stored_zone is not None else estimated_zone

        weight = parse_number(row.billed_weight)
        if weight is None:
            weight = parse_number(payload_value(payload, ["Billed Weight", "Shipment_Billed_Weight_LB", "Package_Billed_Weight_LB", "Weight", "Actual Weight"]))
        published_charge = parse_number(row.published_charge)
        if published_charge is None:
            published_charge = parse_number(payload_value(payload, ["Published Charge", "PublishedCharge", "List Charge", "Base Rate", "Transportation Charge"]))
        component_values = {
            "transportation_charge": parse_number(row.transportation_charge),
            "fuel_surcharge": parse_number(row.fuel_surcharge),
            "residential_surcharge": parse_number(row.residential_surcharge),
            "other_accessorial_charge": parse_number(row.other_accessorial_charge),
        }
        expected, reason, _detail = contract_expected_charge(
            contract_rules,
            payload,
            service_name,
            audit_zone,
            weight,
            published_charge,
            component_values,
        )
        difference = actual_billed - expected if actual_billed is not None and expected is not None else None
        is_verified = expected is not None and actual_billed is not None

        if is_verified:
            verified_packages += 1
            total_verified += expected
            total_difference += difference

        month_key = row.invoice_month
        month = month_lookup.setdefault(
            month_key,
            {
                "invoice_month": month_key,
                "invoice_count": 0,
                "package_count": 0,
                "total_billed": 0.0,
                "total_verified": 0.0,
                "total_difference": 0.0,
                "verified_packages": 0,
                "review_packages": 0,
                "invoices": [],
            },
        )
        invoice_key = (month_key, row.invoice_number)
        invoice = invoice_lookup.setdefault(
            invoice_key,
            {
                "invoice_number": row.invoice_number,
                "package_count": 0,
                "total_billed": 0.0,
                "total_verified": 0.0,
                "total_difference": 0.0,
                "verified_packages": 0,
                "review_packages": 0,
                "top_rows": [],
            },
        )
        if invoice not in month["invoices"]:
            month["invoices"].append(invoice)
            month["invoice_count"] += 1

        for target in (month, invoice):
            target["package_count"] += 1
            target["total_billed"] += actual_billed or 0
            if is_verified:
                target["verified_packages"] += 1
                target["total_verified"] += expected
                target["total_difference"] += difference
                target["review_packages"] = max(0, target["review_packages"] - 1)

        if len(invoice["top_rows"]) < 6:
            invoice["top_rows"].append(
                {
                    "tracking_number": row.tracking_number or "",
                    "weight": weight,
                    "zone": audit_zone,
                    "billed": actual_billed,
                    "expected": expected,
                    "difference": difference,
                    "reason": reason,
                }
            )

    months = sort_report_months(month_lookup.values())
    for month in months:
        month["invoices"].sort(key=lambda item: abs(item["total_difference"]), reverse=True)
    total_packages = sum(month["package_count"] for month in months)

    return {
        "contract_error": contract_error,
        "contract_rule_count": contract_rules.get("rule_count", 0),
        "contract_agreement_no": contract_rules.get("agreement_no"),
        "total_verified": total_verified,
        "total_difference": total_difference,
        "verified_packages": verified_packages,
        "review_packages": max(0, total_packages - verified_packages),
        "months": months,
    }


def get_ups_billing_analysis(limit=100):
    ensure_ups_table()
    ensure_actual_billing_table()
    conn = get_master_connection()
    cursor = conn.cursor()
    total_charged_expression = "total_billed_charge"
    invoice_month_expression = "COALESCE(NULLIF(LTRIM(RTRIM(invoice_month)), ''), 'Missing Invoice Date')"
    manifest_key_expression = "NULLIF(LTRIM(RTRIM(tracking_key)), '')"
    billing_key_expression = "NULLIF(LTRIM(RTRIM(billing_tracking_key)), '')"
    billing_key_expression_aliased = "NULLIF(LTRIM(RTRIM(b.billing_tracking_key)), '')"

    try:
        cursor.execute(
            """
            SELECT
                OBJECT_ID('khPriority.dbo.CarrierUPSRawData', 'U') AS manifest_table_id,
                OBJECT_ID('khPriority.dbo.CarrierUPSActualBilling', 'U') AS billing_table_id
            """
        )
        table_state = cursor.fetchone()
        if not table_state or not table_state.manifest_table_id or not table_state.billing_table_id:
            return empty_billing_analysis("Upload manifest and actual billing data before running the billing analysis.")

        cursor.execute(
            f"""
            SELECT
                (SELECT COUNT(DISTINCT {manifest_key_expression})
                 FROM khPriority.dbo.CarrierUPSRawData
                 WHERE {manifest_key_expression} IS NOT NULL) AS manifest_tracking_count,
                (SELECT COUNT(DISTINCT {billing_key_expression})
                 FROM khPriority.dbo.CarrierUPSActualBilling
                 WHERE {billing_key_expression} IS NOT NULL) AS billing_tracking_count,
                (SELECT COUNT(DISTINCT m.tracking_key)
                 FROM khPriority.dbo.CarrierUPSRawData m
                 INNER JOIN khPriority.dbo.CarrierUPSActualBilling b
                    ON m.tracking_key = b.billing_tracking_key
                 WHERE NULLIF(LTRIM(RTRIM(m.tracking_key)), '') IS NOT NULL) AS matched_tracking_count,
                (SELECT COUNT(DISTINCT m.tracking_key)
                 FROM khPriority.dbo.CarrierUPSRawData m
                 LEFT JOIN khPriority.dbo.CarrierUPSActualBilling b
                    ON m.tracking_key = b.billing_tracking_key
                 WHERE NULLIF(LTRIM(RTRIM(m.tracking_key)), '') IS NOT NULL
                   AND b.id IS NULL) AS manifest_missing_count,
                (SELECT COUNT(DISTINCT b.billing_tracking_key)
                 FROM khPriority.dbo.CarrierUPSActualBilling b
                 LEFT JOIN khPriority.dbo.CarrierUPSRawData m
                    ON b.billing_tracking_key = m.tracking_key
                 WHERE NULLIF(LTRIM(RTRIM(b.billing_tracking_key)), '') IS NOT NULL
                   AND m.id IS NULL) AS billing_unmatched_count,
                (SELECT COUNT(*)
                 FROM khPriority.dbo.CarrierUPSActualBilling
                 WHERE NULLIF(LTRIM(RTRIM(invoice_number)), '') IS NULL) AS missing_invoice_number_count
            """
        )
        totals = cursor.fetchone()

        cursor.execute(
            f"""
            SELECT
                {invoice_month_expression} AS payment_month,
                COUNT(DISTINCT {billing_key_expression}) AS package_count,
                SUM(COALESCE({total_charged_expression}, 0)) AS payment_amount
            FROM khPriority.dbo.CarrierUPSActualBilling
            GROUP BY {invoice_month_expression}
            ORDER BY payment_month DESC
            """
        )
        monthly_payments = [
            {
                "payment_month": row.payment_month,
                "package_count": row.package_count,
                "payment_amount": float(row.payment_amount or 0),
                "invoices": [],
            }
            for row in cursor.fetchall()
        ]
        monthly_lookup = {row["payment_month"]: row for row in monthly_payments}

        cursor.execute(
            f"""
            SELECT
                {invoice_month_expression} AS payment_month,
                COALESCE(NULLIF(LTRIM(RTRIM(invoice_number)), ''), 'Missing Invoice') AS invoice_number,
                COUNT(DISTINCT {billing_key_expression}) AS package_count,
                SUM(COALESCE({total_charged_expression}, 0)) AS payment_amount
            FROM khPriority.dbo.CarrierUPSActualBilling
            GROUP BY
                {invoice_month_expression},
                COALESCE(NULLIF(LTRIM(RTRIM(invoice_number)), ''), 'Missing Invoice')
            ORDER BY payment_month DESC, payment_amount DESC
            """
        )
        for row in cursor.fetchall():
            month = monthly_lookup.get(row.payment_month)
            if month is not None:
                month["invoices"].append(
                    {
                        "invoice_number": row.invoice_number,
                        "package_count": row.package_count,
                        "payment_amount": float(row.payment_amount or 0),
                    }
                )

        cursor.execute(
            f"""
            SELECT
                COALESCE(NULLIF(LTRIM(RTRIM(source_file)), ''), 'Unknown Source') AS source_file,
                COUNT(*) AS row_count,
                COUNT(DISTINCT {billing_key_expression}) AS package_count,
                SUM(COALESCE({total_charged_expression}, 0)) AS payment_amount,
                MIN(uploaded_at) AS first_uploaded_at,
                MAX(uploaded_at) AS last_uploaded_at
            FROM khPriority.dbo.CarrierUPSActualBilling
            GROUP BY COALESCE(NULLIF(LTRIM(RTRIM(source_file)), ''), 'Unknown Source')
            ORDER BY last_uploaded_at DESC, source_file
            """
        )
        source_files = [
            {
                "source_file": row.source_file,
                "row_count": row.row_count or 0,
                "package_count": row.package_count or 0,
                "payment_amount": float(row.payment_amount or 0),
                "first_uploaded_at": row.first_uploaded_at,
                "last_uploaded_at": row.last_uploaded_at,
            }
            for row in cursor.fetchall()
        ]

        cursor.execute(
            """
            SELECT TOP (?)
                m.tracking_number,
                m.invoice_number,
                m.source_file,
                m.recipient_name,
                m.zip_code,
                m.billed_weight,
                m.charge_amount
            FROM khPriority.dbo.CarrierUPSRawData m
            LEFT JOIN khPriority.dbo.CarrierUPSActualBilling b
                ON m.tracking_key = b.billing_tracking_key
            WHERE NULLIF(LTRIM(RTRIM(m.tracking_key)), '') IS NOT NULL
              AND b.id IS NULL
            ORDER BY m.id DESC
            """,
            limit,
        )
        manifest_missing_rows = [dict(zip([column[0] for column in cursor.description], row)) for row in cursor.fetchall()]

        cursor.execute(
            """
            SELECT TOP (?)
                COALESCE(b.tracking_number, b.raw_Tracking_No, b.billing_tracking_key) AS tracking_number,
                b.invoice_number,
                COALESCE(NULLIF(LTRIM(RTRIM(b.invoice_month)), ''), 'Missing Invoice Date') AS invoice_month,
                b.invoice_date,
                b.source_file,
                b.service_level,
                b.zone,
                b.billed_weight,
                b.total_billed_charge AS billed_amount
            FROM khPriority.dbo.CarrierUPSActualBilling b
            LEFT JOIN khPriority.dbo.CarrierUPSRawData m
                ON b.billing_tracking_key = m.tracking_key
            WHERE NULLIF(LTRIM(RTRIM(b.billing_tracking_key)), '') IS NOT NULL
              AND m.id IS NULL
            ORDER BY b.id DESC
            """,
            limit,
        )
        billing_unmatched_rows = [dict(zip([column[0] for column in cursor.description], row)) for row in cursor.fetchall()]

        cursor.execute(
            """
            SELECT TOP (?)
                tracking_number,
                invoice_number,
                invoice_date,
                source_file,
                service_level,
                total_billed_charge
            FROM khPriority.dbo.CarrierUPSActualBilling
            WHERE NULLIF(LTRIM(RTRIM(invoice_number)), '') IS NULL
            ORDER BY id DESC
            """,
            limit,
        )
        missing_invoice_rows = [dict(zip([column[0] for column in cursor.description], row)) for row in cursor.fetchall()]

        return {
            "error": None,
            "manifest_tracking_count": totals.manifest_tracking_count or 0,
            "billing_tracking_count": totals.billing_tracking_count or 0,
            "matched_tracking_count": totals.matched_tracking_count or 0,
            "manifest_missing_count": totals.manifest_missing_count or 0,
            "billing_unmatched_count": totals.billing_unmatched_count or 0,
            "missing_invoice_number_count": totals.missing_invoice_number_count or 0,
            "total_payment_amount": sum(row["payment_amount"] for row in monthly_payments),
            "total_billing_packages": sum(row["package_count"] for row in monthly_payments),
            "monthly_payments": monthly_payments,
            "source_files": source_files,
            "manifest_missing_rows": manifest_missing_rows,
            "billing_unmatched_rows": billing_unmatched_rows,
            "missing_invoice_rows": missing_invoice_rows,
        }
    finally:
        conn.close()


def get_ups_billing_report():
    ensure_actual_billing_table()
    conn = get_master_connection()
    cursor = conn.cursor()
    month_expression = "COALESCE(NULLIF(LTRIM(RTRIM(invoice_month)), ''), 'Missing Invoice Date')"
    invoice_expression = "COALESCE(NULLIF(LTRIM(RTRIM(invoice_number)), ''), 'Missing Invoice')"
    tracking_expression = "NULLIF(LTRIM(RTRIM(billing_tracking_key)), '')"
    amount_expression = "COALESCE(total_billed_charge, 0)"

    try:
        cursor.execute(
            """
            SELECT OBJECT_ID('khPriority.dbo.CarrierUPSActualBilling', 'U') AS billing_table_id
            """
        )
        table_state = cursor.fetchone()
        if not table_state or not table_state.billing_table_id:
            return empty_ups_billing_report("Upload actual billing data before opening the UPS billing report.")

        cursor.execute(
            f"""
            SELECT
                {month_expression} AS invoice_month,
                COUNT(DISTINCT {invoice_expression}) AS invoice_count,
                COUNT(DISTINCT {tracking_expression}) AS package_count,
                SUM({amount_expression}) AS total_billed
            FROM khPriority.dbo.CarrierUPSActualBilling
            GROUP BY {month_expression}
            ORDER BY
                CASE WHEN {month_expression} = 'Missing Invoice Date' THEN 1 ELSE 0 END,
                invoice_month DESC
            """
        )
        months = [
            {
                "invoice_month": row.invoice_month,
                "invoice_count": row.invoice_count or 0,
                "package_count": row.package_count or 0,
                "total_billed": float(row.total_billed or 0),
                "invoices": [],
            }
            for row in cursor.fetchall()
        ]
        month_lookup = {row["invoice_month"]: row for row in months}

        cursor.execute(
            f"""
            SELECT
                {month_expression} AS invoice_month,
                {invoice_expression} AS invoice_number,
                COUNT(DISTINCT {tracking_expression}) AS package_count,
                SUM({amount_expression}) AS total_billed,
                MIN(NULLIF(LTRIM(RTRIM(invoice_date)), '')) AS first_invoice_date,
                MAX(NULLIF(LTRIM(RTRIM(invoice_date)), '')) AS last_invoice_date
            FROM khPriority.dbo.CarrierUPSActualBilling
            GROUP BY {month_expression}, {invoice_expression}
            ORDER BY
                CASE WHEN {month_expression} = 'Missing Invoice Date' THEN 1 ELSE 0 END,
                invoice_month DESC,
                total_billed DESC,
                invoice_number
            """
        )
        total_invoices = 0
        for row in cursor.fetchall():
            month = month_lookup.get(row.invoice_month)
            if month is None:
                continue
            total_invoices += 1
            month["invoices"].append(
                {
                    "invoice_number": row.invoice_number,
                    "package_count": row.package_count or 0,
                    "total_billed": float(row.total_billed or 0),
                    "first_invoice_date": row.first_invoice_date or "",
                    "last_invoice_date": row.last_invoice_date or "",
                }
            )

        cursor.execute(
            f"""
            SELECT
                invoice_year,
                COUNT(DISTINCT invoice_number) AS invoice_count,
                COUNT(DISTINCT tracking_key) AS package_count,
                SUM(total_billed_charge) AS total_billed
            FROM (
                SELECT
                    CASE
                        WHEN {month_expression} = 'Missing Invoice Date' THEN 'Missing'
                        ELSE LEFT({month_expression}, 4)
                    END AS invoice_year,
                    {invoice_expression} AS invoice_number,
                    {tracking_expression} AS tracking_key,
                    {amount_expression} AS total_billed_charge
                FROM khPriority.dbo.CarrierUPSActualBilling
            ) year_rows
            GROUP BY invoice_year
            ORDER BY
                CASE WHEN invoice_year = 'Missing' THEN 1 ELSE 0 END,
                invoice_year DESC
            """
        )
        year_trends = [
            {
                "invoice_year": row.invoice_year,
                "invoice_count": row.invoice_count or 0,
                "package_count": row.package_count or 0,
                "total_billed": float(row.total_billed or 0),
            }
            for row in cursor.fetchall()
        ]

        month_trends = [
            {
                "invoice_month": row["invoice_month"],
                "invoice_count": row["invoice_count"],
                "package_count": row["package_count"],
                "total_billed": row["total_billed"],
            }
            for row in sorted(
                months,
                key=lambda item: (item["invoice_month"] == "Missing Invoice Date", item["invoice_month"]),
            )
        ]
        max_month_total = max([row["total_billed"] for row in month_trends] or [0])
        for row in month_trends:
            row["bar_width"] = round((row["total_billed"] / max_month_total) * 100, 1) if max_month_total else 0

        cursor.execute(
            """
            SELECT COUNT(*) AS missing_date_rows
            FROM khPriority.dbo.CarrierUPSActualBilling
            WHERE NULLIF(LTRIM(RTRIM(invoice_month)), '') IS NULL
            """
        )
        missing_date_row = cursor.fetchone()
        cursor.execute(
            """
            SELECT
                COALESCE(NULLIF(LTRIM(RTRIM(source_file)), ''), 'Unknown Source') AS source_file,
                COUNT(*) AS row_count,
                MIN(uploaded_at) AS first_uploaded_at,
                MAX(uploaded_at) AS last_uploaded_at
            FROM khPriority.dbo.CarrierUPSActualBilling
            WHERE NULLIF(LTRIM(RTRIM(invoice_month)), '') IS NULL
            GROUP BY COALESCE(NULLIF(LTRIM(RTRIM(source_file)), ''), 'Unknown Source')
            ORDER BY row_count DESC, source_file
            """
        )
        missing_date_sources = [
            {
                "source_file": row.source_file,
                "row_count": row.row_count or 0,
                "first_uploaded_at": row.first_uploaded_at,
                "last_uploaded_at": row.last_uploaded_at,
            }
            for row in cursor.fetchall()
        ]
        verified_report = build_ups_verified_report(cursor, months)

        return {
            "error": None,
            "total_months": len(months),
            "total_invoices": total_invoices,
            "total_packages": sum(row["package_count"] for row in months),
            "total_billed": sum(row["total_billed"] for row in months),
            "verified": verified_report,
            "months": months,
            "year_trends": year_trends,
            "month_trends": month_trends,
            "missing_date_rows": missing_date_row.missing_date_rows if missing_date_row else 0,
            "missing_date_sources": missing_date_sources,
        }
    finally:
        conn.close()


def upload_ups_rows(folder_path, rows, uploaded_by=None):
    ensure_ups_table()
    batch_id = str(uuid.uuid4())
    conn = get_master_connection()
    cursor = conn.cursor()
    cursor.fast_executemany = True

    insert_params = []
    for row in rows:
        tracking_no = first_matching(row, ["Tracking ID", "Tracking Number", "TrackingNumber", "Tracking_Number", "Tracking", "ShipmentID", "Shipment_ID"])
        insert_params.append(
            (
                batch_id,
                text_or_none(folder_path),
                text_or_none(row.get("_SourceFile"), 500),
                row.get("_RowNumber"),
                tracking_key(tracking_no),
                text_or_none(first_matching(row, ["Invoice Number", "InvoiceNumber", "Invoice_No", "InvoiceNo"]), 255),
                text_or_none(tracking_no, 255),
                text_or_none(first_matching(row, ["ShipmentDate", "ShipDate", "Ship_Date", "Date"]), 120),
                text_or_none(first_matching(row, ["Consignee Name", "RecipientName", "Recipient", "Consignee", "ShipToName", "Ship_To_Name"]), 500),
                text_or_none(first_matching(row, ["City", "Consignee City", "ShipToCity", "Ship_To_City"]), 255),
                text_or_none(first_matching(row, ["State", "State Code", "Province", "ShipToState", "Ship_To_State"]), 80),
                text_or_none(first_matching(row, ["Zip Code", "Zip", "Postal Code", "Postcode", "ShipToZip", "Ship_To_Zip"]), 80),
                text_or_none(first_matching(row, ["Zone", "UPS Zone"]), 80),
                decimal_or_none(first_matching(row, ["Weight", "Billed Weight", "BilledWeight", "Actual Weight", "Package Weight"])),
                text_or_none(first_matching(row, ["Residential Flag", "ResidentialFlag", "Residential", "Is Residential"]), 80),
                text_or_none(first_matching(row, ["ServiceLevel", "Service Level", "Service", "Service_Type", "UPSService"]), 255),
                text_or_none(first_matching(row, ["Status", "ShipmentStatus", "Shipment_Status", "DeliveryStatus"]), 255),
                decimal_or_none(first_matching(row, ["Charge", "Charges", "Amount", "TotalCharge", "Total_Charge", "Cost"])),
                decimal_or_none(first_matching(row, ["COD Amount", "CODAmount", "COD"])),
                decimal_or_none(first_matching(row, ["Declared Value", "DeclaredValue"])),
                decimal_or_none(first_matching(row, ["Add On Cost", "AddOnCost", "Addon Cost", "Accessorial Cost"])),
                json.dumps(row, ensure_ascii=False, default=str),
                uploaded_by,
            ),
        )
    cursor.executemany(
        """
        INSERT INTO khPriority.dbo.CarrierUPSRawData (
            upload_batch_id,
            source_folder,
            source_file,
            source_row_number,
            tracking_key,
            invoice_number,
            tracking_number,
            shipment_date,
            recipient_name,
            city,
            state_code,
            zip_code,
            zone,
            billed_weight,
            residential_flag,
            service_level,
            shipment_status,
            charge_amount,
            cod_amount,
            declared_value,
            add_on_cost,
            raw_payload,
            uploaded_by
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        insert_params,
    )

    conn.commit()
    conn.close()
    return batch_id
