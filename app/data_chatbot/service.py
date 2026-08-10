import os
import re
import uuid
from decimal import Decimal
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from app.database.connection_manager import get_master_connection

try:
    import anthropic
except Exception:
    anthropic = None


EXPORT_DIR = Path(__file__).resolve().parents[2] / "data" / "chatbot_exports"
FORBIDDEN_SQL = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|merge|exec|execute|create|grant|revoke)\b",
    re.IGNORECASE,
)
DATE_TERMS = ("date", "month", "period", "created", "uploaded")
AMOUNT_TERMS = ("amount", "charge", "payment", "cost", "value", "revenue", "total")
AMOUNT_EXCLUDE_TERMS = ("weight", "lbs", "lb", "qty", "quantity", "count", "number", "no")
WEIGHT_TERMS = ("weight", "lbs", "lb")
TRACKING_TERMS = ("tracking", "shipment", "invoice")
CHART_TERMS = ("chart", "graph", "trend", "visual", "visualize", "plot", "month", "monthly", "compare", "comparison")


def ensure_chatbot_tables():
    conn = get_master_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        IF NOT EXISTS (
            SELECT 1 FROM khPriority.INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = 'dbo'
              AND TABLE_NAME = 'AIChatbotAssignedTables'
        )
        CREATE TABLE khPriority.dbo.AIChatbotAssignedTables (
            id INT IDENTITY(1,1) PRIMARY KEY,
            table_schema NVARCHAR(128) NOT NULL,
            table_name NVARCHAR(256) NOT NULL,
            display_name NVARCHAR(300) NULL,
            user_id INT NULL,
            assigned_by_user_id INT NULL,
            is_active BIT NOT NULL DEFAULT 1,
            assigned_at DATETIME NOT NULL DEFAULT GETDATE(),
            CONSTRAINT UQ_AIChatbotAssignedTables UNIQUE (table_schema, table_name)
        )
        """
    )
    cursor.execute(
        """
        IF COL_LENGTH('khPriority.dbo.AIChatbotAssignedTables', 'user_id') IS NULL
            ALTER TABLE khPriority.dbo.AIChatbotAssignedTables ADD user_id INT NULL
        IF COL_LENGTH('khPriority.dbo.AIChatbotAssignedTables', 'assigned_by_user_id') IS NULL
            ALTER TABLE khPriority.dbo.AIChatbotAssignedTables ADD assigned_by_user_id INT NULL
        IF EXISTS (
            SELECT 1
            FROM khPriority.sys.key_constraints
            WHERE [name] = 'UQ_AIChatbotAssignedTables'
              AND parent_object_id = OBJECT_ID('khPriority.dbo.AIChatbotAssignedTables')
        )
            ALTER TABLE khPriority.dbo.AIChatbotAssignedTables DROP CONSTRAINT UQ_AIChatbotAssignedTables
        IF NOT EXISTS (
            SELECT 1
            FROM khPriority.sys.indexes
            WHERE [name] = 'UX_AIChatbotAssignedTables_UserTable'
              AND object_id = OBJECT_ID('khPriority.dbo.AIChatbotAssignedTables')
        )
            CREATE UNIQUE INDEX UX_AIChatbotAssignedTables_UserTable
            ON khPriority.dbo.AIChatbotAssignedTables(user_id, table_schema, table_name)
        """
    )
    conn.commit()
    conn.close()


def split_table_name(full_name):
    text = str(full_name or "").strip().replace("[", "").replace("]", "")
    parts = [part for part in text.split(".") if part]
    if len(parts) == 1:
        return "dbo", parts[0]
    return parts[-2], parts[-1]


def quote_name(value):
    return "[" + str(value or "").replace("]", "]]") + "]"


def table_sql_name(schema, table):
    return f"khPriority.{quote_name(schema)}.{quote_name(table)}"


def discover_tables(search=""):
    ensure_chatbot_tables()
    conn = get_master_connection()
    cursor = conn.cursor()
    params = []
    where = "WHERE TABLE_TYPE = 'BASE TABLE'"
    if search:
        where += " AND (TABLE_NAME LIKE ? OR TABLE_SCHEMA LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])
    cursor.execute(
        f"""
        SELECT TOP 250 TABLE_SCHEMA, TABLE_NAME
        FROM khPriority.INFORMATION_SCHEMA.TABLES
        {where}
        ORDER BY TABLE_SCHEMA, TABLE_NAME
        """,
        params,
    )
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "schema": row.TABLE_SCHEMA,
            "table": row.TABLE_NAME,
            "full_name": f"{row.TABLE_SCHEMA}.{row.TABLE_NAME}",
        }
        for row in rows
    ]


def get_chatbot_users(admin_user=None):
    conn = get_master_connection()
    cursor = conn.cursor()
    where = "WHERE is_active = 1"
    params = []
    if admin_user and getattr(admin_user, "role_name", "") == "org_admin":
        where += " AND org_id = ?"
        params.append(admin_user.org_id)
    cursor.execute(
        f"""
        SELECT id, org_id, full_name, email, username, role_name
        FROM khPriority.dbo.Users
        {where}
        ORDER BY full_name, username
        """,
        params,
    )
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "id": int(row.id),
            "org_id": row.org_id,
            "full_name": row.full_name,
            "email": row.email,
            "username": row.username,
            "role_name": row.role_name,
        }
        for row in rows
    ]


def get_assigned_tables(user_id=None, include_global=True):
    ensure_chatbot_tables()
    conn = get_master_connection()
    cursor = conn.cursor()
    if user_id:
        cursor.execute(
            """
            SELECT table_schema, table_name, display_name, assigned_at, user_id
            FROM khPriority.dbo.AIChatbotAssignedTables
            WHERE is_active = 1
              AND user_id = ?
            ORDER BY assigned_at DESC
            """,
            int(user_id),
        )
        rows = cursor.fetchall()
        if not rows and include_global:
            cursor.execute(
                """
                SELECT table_schema, table_name, display_name, assigned_at, user_id
                FROM khPriority.dbo.AIChatbotAssignedTables
                WHERE is_active = 1
                  AND user_id IS NULL
                ORDER BY assigned_at DESC
                """
            )
            rows = cursor.fetchall()
    else:
        cursor.execute(
            """
            SELECT table_schema, table_name, display_name, assigned_at, user_id
        FROM khPriority.dbo.AIChatbotAssignedTables
        WHERE is_active = 1
        ORDER BY assigned_at DESC
            """
        )
        rows = cursor.fetchall()
    conn.close()
    return [
        {
            "schema": row.table_schema,
            "table": row.table_name,
            "display_name": row.display_name or row.table_name,
            "full_name": f"{row.table_schema}.{row.table_name}",
            "sql_name": table_sql_name(row.table_schema, row.table_name),
            "user_id": row.user_id,
        }
        for row in rows
    ]


def get_assignment_rows(admin_user=None):
    ensure_chatbot_tables()
    conn = get_master_connection()
    cursor = conn.cursor()
    params = []
    user_filter = ""
    if admin_user and getattr(admin_user, "role_name", "") == "org_admin":
        user_filter = "AND u.org_id = ?"
        params.append(admin_user.org_id)
    cursor.execute(
        f"""
        SELECT
            a.table_schema,
            a.table_name,
            a.display_name,
            a.assigned_at,
            a.user_id,
            u.full_name,
            u.username,
            u.email
        FROM khPriority.dbo.AIChatbotAssignedTables a
        LEFT JOIN khPriority.dbo.Users u ON u.id = a.user_id
        WHERE a.is_active = 1
          {user_filter}
        ORDER BY COALESCE(u.full_name, 'All users'), a.assigned_at DESC
        """,
        params,
    )
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "schema": row.table_schema,
            "table": row.table_name,
            "display_name": row.display_name or row.table_name,
            "full_name": f"{row.table_schema}.{row.table_name}",
            "assigned_at": row.assigned_at,
            "user_id": row.user_id,
            "user_name": row.full_name or "All users",
            "username": row.username or "",
            "email": row.email or "",
        }
        for row in rows
    ]


def assign_table(full_name, display_name=None, user_id=None, assigned_by_user_id=None):
    ensure_chatbot_tables()
    schema, table = split_table_name(full_name)
    user_id = int(user_id) if str(user_id or "").strip() else None
    assigned_by_user_id = int(assigned_by_user_id) if str(assigned_by_user_id or "").strip() else None
    conn = get_master_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        IF EXISTS (
            SELECT 1 FROM khPriority.dbo.AIChatbotAssignedTables
            WHERE table_schema = ? AND table_name = ?
              AND ((user_id = ?) OR (user_id IS NULL AND ? IS NULL))
        )
            UPDATE khPriority.dbo.AIChatbotAssignedTables
            SET is_active = 1,
                display_name = COALESCE(NULLIF(?, ''), display_name),
                assigned_by_user_id = ?,
                assigned_at = GETDATE()
            WHERE table_schema = ? AND table_name = ?
              AND ((user_id = ?) OR (user_id IS NULL AND ? IS NULL))
        ELSE
            INSERT INTO khPriority.dbo.AIChatbotAssignedTables
                (table_schema, table_name, display_name, user_id, assigned_by_user_id)
            VALUES (?, ?, NULLIF(?, ''), ?, ?)
        """,
        schema,
        table,
        user_id,
        user_id,
        display_name or "",
        assigned_by_user_id,
        schema,
        table,
        user_id,
        user_id,
        schema,
        table,
        display_name or "",
        user_id,
        assigned_by_user_id,
    )
    conn.commit()
    conn.close()


