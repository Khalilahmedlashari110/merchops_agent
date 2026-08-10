from app.email_agent.reader import read_email_inbox
from app.email_agent.parser import parse_email_request
from app.email_agent.ai_logic import generate_agentic_reply, generate_unregistered_sender_reply
from app.email_agent.db_service import (
    get_active_email_accounts,
    save_incoming_email_log,
    save_email_draft,
    is_email_already_drafted,
)
from app.email_agent.sender_service import (
    is_sender_approved,
    get_sender_by_email,
    add_or_update_unregistered_sender,
)
from app.inventory.service import get_presentation_rows_from_db, get_rows_from_named_table


def normalize_value(v):
    return str(v or "").strip().lower()


def _load_rows_for_sender(assigned_tables):
    """Fetch and tag rows from all tables assigned to a sender.

    Falls back to the default presentation batch when no tables are assigned.
    Each row gets a _source_table key so the LLM knows its origin.
    """
    if not assigned_tables:
        rows = get_presentation_rows_from_db()
        for r in rows:
            r["_source_table"] = "InventoryPresentationData"
        return rows

    combined = []
    for table_name in assigned_tables:
        try:
            table_rows = get_rows_from_named_table(table_name)
            for r in table_rows:
                r["_source_table"] = table_name
            combined.extend(table_rows)
        except Exception as exc:
            print(f"[DATA] Could not query table '{table_name}': {exc}")
    return combined


def get_matching_inventory_rows(parsed_request, assigned_tables=None):
    rows = _load_rows_for_sender(assigned_tables)

    if not rows:
        return []

    key_terms = [t.lower() for t in parsed_request.get("key_terms", [])]
    if not key_terms:
        return rows[:40]

    matched = []
    for r in rows:
        row_text = " ".join(
            str(v).lower()
            for k, v in r.items()
            if not k.startswith("_") and v is not None and str(v).strip()
        )
        score = sum(1 for term in key_terms if term in row_text)
        if score > 0:
            item = dict(r)
            item["_match_score"] = score
            matched.append(item)

    if matched:
        matched.sort(key=lambda x: x["_match_score"], reverse=True)
        return matched[:40]

    return rows[:40]


def process_email_account(account):
    emails = read_email_inbox(
        email_user=account["email_address"],
        email_pass=account["email_password"],
        provider=account.get("provider", "custom"),
        imap_server=account["imap_server"],
        imap_port=account["imap_port"],
        limit=10,
    )

    processed = []

    for e in emails:
        parsed = parse_email_request(e["subject"], e["body"])
        sender_email = e.get("from_email")
        sender_name = e.get("from_name")
        approved = is_sender_approved(account["org_id"], sender_email)

        matched_rows = []
        draft_reply = ""
        auto_draft_enabled = False
        draft_id = None

        # Only generate drafts/logs for new inventory-request emails
        if parsed.get("is_inventory_request") and not is_email_already_drafted(e.get("message_id")):
            if approved:
                sender_record = get_sender_by_email(account["org_id"], sender_email)
                assigned_tables = sender_record.get("tables", []) if sender_record else []
                matched_rows = get_matching_inventory_rows(parsed, assigned_tables=assigned_tables)
                draft_reply = generate_agentic_reply(
                    subject=e["subject"],
                    body=e["body"],
                    parsed_request=parsed,
                    inventory_rows=matched_rows,
                    organization_name=account.get("organization_name", ""),
                    account_name=account.get("account_name", "")
                )
                auto_draft_enabled = True
            else:
                add_or_update_unregistered_sender(
                    org_id=account["org_id"],
                    email_account_id=account["id"],
                    sender_email=sender_email,
                    sender_name=sender_name,
                    subject_line=e.get("subject"),
                    body_text=e.get("body"),
                )
                draft_reply = generate_unregistered_sender_reply(
                    account_name=account.get("account_name", "SmartOps Agents")
                )
                auto_draft_enabled = True

            log_id = save_incoming_email_log(
                org_id=account["org_id"],
                user_id=account.get("user_id"),
                email_account_id=account["id"],
                external_message_id=e.get("message_id"),
                sender_email=sender_email,
                subject_line=e.get("subject"),
                body_text=e.get("body"),
                detected_intent="data_request" if parsed.get("is_data_request") else "general",
                matched_skus=",".join(parsed.get("key_terms", [])[:5]),
                auto_reply_generated=bool(draft_reply),
                reply_subject=f"Re: {e.get('subject')}" if draft_reply else None,
                reply_body=draft_reply if draft_reply else None,
            )

            if draft_reply:
                draft_id = save_email_draft(
                    log_id=log_id,
                    org_id=account["org_id"],
                    user_id=account.get("user_id"),
                    email_account_id=account["id"],
                    recipient_email=sender_email,
                    subject_line=f"Re: {e.get('subject')}",
                    reply_body=draft_reply
                )

        # All emails (not just inventory requests) go to the inbox
        processed.append({
            **e,
            "approved_sender": approved,
            "parsed": parsed,
            "matched_rows": matched_rows,
            "draft_reply": draft_reply,
            "auto_draft_enabled": auto_draft_enabled,
            "draft_id": draft_id,
        })

    return processed


def process_all_active_accounts():
    accounts = get_active_email_accounts()
    results = []

    for account in accounts:
        results.append({
            "account": account,
            "emails": process_email_account(account)
        })

    return results