"""dontmissddl — Main entry point. Runs in GitHub Actions, not a long-lived server.

This script does two things (controlled by --mode):
  poll    — Fetch recent content from Feishu/Email/RSS, extract DDLs via LLM
  remind  — Check upcoming DDLs, send Feishu reminders
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Fix Unicode on Windows GBK terminal
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

# Project root
ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env", encoding="utf-8")  # load .env before reading os.environ
DATA_DIR = ROOT / "data"
DDLS_FILE = DATA_DIR / "ddls.json"
STATE_FILE = DATA_DIR / "state.json"


# ═══════════════════════════════════════════════════
# JSON-backed storage (no SQLite → git-friendly)
# ═══════════════════════════════════════════════════

def _load_json(path: Path) -> dict | list:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {} if path.suffix == "" else []


def _save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_ddls() -> list[dict]:
    return _load_json(DDLS_FILE) if isinstance(_load_json(DDLS_FILE), list) else []


def save_ddls(items: list[dict]):
    _save_json(DDLS_FILE, items)


def load_state() -> dict:
    s = _load_json(STATE_FILE)
    if not isinstance(s, dict):
        return {}
    s.setdefault("last_message_ids", {})
    s.setdefault("processed_ids", [])
    s.setdefault("last_email_uid", "0")
    s.setdefault("seen_sogou_links", [])
    return s


def save_state(state: dict):
    # Keep processed_ids bounded
    if len(state.get("processed_ids", [])) > 5000:
        state["processed_ids"] = state["processed_ids"][-2000:]
    _save_json(STATE_FILE, state)


# ═══════════════════════════════════════════════════
# Poll: fetch messages → extract DDLs
# ═══════════════════════════════════════════════════

def _process_texts(texts: list[dict], state: dict, ddls: list[dict]) -> int:
    """Run LLM extraction on a batch of texts from any source.
    Returns number of new DDLs saved.
    """
    from server.extract import extract_ddl

    old_ids = set(state.get("processed_ids", []))
    new_count = 0

    for item in texts:
        text = item["text"]
        if not text:
            continue

        # Simple content hash for dedup
        text_id = item.get("msg_id") or str(hash(text))
        if text_id in old_ids:
            continue

        print(f"  [{item['source']}] {text[:60]}...")

        try:
            ddl_list = extract_ddl(text)
        except Exception as e:
            print(f"    [skip] LLM error: {e}")
            state["processed_ids"].append(text_id)
            continue

        if not ddl_list:
            state["processed_ids"].append(text_id)
            continue

        for ddl in ddl_list:
            if not ddl.get("title") or not ddl.get("deadline"):
                continue
            dup = any(
                d.get("title") == ddl["title"] and d.get("deadline") == ddl["deadline"]
                for d in ddls
            )
            if dup:
                continue

            ddls.append({
                "title": ddl["title"],
                "deadline": ddl["deadline"],
                "description": ddl.get("description", ""),
                "source": item.get("source", "unknown"),
                "source_group": item.get("source_group", ""),
                "source_url": item.get("source_url", ""),
                "raw_text": text,
                "notified_dates": [],
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            print(f"    [+] {ddl['title']} -> {ddl['deadline']}")
            new_count += 1

        state["processed_ids"].append(text_id)

    return new_count


def run_poll():
    from server.sources.feishu_bot import FeishuBot
    from server.sources.email_source import fetch_recent_emails
    from server.sources.wechat_rss import fetch_wechat_articles

    state = load_state()
    ddls = load_ddls()
    total_new = 0

    # ── Source 1: Feishu ──
    bot = FeishuBot()
    group_ids_str = os.environ.get("FEISHU_GROUP_IDS", "")
    if group_ids_str:
        group_ids = [g.strip() for g in group_ids_str.split(",") if g.strip()]
        old_ids = set(state.get("processed_ids", []))

        for chat_id in group_ids:
            last_id = state["last_message_ids"].get(chat_id, "")
            print(f"\n[Feishu] chat={chat_id[:12]}... last_id={last_id[:16] if last_id else 'none'}")

            # list_messages now paginates automatically, stopping when it sees last_id
            messages = bot.list_messages(chat_id, stop_at_id=last_id or None)
            if not messages:
                print("  → no new messages")
                continue

            # Build input list for _process_texts
            fresh = []
            for msg in messages:
                mid = msg.get("message_id", "")
                if mid in old_ids:
                    continue
                # Parse content
                body = msg.get("body", {}).get("content", "{}")
                try:
                    content = json.loads(body)
                    text = content.get("text", "").strip()
                except (json.JSONDecodeError, AttributeError):
                    text = ""
                if text:
                    fresh.append({
                        "text": text,
                        "msg_id": mid,
                        "source": "feishu",
                        "source_group": chat_id,
                        "source_url": "",
                    })

            if not fresh:
                print(f"  → {len(messages)} messages, 0 new")
                continue

            print(f"  → {len(fresh)} new messages")
            fresh.reverse()  # process oldest first

            total_new += _process_texts(fresh, state, ddls)

            # Update last_id
            state["last_message_ids"][chat_id] = messages[0].get("message_id", "")
    else:
        print("[Feishu] Not configured, skipping.")

    # ── Source 2: Email ──
    print("\n[Source] Email (IMAP)...")
    last_email_uid = int(state.get("last_email_uid", 0))
    emails, max_uid = fetch_recent_emails(since_uid=last_email_uid)
    if emails:
        total_new += _process_texts(emails, state, ddls)
        state["last_email_uid"] = str(max_uid)

    # ── Source 3: WeChat RSS ──
    print("\n[Source] WeChat RSS...")
    articles = fetch_wechat_articles()
    if articles:
        total_new += _process_texts(articles, state, ddls)

    # ── Source 4: Sogou WeChat Search ──
    from server.sources.wechat_sogou import fetch_sogou_articles

    print("\n[Source] Sogou WeChat...")
    seen_links = set(state.get("seen_sogou_links", [])[-500:])  # keep last 500
    sogou_articles, new_sogou_links = fetch_sogou_articles(skip_links=seen_links)
    if sogou_articles:
        total_new += _process_texts(sogou_articles, state, ddls)
        if new_sogou_links:
            all_links = set(state.get("seen_sogou_links", []))
            all_links.update(new_sogou_links)
            state["seen_sogou_links"] = list(all_links)[-500:]

    if total_new > 0:
        save_ddls(ddls)

    # ── Sync to Bitable ──
    wiki_token = os.environ.get("FEISHU_WIKI_TOKEN", "")
    table_id = os.environ.get("FEISHU_TABLE_ID", "")
    if wiki_token and table_id:
        from server.sources.feishu_bitable import FeishuBitable, build_ddl_fields

        print("\n[Bitable] Syncing to multidimensional table...")
        bt = FeishuBitable()
        app_token = bt.resolve_bitable_token(wiki_token)
        if app_token:
            existing = bt.list_records(app_token, table_id)
            # Build a set of (title, deadline) already in the table
            seen_in_table: set[tuple[str, str]] = set()
            for rec in existing:
                f = rec.get("fields", {})
                t = f.get("标题", "")
                d = ""
                dl_ts = f.get("截止日期")
                if dl_ts:
                    from datetime import datetime as _dt, timezone as _tz
                    try:
                        d = _dt.fromtimestamp(dl_ts / 1000, tz=_tz.utc).isoformat()
                    except Exception:
                        pass
                seen_in_table.add((t, d))

            # Collect new DDLs not yet in the table (skip past deadlines)
            new_fields = []
            for ddl in ddls:
                key = (ddl.get("title", ""), ddl.get("deadline", ""))
                if key in seen_in_table:
                    continue
                fields = build_ddl_fields(ddl)
                if fields is None:
                    continue  # past deadline
                new_fields.append(fields)
                seen_in_table.add(key)

            if new_fields:
                n = bt.add_records(app_token, table_id, new_fields)
                print(f"[Bitable] {n} new record(s) written, {len(new_fields) - n} failed.")
            else:
                print("[Bitable] All DDLs already in table, nothing to add.")
        else:
            print("[Bitable] Could not resolve wiki token to Bitable app_token.")

    save_state(state)
    print(f"\nDone: {total_new} new DDL(s) saved, {len(ddls)} total")


# ═══════════════════════════════════════════════════
# Remind: check upcoming DDLs → send notifications
# ═══════════════════════════════════════════════════

def run_remind():
    from server.sources.feishu_bot import FeishuBot

    bot = FeishuBot()
    ddls = load_ddls()
    now = datetime.now(timezone.utc)

    days_str = os.environ.get("REMINDER_DAYS", "7,3,1")
    days_list = [int(d.strip()) for d in days_str.split(",") if d.strip()]

    my_open_id = os.environ.get("FEISHU_MY_OPEN_ID", "")

    sent = 0
    modified = False

    for item in ddls:
        try:
            deadline_dt = datetime.fromisoformat(item["deadline"])
            # Make offset-naive datetimes UTC-aware
            if deadline_dt.tzinfo is None:
                deadline_dt = deadline_dt.replace(tzinfo=timezone.utc)
        except (ValueError, KeyError):
            continue

        days_left = (deadline_dt - now).days

        # Skip past deadlines
        if days_left < 0:
            continue

        for days_before in days_list:
            if days_left != days_before:
                continue

            notified = item.get("notified_dates", [])
            if isinstance(notified, str):
                notified = json.loads(notified) if notified else []
            if days_before in notified:
                continue

            deadline_short = deadline_dt.strftime("%m月%d日 %H:%M")
            source_info = ""
            if item.get("source") == "email":
                source_info = f"\n[Email] {item.get('source_group', '')}"
            elif item.get("source") == "wechat_rss":
                source_info = f"\n[RSS] {item.get('source_group', '')}"

            text = (
                f"[DDL Reminder] {item['title']}\n"
                f"Deadline: {deadline_short}\n"
                f"{days_before} day(s) left"
                f"{source_info}"
            )

            sent_ok = False
            # Prefer DM to user, fall back to source group
            if my_open_id:
                sent_ok = bot.send_dm(my_open_id, text)
                dest = f"DM({my_open_id[:12]}...)"
            else:
                chat_id = item.get("source_group", "")
                if chat_id:
                    sent_ok = bot.send_text(chat_id, text)
                    dest = f"group({chat_id[:12]}...)"

            if sent_ok:
                notified.append(days_before)
                item["notified_dates"] = notified
                sent += 1
                modified = True
                print(f"[REMIND] {item['title']} ({days_before}d) → {dest}")
            break  # only notify once per run per item

    if modified:
        save_ddls(ddls)
    print(f"Remind done: {sent} notification(s) sent")


# ═══════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════

def run_lookup_id():
    """Look up your Feishu open_id by email or mobile."""
    from server.sources.feishu_bot import FeishuBot

    email = os.environ.get("EMAIL_USER", "")
    mobile = os.environ.get("FEISHU_MY_MOBILE", "")

    bot = FeishuBot()

    if mobile:
        print(f"Looking up by mobile: {mobile}")
        open_id = bot.lookup_open_id(mobile=mobile)
    elif email:
        print(f"Looking up by email: {email}")
        open_id = bot.lookup_open_id(email=email)
    else:
        print("Set EMAIL_USER or FEISHU_MY_MOBILE in .env first, then run again.")
        return
    if open_id:
        print(f"\n[OK] Your open_id: {open_id}")
        print(f"   Copy this to .env -> FEISHU_MY_OPEN_ID={open_id}")
    else:
        print("\n[FAIL] Lookup failed. Either:")
        print("   1. The app doesn't have 'contact:user.id:readonly' permission - add it in Feishu console")
        print("   2. The email doesn't match a Feishu user in your tenant")
        print(f"\n   You can also find your open_id manually:")
        print("   Feishu Admin Console -> Members -> click yourself -> copy Open ID")


def run_find_chat():
    """List all chats the bot is in, to find the right chat_id."""
    from server.sources.feishu_bot import FeishuBot

    bot = FeishuBot()
    chats = bot.list_chats()
    if not chats:
        print("No chats found. Is the bot in any conversations?")
        return
    print(f"\n=== {len(chats)} chat(s) found ===\n")
    for c in chats:
        chat_id = c.get("chat_id", "")
        name = c.get("name", "(no name / DM)")
        chat_type = c.get("chat_type", "?")
        print(f"  [{chat_type}] {name}")
        print(f"    chat_id: {chat_id}")
        print()


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "poll"
    if mode == "poll":
        run_poll()
    elif mode == "remind":
        run_remind()
    elif mode == "all":
        run_poll()
        run_remind()
    elif mode == "lookup-id":
        run_lookup_id()
    elif mode == "find-chat":
        run_find_chat()
    else:
        print(f"Usage: python -m server.main [poll|remind|all|lookup-id|find-chat]")
        sys.exit(1)


if __name__ == "__main__":
    main()