def remove_table(full_name, user_id=None):
    ensure_chatbot_tables()
    schema, table = split_table_name(full_name)
    user_id = int(user_id) if str(user_id or "").strip() else None
    conn = get_master_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE khPriority.dbo.AIChatbotAssignedTables
        SET is_active = 0
        WHERE table_schema = ? AND table_name = ?
          AND ((user_id = ?) OR (user_id IS NULL AND ? IS NULL))
        """,
        schema,
        table,
        user_id,
        user_id,
    )
    conn.commit()
    conn.close()


def get_table_columns(schema, table):
    conn = get_master_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT COLUMN_NAME, DATA_TYPE
        FROM khPriority.INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = ?
          AND TABLE_NAME = ?
        ORDER BY ORDINAL_POSITION
        """,
        schema,
        table,
    )
    rows = cursor.fetchall()
    conn.close()
    return [{"name": row.COLUMN_NAME, "type": row.DATA_TYPE} for row in rows]


def build_schema_context(assigned):
    context = []
    for table in assigned[:8]:
        columns = get_table_columns(table["schema"], table["table"])[:40]
        table["columns"] = columns
        context.append(
            {
                "table": table["full_name"],
                "sql_name": table["sql_name"],
                "columns": columns,
            }
        )
    return context


def default_query_for_message(message, assigned):
    if not assigned:
        return None, "No assigned data tables yet."

    lower = str(message or "").lower()
    if "table" in lower and any(word in lower for word in ["assigned", "available", "access"]):
        return None, "Assigned tables are ready."

    table = assigned[0]
    columns = get_table_columns(table["schema"], table["table"])
    select_cols = ", ".join(quote_name(col["name"]) for col in columns[:12]) or "*"
    sql = f"SELECT TOP 50 {select_cols} FROM {table['sql_name']}"
    return sql, f"I opened a preview from {table['full_name']}."


