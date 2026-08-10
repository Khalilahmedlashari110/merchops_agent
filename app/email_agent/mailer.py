import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import parseaddr


def send_html_email(
    smtp_server,
    smtp_port,
    sender_email,
    sender_password,
    recipient_email,
    subject,
    html_body
):
    _, clean_recipient = parseaddr(str(recipient_email or "").strip())
    if not clean_recipient:
        raise ValueError(f"Invalid recipient email: {recipient_email}")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender_email
    msg["To"] = clean_recipient

    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(str(smtp_server).strip(), int(smtp_port)) as server:
        server.starttls()
        server.login(str(sender_email).strip(), str(sender_password).strip())
        server.sendmail(str(sender_email).strip(), [clean_recipient], msg.as_string())

    return True