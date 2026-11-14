"""Email notifications via SMTP env vars. Without SMTP_HOST (or with EMAIL_DRY_RUN=1) every email is
written to data/outbox.jsonl and printed to the log instead of being sent ("mocked")."""
import datetime as dt, json, os, smtplib, ssl, threading
from email.message import EmailMessage

from store import DATA

_lock = threading.Lock()


def _outbox(rec):
    os.makedirs(DATA, exist_ok=True)
    with _lock, open(os.path.join(DATA, "outbox.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def send_email(to, subject, body, reply_to=None):
    """Returns 'sent', 'logged' (no SMTP configured / dry run) or 'failed: ...'."""
    to = [t for t in ([to] if isinstance(to, str) else to) if t]
    rec = {"at": dt.datetime.now().isoformat(timespec="seconds"), "to": to, "subject": subject, "body": body}
    host = os.getenv("SMTP_HOST")
    if not to:
        rec["status"] = "logged (no recipient)"; _outbox(rec); return "logged"
    if not host or os.getenv("EMAIL_DRY_RUN", "").lower() in ("1", "true", "yes"):
        rec["status"] = "logged (SMTP not configured)"; _outbox(rec)
        print(f"[email mock] to={to} subject={subject!r}")
        return "logged"
    port = int(os.getenv("SMTP_PORT", "465"))
    sec = os.getenv("SMTP_SECURITY", "ssl" if port == 465 else "starttls").lower()
    user, pw = os.getenv("SMTP_USER"), os.getenv("SMTP_PASS")
    m = EmailMessage()
    m["Subject"], m["From"], m["To"] = subject, os.getenv("SMTP_FROM") or user or "bookbot@localhost", ", ".join(to)
    if reply_to:
        m["Reply-To"] = reply_to
    m.set_content(body)
    try:
        if sec == "ssl":
            c = smtplib.SMTP_SSL(host, port, timeout=15, context=ssl.create_default_context())
        else:
            c = smtplib.SMTP(host, port, timeout=15)
            if sec == "starttls":
                c.starttls(context=ssl.create_default_context())
        with c:
            if user and pw:
                c.login(user, pw)
            c.send_message(m)
        rec["status"] = "sent"; _outbox(rec)
        return "sent"
    except Exception as e:
        rec["status"] = f"failed: {e}"; _outbox(rec)
        print(f"[email error] {e}")
        return f"failed: {str(e)[:120]}"