def column_matches(column, terms):
    name = str(column.get("name") or "").lower()
    return any(term in name for term in terms)


def pick_column(columns, terms):
    for column in columns:
        if column_matches(column, terms):
            return column["name"]
    return None


def pick_date_column(columns):
    date_types = {"date", "datetime", "datetime2", "smalldatetime"}
    for column in columns:
        if str(column.get("type") or "").lower() in date_types:
            return column["name"]
    return pick_column(columns, DATE_TERMS)


def pick_amount_column(columns):
    candidates = []
    for column in columns:
        name = str(column.get("name") or "").lower()
        if any(term in name for term in AMOUNT_EXCLUDE_TERMS):
            continue
        if any(term in name for term in AMOUNT_TERMS):
            score = 0
            if "total" in name:
                score += 4
            if "charge" in name or "amount" in name:
                score += 3
            if "raw_charge_total" in name:
                score += 8
            candidates.append((score, column["name"]))
    if not candidates:
        return None
    return sorted(candidates, reverse=True)[0][1]


def table_score(message, table):
    text = str(message or "").lower()
    tokens = [part for part in re.split(r"[^a-z0-9]+", text) if len(part) > 2]
    haystack = f"{table['full_name']} {table.get('display_name') or ''}".lower()
    return sum(1 for token in tokens if token in haystack)


