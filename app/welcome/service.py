import os
import json
import base64
from io import BytesIO

from app.database.connection_manager import get_master_connection

_client = None


def _get_client():
    import anthropic
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


def ensure_visitors_table():
    try:
        conn = get_master_connection()
        cursor = conn.cursor()
        cursor.execute("""
            IF NOT EXISTS (
                SELECT * FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_CATALOG = 'khPriority'
                  AND TABLE_NAME    = 'WelcomeVisitors'
            )
            CREATE TABLE khPriority.dbo.WelcomeVisitors (
                id            INT IDENTITY(1,1) PRIMARY KEY,
                name          NVARCHAR(100)  NOT NULL,
                face_encoding NVARCHAR(MAX)  NULL,
                visit_count   INT            DEFAULT 1,
                first_visit   DATETIME       DEFAULT GETDATE(),
                last_visit    DATETIME       DEFAULT GETDATE()
            )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[WELCOME] Table setup error: {e}")


def get_all_visitors():
    conn = get_master_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, visit_count, first_visit, last_visit
        FROM khPriority.dbo.WelcomeVisitors
        ORDER BY last_visit DESC
    """)
    cols = [c[0] for c in cursor.description]
    rows = cursor.fetchall()
    conn.close()
    result = []
    for row in rows:
        r = dict(zip(cols, row))
        for k in ("first_visit", "last_visit"):
            if r.get(k) and hasattr(r[k], "strftime"):
                r[k] = r[k].strftime("%Y-%m-%d %H:%M")
        result.append(r)
    return result


def _decode_image(image_b64: str):
    from PIL import Image
    import numpy as np
    raw = base64.b64decode(image_b64.split(",")[-1])
    img = Image.open(BytesIO(raw)).convert("RGB")
    return np.array(img)


def recognize_face(image_b64: str):
    """
    Compare the captured webcam frame against all stored encodings.
    Returns (visitor_id, visitor_name) or (None, None).
    """
    try:
        import face_recognition
        import numpy as np
        img_np = _decode_image(image_b64)
        locations = face_recognition.face_locations(img_np)
        if not locations:
            return None, None

        unknown_enc = face_recognition.face_encodings(img_np, locations)[0]

        conn = get_master_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, name, face_encoding FROM khPriority.dbo.WelcomeVisitors "
            "WHERE face_encoding IS NOT NULL"
        )
        rows = cursor.fetchall()
        conn.close()

        for visitor_id, name, enc_json in rows:
            if not enc_json:
                continue
            stored = np.array(json.loads(enc_json))
            if face_recognition.compare_faces([stored], unknown_enc, tolerance=0.50)[0]:
                _increment_visit(visitor_id)
                return visitor_id, name

        return None, None
    except Exception as e:
        print(f"[WELCOME] recognize_face error: {e}")
        return None, None


def _increment_visit(visitor_id: int):
    conn = get_master_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE khPriority.dbo.WelcomeVisitors "
        "SET visit_count = visit_count + 1, last_visit = GETDATE() "
        "WHERE id = ?",
        visitor_id,
    )
    conn.commit()
    conn.close()


def save_visitor(name: str, image_b64: str = None):
    """
    Persist a new visitor with an optional face encoding.
    Returns the new visitor_id.
    """
    enc_json = None
    if image_b64:
        try:
            import face_recognition
            img_np = _decode_image(image_b64)
            locations = face_recognition.face_locations(img_np)
            if locations:
                enc = face_recognition.face_encodings(img_np, locations)[0]
                enc_json = json.dumps(enc.tolist())
        except Exception as e:
            print(f"[WELCOME] save_visitor encoding error: {e}")

    conn = get_master_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO khPriority.dbo.WelcomeVisitors (name, face_encoding, visit_count) "
        "VALUES (?, ?, 1)",
        (name, enc_json),
    )
    conn.commit()
    cursor.execute("SELECT @@IDENTITY")
    row = cursor.fetchone()
    conn.close()
    return int(row[0]) if row else None


def chat_with_aria(user_message: str, visitor_name: str = None, history: list = None):
    """
    Single-turn Claude Haiku call for ARIA welcome-page conversation.
    history: [{"role": "user"|"assistant", "content": "..."}]
    """
    history = (history or [])[-10:]  # cap at last 10 turns

    name_ctx = (
        f"The visitor's name is {visitor_name}."
        if visitor_name
        else "The visitor has not yet introduced themselves."
    )

    system_prompt = f"""You are SmartOps Agent, the AI assistant for MerchOps Agent, an AI-powered inventory and email automation platform.
You greet visitors on the welcome screen before they log in.

{name_ctx}

Personality: warm, natural, professional, and helpful. Sound like a capable front-desk assistant, not a command terminal. Never more than 2-3 short sentences per reply.

Priorities:
1. If you don't know the visitor's name, warmly ask for their introduction first.
2. Once you know their name, greet them personally and give a one-sentence description of MerchOps.
3. Answer brief questions about the system concisely.
4. Encourage them to click "Enter System" to log in when they are ready.

MerchOps Agent is an AI-driven platform that automatically reads inventory-related emails, queries the SQL Server database, and drafts professional HTML replies using Claude, all with human review before sending.

Never invent features or data. Stay concise."""

    messages = list(history) + [{"role": "user", "content": user_message}]

    response = _get_client().messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        system=system_prompt,
        messages=messages,
    )
    return response.content[0].text.strip()
