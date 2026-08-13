"""Email source — IMAP inbox monitoring for DDLs."""

import email
import imaplib
import os
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


def fetch_recent_emails(since_uid: int = 0) -> tuple[list[dict], int]:
    """Fetch unread emails since a given IMAP UID (exclusive).

    Does NOT mark emails as read — your inbox stays untouched.
    Instead, tracks the highest UID seen so the next call only fetches newer mail.

    Args:
        since_uid: only fetch emails with UID > this value. 0 = fetch all unread.

    Returns:
        results: list of {text, source_group, source_url, msg_id} dicts
        max_uid: the highest UID fetched this run (pass as since_uid next time)
    """

    host = os.environ.get("EMAIL_HOST", "")
    port = int(os.environ.get("EMAIL_PORT", "993"))
    user = os.environ.get("EMAIL_USER", "")
    password = os.environ.get("EMAIL_PASSWORD", "")

    if not host or not user or not password:
        print("[EMAIL] Not configured, skipping.")
        return [], since_uid

    results: list[dict] = []
    max_uid = since_uid
    try:
        mail = imaplib.IMAP4_SSL(host, port)
        mail.login(user, password)
        mail.select("INBOX")

        # Fetch all UNSEEN messages, then filter by UID
        status, data = mail.uid("SEARCH", None, "UNSEEN")
        if status != "OK":
            mail.logout()
            return [], since_uid

        all_uids = data[0].split()
        if not all_uids:
            print("[EMAIL] No unread emails.")
            mail.logout()
            return [], since_uid

        # Filter to only new UIDs since last run (don't re-fetch already processed)
        new_uids = [u for u in all_uids if int(u) > since_uid]
        print(f"[EMAIL] {len(new_uids)} new unread (out of {len(all_uids)} total unread).")

        for uid_bytes in new_uids:
            uid = int(uid_bytes)
            status, msg_data = mail.uid("FETCH", uid_bytes, "(RFC822)")
            if status != "OK":
                continue

            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)

            subject = _decode_header_value(msg["Subject"])
            sender = _decode_header_value(msg["From"])
            body = _get_body(msg)

            # Combine subject + body for LLM
            text = f"邮件主题：{subject}\n发件人：{sender}\n\n{body[:2000]}"
            if len(body) > 2000:
                text += "\n\n[邮件内容过长，已截断]"

            uid_str = str(uid)
            results.append({
                "text": text,
                "source": "email",
                "source_group": sender,
                "source_url": "",
                "raw_text": f"Subject: {subject}",
                "msg_id": uid_str,
            })
            if uid > max_uid:
                max_uid = uid

        mail.logout()
        print(f"[EMAIL] Fetched {len(results)} email(s), max_uid={max_uid}.")
    except Exception as e:
        print(f"[EMAIL] Error: {e}")
        return results, max_uid

    return results, max_uid