def pick_table_for_message(message, assigned):
    return sorted(assigned, key=lambda table: table_score(message, table), reverse=True)[0]


def select_preview_columns(columns, message):
    lower = str(message or "").lower()
    priority_terms = list(TRACKING_TERMS + DATE_TERMS + AMOUNT_TERMS + WEIGHT_TERMS)
    if "zip" in lower or "postal" in lower:
        priority_terms = ["zip", "postal", "state"] + priority_terms
    priority = [col for col in columns if column_matches(col, priority_terms)]
    remaining = [col for col in columns if col not in priority]
    selected = (priority + remaining)[:14]
    return selected or columns[:14]


def extract_limit(message, default=50, maximum=200):
    match = re.search(r"\b(?:top|first|show)\s+(\d{1,4})\b", str(message or "").lower())
    if not match:
        return default
    return max(1, min(int(match.group(1)), maximum))


def conversation_context_text(history):
    turns = []
    for item in (history or [])[-8:]:
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            turns.append(f"{role}: {content[:900]}")
    return "\n".join(turns)


def contextual_message(message, history):
    context = conversation_context_text(history)
    if not context:
        return message
    lower = str(message or "").lower()
    followup_terms = ("same", "that", "those", "previous", "above", "again", "now", "also", "trend", "chart", "graph")
    if any(term in lower for term in followup_terms):
        return f"Previous conversation:\n{context}\n\nCurrent user question: {message}"
    return message


def build_local_plan(message, assigned, history=None):
    if not assigned:
        return {"sql": "", "answer": "No assigned data tables yet."}

    effective_message = contextual_message(message, history)
    lower = str(effective_message or "").lower()
    table = pick_table_for_message(effective_message, assigned)
    columns = get_table_columns(table["schema"], table["table"])
    if not columns:
        return {"sql": "", "answer": f"I could not read column metadata for {table['full_name']}."}

    if any(word in lower for word in ["column", "columns", "schema", "fields", "structure"]):
        rows = [
            {
                "Table": table["full_name"],
                "Column": column["name"],
                "Data Type": column["type"],
            }
            for column in columns
        ]
        return {
            "sql": "",
            "answer": f"Here is the column structure for {table['full_name']}.",
            "columns": ["Table", "Column", "Data Type"],
            "local_rows": rows,
            "title": f"{table['full_name']} Columns",
        }

    if any(word in lower for word in ["count", "total rows", "how many rows", "record count"]):
        return {
            "sql": f"SELECT COUNT(1) AS TotalRows FROM {table['sql_name']}",
            "answer": f"I counted the rows in {table['full_name']}.",
            "title": f"{table['full_name']} Row Count",
        }

    wants_month = any(word in lower for word in ["month", "monthly", "by month", "trend"])
    wants_sum = any(word in lower for word in ["sum", "total", "amount", "charge", "payment", "bill", "value"])
    date_col = pick_date_column(columns)
    amount_col = pick_amount_column(columns)
    if wants_month and wants_sum and date_col and amount_col:
        sql = f"""
        SELECT TOP 120
            CONVERT(CHAR(7), TRY_CAST({quote_name(date_col)} AS DATE), 120) AS MonthYear,
            COUNT(1) AS [RowCount],
            SUM(TRY_CAST({quote_name(amount_col)} AS DECIMAL(18, 4))) AS [TotalAmount]
        FROM {table['sql_name']}
        WHERE TRY_CAST({quote_name(date_col)} AS DATE) IS NOT NULL
        GROUP BY CONVERT(CHAR(7), TRY_CAST({quote_name(date_col)} AS DATE), 120)
        ORDER BY MonthYear DESC
        """
        return {
            "sql": sql,
            "answer": f"I summarized {table['full_name']} by month using {date_col} and {amount_col}.",
            "title": f"{table['full_name']} Monthly Summary",
        }

    if wants_sum and amount_col:
        sql = f"""
        SELECT
            COUNT(1) AS [RowCount],
            SUM(TRY_CAST({quote_name(amount_col)} AS DECIMAL(18, 4))) AS [TotalAmount],
            AVG(TRY_CAST({quote_name(amount_col)} AS DECIMAL(18, 4))) AS [AvgAmount]
        FROM {table['sql_name']}
        """
        return {
            "sql": sql,
            "answer": f"I summarized the amount field {amount_col} from {table['full_name']}.",
            "title": f"{table['full_name']} Amount Summary",
        }

    limit = extract_limit(effective_message)
    selected = select_preview_columns(columns, effective_message)
    select_cols = ", ".join(quote_name(column["name"]) for column in selected)
    order_col = pick_date_column(columns) or selected[0]["name"]
    sql = f"SELECT TOP {limit} {select_cols} FROM {table['sql_name']} ORDER BY {quote_name(order_col)} DESC"
    return {
        "sql": sql,
        "answer": f"I pulled {limit} row(s) from {table['full_name']} using the most relevant fields.",
        "title": f"{table['full_name']} Preview",
    }


