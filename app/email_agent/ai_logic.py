import os
import re
import anthropic

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    return _client


def _ensure_table_closed(html):
    """Close any unclosed <table> only if one is actually open.

    Blindly appending </td></tr></tbody></table> when the table is already
    closed confuses browsers into pulling subsequent <p> tags inside a phantom
    table row.  Count open vs close tags and only add what is missing.
    """
    open_count  = len(re.findall(r'<table[\s>]', html, re.IGNORECASE))
    close_count = len(re.findall(r'</table\s*>',  html, re.IGNORECASE))
    gap = open_count - close_count
    if gap > 0:
        html = html.rstrip() + ('</td></tr></tbody></table>' * gap)
    return html


def _format_inventory_rows_for_prompt(rows):
    if not rows:
        return "No matching data rows found."

    # Group by source table so the LLM sees clear data boundaries
    by_table = {}
    for r in rows[:150]:
        src = r.get("_source_table", "unknown")
        by_table.setdefault(src, []).append(r)

    sections = []
    for table_name, table_rows in by_table.items():
        lines = [f"[Source: {table_name}]"]
        for r in table_rows:
            # Emit every non-private, non-None field dynamically
            fields = " | ".join(
                f"{k}={v}"
                for k, v in r.items()
                if not k.startswith("_") and v is not None and str(v).strip() != ""
            )
            lines.append(fields)
        sections.append("\n".join(lines))

    return "\n\n".join(sections)



_TABLE_STYLE = (
    "width:100%;border-collapse:collapse;margin-top:16px;"
    "font-family:Arial,sans-serif;font-size:13px;"
)
_TH_STYLE = "border:1px solid #cfd8df;padding:8px;text-align:left;background:#eef4f8;"
_TD_STYLE = "border:1px solid #d9e2e8;padding:7px;"
_TD_RIGHT = "border:1px solid #d9e2e8;padding:7px;text-align:right;"


def _call_llm(original_subject, original_body, parsed_request, inventory_rows, organization_name, account_name):
    inventory_text = _format_inventory_rows_for_prompt(inventory_rows)
    item_count = len(inventory_rows)

    key_terms = parsed_request.get("key_terms", [])
    parsed_summary = (
        f"Key terms from email: {', '.join(key_terms) or 'none extracted'}\n"
        f"Urgent: {parsed_request.get('is_urgent', False)}\n"
        f"Matching data rows found: {item_count}"
    )

    system_prompt = f"""You are a professional email response agent for {organization_name or account_name or 'SmartOps Agents'}.

Your role is to read the incoming email, understand precisely what the sender needs, and write a concise, professional reply using only the provided data.

GREETING:
- Start with "Dear [Sender's first name]," if the name is identifiable from the email, otherwise "Dear Sir/Madam,"

CONTENT:
- One short sentence acknowledging the request, then answer directly with data.
- When a date range or trend is requested, include EVERY record in that range — do not sample or truncate.
- For time-series or multi-column data (e.g. monthly costs by size), always use a table — it is the clearest format.
- Flag missing values, anomalies, or gaps in the data with a brief note below the table.
- Close the body with exactly this sentence on its own paragraph: "Please let me know if you need anything further."
- Do NOT include a sign-off or "Best regards" — that is added separately.

HTML OUTPUT RULES (critical — follow exactly):
- Output an HTML fragment only: no <html>, <head>, or <body> tags.
- Use <p> for paragraphs.
- Every table MUST be fully closed: every <tr> closed with </tr>, every <tbody> closed with </tbody>, and </table> MUST appear before any following <p> tag.
- After writing </table>, do NOT add any more <tr>, <td>, or table-related tags — only <p> tags are allowed after </table>.
- Never leave a table open at the end of your output.
- Do NOT include "Best regards", a signature, or any sign-off — this is appended externally.

TABLE STYLE (use these exact inline styles):
- <table>: style="{_TABLE_STYLE}"
- <th>: style="{_TH_STYLE}"
- <td> (text/labels): style="{_TD_STYLE}"
- <td> (numbers): style="{_TD_RIGHT}"
- Missing/zero values: style="{_TD_RIGHT}color:#c0392b;font-weight:bold"
- Warning values: style="{_TD_RIGHT}color:#e67e22;font-weight:bold"

STRICT:
- Use only numbers from the provided data — never invent figures.
- Answer only what was asked."""

    user_prompt = f"""--- ORIGINAL EMAIL ---
Subject: {original_subject}
Body:
{original_body}

--- CONTEXT ---
{parsed_summary}

--- DATA ---
{inventory_text}

Write the HTML email reply now. Include all data rows that fall within the requested date range — output a complete table with no rows omitted. Close all HTML tags properly before finishing."""

    client = _get_client()

    with client.messages.stream(
        model="claude-opus-4-7",
        max_tokens=4000,
        thinking={"type": "adaptive"},
        system=[
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {"role": "user", "content": user_prompt},
        ],
    ) as stream:
        message = stream.get_final_message()

    for block in message.content:
        if block.type == "text":
            return block.text.strip()

    return ""


def generate_agentic_reply(subject, body, parsed_request, inventory_rows=None, organization_name="", account_name=""):
    inventory_rows = inventory_rows or []

    try:
        ai_body_html = _call_llm(
            original_subject=subject,
            original_body=body,
            parsed_request=parsed_request,
            inventory_rows=inventory_rows,
            organization_name=organization_name,
            account_name=account_name,
        )
    except Exception as e:
        print(f"[EMAIL AGENT] LLM call failed: {e}")
        ai_body_html = (
            "<p>Thank you for your enquiry. We have reviewed the inventory data for the items you mentioned "
            "and will follow up shortly with the details.</p>"
        )

    sign_off = account_name or organization_name or "SmartOps Agents"

    # Only close unclosed tables — appending these tags when the table is
    # already closed causes browsers to re-enter table mode and pull the
    # sign-off paragraph into a phantom row.
    safe_body = _ensure_table_closed(ai_body_html)

    html = f"""<html>
<body style="font-family:Arial,sans-serif;color:#1f2d3a;font-size:14px;line-height:1.6;max-width:860px;padding:24px 28px;">

{safe_body}

<div style="margin-top:32px;padding-top:18px;border-top:1px solid #e0e6eb;font-family:Arial,sans-serif;font-size:14px;color:#1f2d3a;">
    <p style="margin:0 0 4px 0;">Best regards,</p>
    <p style="margin:0;font-weight:600;">{sign_off}</p>
</div>

</body>
</html>"""

    return html.strip()


def generate_unregistered_sender_reply(account_name="SmartOps Agents"):
    return f"""<html>
<body style="font-family:Arial,sans-serif;color:#1f2d3a;font-size:14px;line-height:1.6;">
    <p>Hi,</p>

    <p>
        Thank you for reaching out. Unfortunately, your email address is not currently registered in our system,
        so we are unable to process your request automatically.
    </p>

    <p>
        Please contact the administrator to get registered, and we will be happy to assist you once your account is active.
    </p>

    <p style="margin-top:18px;">
        Best regards,<br>
        <strong>{account_name}</strong>
    </p>
</body>
</html>""".strip()
