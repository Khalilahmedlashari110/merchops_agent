import imaplib
import email
from email.header import decode_header
from email.utils import parseaddr


def decode_mime_text(value):
    if not value:
        return ""
    parts = decode_header(value)
    decoded = []
    for text, enc in parts:
        if isinstance(text, bytes):
            decoded.append(text.decode(enc or "utf-8", errors="ignore"))
        else:
            decoded.append(text)
    return "".join(decoded)


def extract_email_body(msg):
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition") or "")
            if content_type == "text/plain" and "attachment" not in disposition.lower():
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(errors="ignore")
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition") or "")
            if content_type == "text/html" and "attachment" not in disposition.lower():
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(errors="ignore")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            return payload.decode(errors="ignore")

    return ""


def read_email_inbox(email_user, email_pass, provider, imap_server, imap_port, limit=20):
    mail = imaplib.IMAP4_SSL(imap_server, int(imap_port))
    mail.login(email_user, email_pass)
    mail.select("inbox")

    status, messages = mail.search(None, "UNSEEN")
    if status != "OK":
        mail.logout()
        return []

    mail_ids = messages[0].split()
    mail_ids = mail_ids[-limit:]

    emails = []

    for mail_id in reversed(mail_ids):
        status, msg_data = mail.fetch(mail_id, "(RFC822)")
        if status != "OK":
            continue

        for response_part in msg_data:
            if isinstance(response_part, tuple):
                msg = email.message_from_bytes(response_part[1])

                subject = decode_mime_text(msg.get("Subject"))
                from_raw = decode_mime_text(msg.get("From"))
                to_raw = decode_mime_text(msg.get("To"))
                date_ = decode_mime_text(msg.get("Date"))
                body = extract_email_body(msg)
                message_id = decode_mime_text(msg.get("Message-ID"))

                from_name, from_email = parseaddr(from_raw)
                to_name, to_email = parseaddr(to_raw)

                emails.append({
                    "mail_id": mail_id.decode() if isinstance(mail_id, bytes) else str(mail_id),
                    "message_id": message_id,
                    "subject": subject,
                    "from": from_raw,
                    "from_name": from_name,
                    "from_email": from_email,
                    "to": to_raw,
                    "to_email": to_email,
                    "date": date_,
                    "body": body,
                })

    mail.logout()
    return emails