def anthropic_client():
    if anthropic is None:
        return None
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    return anthropic.Anthropic(api_key=api_key)


def plan_sql_with_ai(message, assigned, history=None):
    client = anthropic_client()
    if not client or not assigned:
        return None

    schema_context = build_schema_context(assigned)
    system_prompt="""
    You are a SQL Server data assistant for a Flask operations chatbot.

    Return valid JSON only with these keys:
    {
    "sql": "",
    "answer": "",
    "output_style": "text|table|document|chart"
    }

    Core rules:

    1. Use only the assigned tables and columns provided below.
    2. Generate only one read-only SQL Server SELECT query.
    3. Never use INSERT, UPDATE, DELETE, DROP, ALTER, EXEC, MERGE, TRUNCATE, temp tables, CTE modification, or semicolons.
    4. Unless using aggregation, always limit results with TOP 200 or fewer.
    5. Prefer aggregation for summaries, counts, sums, averages, rankings, and trends.
    6. If the question does not require database data, return:

    * sql: ""
    * answer: natural helpful answer
    * output_style: "text"
    7. If the answer cannot be found from the assigned tables, return sql as empty and explain clearly in answer.
    8. If the user question is vague, make the best reasonable interpretation and return a safe query with explanation.
    9. Always provide useful business insight in answer, not only raw data.

    Output style rules:

    * Use "table" for detailed records.
    * Use "document" when results are fewer than 10 rows or the user asks for explanation/report.
    * Use "chart" for trends, monthly movement, comparison over time, or performance analysis.
    * Use "text" for simple answers without tabular data.

    SQL logic rules:

    * For counts, totals, averages, percentages, rankings, and trends, use SQL aggregation.
    * For specific record details, select only relevant columns.
    * For latest data questions:

    * Identify the most suitable date column from the assigned columns.
    * Use MAX(date_column) logic.
    * Return only records from the latest available date.
    * For style/code searches:

    * If the user enters a style with a dash, also search using the part before the dash.
    * Example: if user asks for "JHA001-BLK", also search related data for "JHA001".

    Quality check before final response:

    * Confirm the SQL uses only assigned tables/columns.
    * Confirm the query is read-only.
    * Confirm TOP 200 is used where required.
    * Confirm JSON is valid.
    * Do not include markdown, comments, or explanation outside JSON.

    Assigned tables and columns:
    {{ASSIGNED_TABLES_AND_COLUMNS}}

    """
