"""Email source — IMAP inbox monitoring for DDLs."""

import email
import imaplib
import os
from datetime import datetime, timezone
from email.header import decode_header


def _decode_header_value(value) -> str:
    """Decode email header encoded words (RFC 2047)."""
    if value is None:
        return ""
    parts = decode_header(value)
    result = []
    for part, charset in parts:
        if isinstance(part, bytes):
            result.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(str(part))
    return "".join(result)


def _get_body(msg) -> str:
    """Extract plain text body from email message."""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            return payload.decode(charset, errors="replace")
    return ""


def fetch_recent_emails(hours: int = 24) -> list[dict]:
    """Fetch recent unread emails via IMAP. Returns list of {text, source_group, source_url}."""

    host = os.environ.get("EMAIL_HOST", "")
    port = int(os.environ.get("EMAIL_PORT", "993"))
    user = os.environ.get("EMAIL_USER", "")
    password = os.environ.get("EMAIL_PASSWORD", "")

    if not host or not user or not password:
        print("[EMAIL] Not configured, skipping.")
        return []

    results = []
    try:
        mail = imaplib.IMAP4_SSL(host, port)
        mail.login(user, password)
        mail.select("INBOX")

        # Search for emails from last N hours
        since = datetime.now(timezone.utc)
        # IMAP search doesn't support hours, so we search recent + filter
        status, data = mail.search(None, "UNSEEN")
        if status != "OK":
            mail.logout()
            return []

        msg_ids = data[0].split()
        if not msg_ids:
            print("[EMAIL] No new unread emails.")
            mail.logout()
            return []

        # Process last 20 unread emails
        for mid in msg_ids[-20:]:
            status, msg_data = mail.fetch(mid, "(RFC822)")
            if status != "OK":
                continue

            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)

            subject = _decode_header_value(msg["Subject"])
            sender = _decode_header_value(msg["From"])
            body = _get_body(msg)

            # Combine subject + body for LLM
            text = f"邮件主题：{subject}\n发件人：{sender}\n\n{body[:2000]}"  # truncate long emails
            if len(body) > 2000:
                text += "\n\n[邮件内容过长，已截断]"

            results.append({
                "text": text,
                "source": "email",
                "source_group": sender,
                "source_url": "",
                "raw_text": f"Subject: {subject}",
            })

        mail.logout()
        print(f"[EMAIL] Fetched {len(results)} unread email(s).")
    except Exception as e:
        print(f"[EMAIL] Error: {e}")

    return results