#     system_prompt = """You are a SQL Server data assistant for a Flask operations app.
# Return JSON only with keys: sql, answer, output_style.
# Rules:
# - Use only the provided assigned tables and columns.
# - Generate only one read-only SELECT query.
# - Always include TOP 200 or fewer unless aggregating.
# - Prefer aggregates for summaries.
# - Do not use INSERT, UPDATE, DELETE, DROP, ALTER, EXEC, temp tables, or semicolons.
# - If the question does not need data, set sql to an empty string and answer naturally.
# - output_style can be text, table, or document.
# - If the question is vague, provide a best effort answer but do not return an empty sql without explanation.
# - If you cannot answer from the assigned tables, return sql as empty and explain in the answer
# - Always think step by step and double check the SQL syntax and rules before returning.
# - Here is the list of assigned tables with their columns
# - if records are less then 10 then return them in document style otherwise return in table style
# - If the question is about counts, sums, averages, or trends, use SQL aggregation functions
# - If the question is about specific details, use a SELECT with relevant columns
# - If the question is about the trend please return a chart with smarter insights and not just raw data
# - Always try to provide insights in the answer, not just raw data
# - if question is about the data latest date then please find the latest date column and return the latest record based on that date column do not return the records other dates, should read max date data accordingly
# - if user requiring the give me data chech in data if any style has use dashed in the data give complete before dashed and give me all related data
# """
    context = conversation_context_text(history)
    user_prompt = (
        f"Assigned tables:\n{schema_context}\n\n"
        f"Recent conversation:\n{context or 'No previous turns.'}\n\n"
        f"Current user question: {message}"
    )
    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=900,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = response.content[0].text.strip()
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return None
        import json

        return json.loads(match.group(0))
    except Exception:
        return None


def normalize_sql_for_validation(sql):
    return re.sub(r"\s+", " ", str(sql or "").strip())


def validate_sql(sql, assigned):
    sql = normalize_sql_for_validation(sql)
    if not sql:
        return ""
    if ";" in sql or FORBIDDEN_SQL.search(sql):
        raise ValueError("Only one read-only SELECT query is allowed.")
    if not re.match(r"^select\b", sql, re.I):
        raise ValueError("Only SELECT queries are allowed.")

    allowed = {
        table["sql_name"].replace("[", "").replace("]", "").lower(): table
        for table in assigned
    }
    refs = re.findall(r"\b(?:from|join)\s+([a-zA-Z0-9_\.\[\]]+)", sql, re.I)
    for ref in refs:
        normalized = ref.replace("[", "").replace("]", "").lower()
        if normalized.startswith("khpriority."):
            key = normalized
        elif normalized.count(".") == 1:
            key = "khpriority." + normalized
        else:
            key = None
        if key not in allowed:
            raise ValueError(f"Table is not assigned for chatbot access: {ref}")

    if not re.search(r"\btop\s+\d+\b", sql, re.I) and not re.search(r"\b(count|sum|avg|min|max)\s*\(", sql, re.I):
        sql = re.sub(r"^select\s+", "SELECT TOP 200 ", sql, flags=re.I)
    return sql


def run_query(sql):
    conn = get_master_connection()
    cursor = conn.cursor()
    cursor.execute(sql)
    columns = [column[0] for column in cursor.description]
    rows = [
        {column: serialize_value(value) for column, value in zip(columns, row)}
        for row in cursor.fetchall()
    ]
    conn.close()
    return columns, rows


def serialize_value(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return value


def summarize_result(message, rows, columns, planned_answer=""):
    if not rows:
        return planned_answer or "I checked the assigned data and did not find matching rows."
    if planned_answer:
        return planned_answer
    return f"I found {len(rows):,} row(s). The most useful fields are shown below."


def format_value_for_answer(value):
    if value is None:
        return "blank"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


def build_natural_fallback_answer(message, rows, columns, planned_answer=""):
    if not rows:
        return planned_answer or "I checked the assigned data, but I did not find matching rows for that question."

    row_count = len(rows)
    visible_columns = list(columns or [])[:6]
    first_row = rows[0] if rows else {}
    highlights = []
    for column in visible_columns[:4]:
        value = first_row.get(column)
        if value not in (None, ""):
            highlights.append(f"**{column}:** {format_value_for_answer(value)}")

    opening = planned_answer or f"I found {row_count:,} matching row(s) for your question."
    parts = [opening]
    if row_count == 1 and highlights:
        parts.append("Here is the main record I found:\n- " + "\n- ".join(highlights))
    elif highlights:
        parts.append(
            f"The first result starts with " + ", ".join(highlights[:3]) + "."
        )
    parts.append("I've included the table below so you can review the exact records and download them if needed.")
    return "\n\n".join(parts)


def polish_answer_with_ai(message, rows, columns, planned_answer=""):
    client = anthropic_client()
    if not client or not rows:
        return build_natural_fallback_answer(message, rows, columns, planned_answer)

    preview_rows = rows[:8]
    safe_columns = list(columns or [])[:12]
    prompt = {
        "question": message,
        "draft_answer": planned_answer,
        "row_count": len(rows),
        "columns": safe_columns,
        "preview_rows": [
            {column: row.get(column) for column in safe_columns}
            for row in preview_rows
        ],
    }
    system_prompt = """You write concise, professional analytics answers for a business data chatbot.
Use a natural ChatGPT-like tone. Give the answer first, then 2-4 useful takeaways when the data supports them.
Do not invent facts beyond the supplied rows. Mention that the table below has the exact records when useful.
Use simple Markdown: short paragraphs, bullets, and bold labels. Do not output HTML."""
    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=450,
            system=system_prompt,
            messages=[{"role": "user", "content": str(prompt)}],
        )
        text = response.content[0].text.strip()
        return text or build_natural_fallback_answer(message, rows, columns, planned_answer)
    except Exception:
        return build_natural_fallback_answer(message, rows, columns, planned_answer)


def numeric_value(value):
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", ""))
    except Exception:
        return None


def is_numeric_column(rows, column):
    values = [numeric_value(row.get(column)) for row in (rows or [])[:40]]
    values = [value for value in values if value is not None]
    return bool(values) and len(values) >= max(1, min(3, len(rows or [])))


def choose_chart_label_column(columns, rows):
    if not columns:
        return None
    lowered = {column: str(column).lower() for column in columns}
    for column, lower in lowered.items():
        if any(term in lower for term in ("month", "date", "period", "year", "week", "day")):
            return column
    for column in columns:
        if not is_numeric_column(rows, column):
            return column
    return columns[0]


def build_chart_config(message, rows, columns, output_style=""):
    if not rows or len(rows) < 2 or not columns:
        return None

    lower = str(message or "").lower()
    wants_chart = str(output_style or "").lower() == "chart" or any(term in lower for term in CHART_TERMS)
    label_col = choose_chart_label_column(columns, rows)
    numeric_cols = [column for column in columns if column != label_col and is_numeric_column(rows, column)]
    if not label_col or not numeric_cols:
        return None

    if not wants_chart and len(numeric_cols) > 2 and not any("month" in str(column).lower() for column in columns):
        return None

    chart_rows = list(rows[:40])
    if any(term in str(label_col).lower() for term in ("month", "date", "period", "year")):
        chart_rows = list(reversed(chart_rows))

    datasets = []
    for column in numeric_cols[:3]:
        points = []
        for row in chart_rows:
            value = numeric_value(row.get(column))
            points.append(value if value is not None else 0)
        datasets.append({"label": column, "values": points})

    chart_type = "line" if any(term in lower for term in ("trend", "month", "monthly", "date", "time")) else "bar"
    if any(term in str(label_col).lower() for term in ("month", "date", "period", "year")):
        chart_type = "line"

    return {
        "type": chart_type,
        "title": "Visual trend" if chart_type == "line" else "Visual comparison",
        "label_column": label_col,
        "labels": [format_value_for_answer(row.get(label_col)) for row in chart_rows],
        "datasets": datasets,
    }


def save_excel_export(title, rows):
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    export_id = uuid.uuid4().hex
    filename = f"{export_id}.xlsx"
    path = EXPORT_DIR / filename
    df = pd.DataFrame(rows or [])
    if df.empty:
        df = pd.DataFrame([{"Result": "No rows"}])
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Data", index=False)
        meta = pd.DataFrame(
            [
                {"Field": "Title", "Value": title or "Data Chatbot Export"},
                {"Field": "Generated", "Value": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
                {"Field": "Rows", "Value": len(rows or [])},
            ]
        )
        meta.to_excel(writer, sheet_name="Summary", index=False)
    return export_id


def build_chat_response(message, user_id=None, history=None):
    assigned = get_assigned_tables(user_id=user_id)
    if not assigned:
        return {
            "answer": "No tables are assigned to your chatbot access yet. Please ask an admin to assign the data sources you need, then I can answer from them.",
            "rows": [],
            "columns": [],
            "sql": "",
            "export_id": None,
            "assigned": [],
            "chart": None,
        }

    effective_message = contextual_message(message, history)
    ai_plan = plan_sql_with_ai(message, assigned, history=history)
    plan = ai_plan or build_local_plan(message, assigned, history=history)
    planned_answer = str(plan.get("answer") or "").strip()
    sql = str(plan.get("sql") or "").strip()
    output_style = str(plan.get("output_style") or "").strip().lower()

    if plan.get("local_rows") is not None:
        rows = plan.get("local_rows") or []
        columns = plan.get("columns") or (list(rows[0].keys()) if rows else [])
        export_id = save_excel_export(plan.get("title") or "Data Chatbot Result", rows)
        chart = build_chart_config(effective_message, rows, columns, output_style)
        return {
            "answer": build_natural_fallback_answer(message, rows, columns, planned_answer),
            "rows": rows[:100],
            "columns": columns,
            "sql": "",
            "export_id": export_id,
            "row_count": len(rows),
            "shown_count": min(len(rows), 100),
            "assigned": assigned,
            "chart": chart,
        }

    if not sql:
        return {
            "answer": planned_answer or "I can help with summaries, comparisons, previews, and downloadable reports from the assigned tables.",
            "rows": [],
            "columns": [],
            "sql": "",
            "export_id": None,
            "assigned": assigned,
            "chart": None,
        }

    try:
        sql = validate_sql(sql, assigned)
    except Exception:
        fallback = build_local_plan(message, assigned, history=history)
        if fallback.get("local_rows") is not None:
            rows = fallback.get("local_rows") or []
            columns = fallback.get("columns") or (list(rows[0].keys()) if rows else [])
            export_id = save_excel_export(fallback.get("title") or "Data Chatbot Result", rows)
            chart = build_chart_config(effective_message, rows, columns, fallback.get("output_style") or output_style)
            return {
                "answer": build_natural_fallback_answer(message, rows, columns, fallback.get("answer") or planned_answer),
                "rows": rows[:100],
                "columns": columns,
                "sql": "",
                "export_id": export_id,
                "row_count": len(rows),
                "shown_count": min(len(rows), 100),
                "assigned": assigned,
                "chart": chart,
            }
        sql = validate_sql(str(fallback.get("sql") or ""), assigned)
        planned_answer = fallback.get("answer") or planned_answer
        output_style = str(fallback.get("output_style") or output_style or "").strip().lower()

    if not sql:
        return {
            "answer": planned_answer or "I can answer once I can build a safe query from the assigned tables.",
            "rows": [],
            "columns": [],
            "sql": "",
            "export_id": None,
            "row_count": 0,
            "shown_count": 0,
            "assigned": assigned,
            "chart": None,
        }

    try:
        columns, rows = run_query(sql)
    except Exception:
        if not ai_plan:
            raise
        fallback = build_local_plan(message, assigned, history=history)
        if fallback.get("local_rows") is not None:
            rows = fallback.get("local_rows") or []
            columns = fallback.get("columns") or (list(rows[0].keys()) if rows else [])
            export_id = save_excel_export(fallback.get("title") or "Data Chatbot Result", rows)
            chart = build_chart_config(effective_message, rows, columns, fallback.get("output_style") or output_style)
            return {
                "answer": build_natural_fallback_answer(message, rows, columns, fallback.get("answer")),
                "rows": rows[:100],
                "columns": columns,
                "sql": "",
                "export_id": export_id,
                "row_count": len(rows),
                "shown_count": min(len(rows), 100),
                "assigned": assigned,
                "chart": chart,
            }
        sql = validate_sql(str(fallback.get("sql") or ""), assigned)
        planned_answer = fallback.get("answer") or planned_answer
        output_style = str(fallback.get("output_style") or output_style or "").strip().lower()
        columns, rows = run_query(sql)
    export_id = save_excel_export(plan.get("title") or "Data Chatbot Result", rows)
    chart = build_chart_config(effective_message, rows, columns, output_style)
    return {
        "answer": polish_answer_with_ai(message, rows, columns, planned_answer),
        "rows": rows[:100],
        "columns": columns,
        "sql": sql,
        "export_id": export_id,
        "row_count": len(rows),
        "shown_count": min(len(rows), 100),
        "assigned": assigned,
        "chart": chart,
    }


def export_path(export_id):
    if not re.match(r"^[a-f0-9]{32}$", str(export_id or "")):
        return None
    path = EXPORT_DIR / f"{export_id}.xlsx"
    return path if path.exists() else None
