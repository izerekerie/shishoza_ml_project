"""Optional citizen email notifications (free via Gmail SMTP + an app password).

Configured entirely by env vars so no secret lives in the repo. If SMTP_USER /
SMTP_PASS are unset, notifications are skipped silently and the citizen still
sees the outcome in the "My requests" panel — nothing breaks either way.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from .config import (EE_POOL, PUBLIC_URL, SMTP_FROM, SMTP_HOST, SMTP_PASS,
                     SMTP_PORT, SMTP_USER)


def _send_email(to, subject, body):
    if not (SMTP_USER and SMTP_PASS and to):
        print(f"[email] skipped (SMTP not configured or no recipient): '{subject}'", flush=True)
        return
    try:
        msg = EmailMessage()
        msg["Subject"], msg["From"], msg["To"] = subject, SMTP_FROM, to
        msg.set_content(body)
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as s:
            s.starttls(); s.login(SMTP_USER, SMTP_PASS); s.send_message(msg)
        print(f"[email] sent to {to}: {subject}", flush=True)
    except Exception as e:
        print(f"[email] failed to {to}: {e}", flush=True)


# Short alternative-to-cutting hints keyed by the citizen's stated reason, added
# to the "flagged" email so a refusal always comes with a constructive next step.
_ALT_HINTS = {
    "firewood": "- Fast-growing woodlots, or an improved (rocket) cookstove that needs far less wood.",
    "timber":   "- Harvest selectively, or plant a eucalyptus woodlot instead of clearing natural forest.",
    "farming":  "- Agroforestry: grow crops between retained trees so the land keeps its tree cover.",
    "income":   "- Beekeeping, fruit trees or eco-tourism can earn income without clearing the forest.",
}


def _alternatives_text(reason):
    return _ALT_HINTS.get((reason or "").lower(),
        "- Agroforestry, managed woodlots and improved cookstoves reduce the need to clear natural forest.")


def notify_decision(email, req_id, status, note, sector, reason=None):
    """Email the citizen the manager's decision, off the request thread."""
    if not email:
        return
    where = f" for {sector}" if sector else ""
    if status == "approved":
        subject = f"Shishoza - review #{req_id} approved"
        body = (f"Hello,\n\nYour technical-review request #{req_id}{where} has been APPROVED "
                "by the district forest manager.\n\n"
                "The tree-loss impact was assessed as acceptable. You may now proceed with the "
                "official cutting-permit application through your district land office. Keep this "
                f"review number (#{req_id}) as your reference."
                + (f"\n\nManager's note: {note}" if note else "")
                + f"\n\nTrack it any time in your account:\n{PUBLIC_URL}/my-reviews\n\n- Shishoza")
    else:  # rejected / flagged
        subject = f"Shishoza - review #{req_id} flagged"
        body = (f"Hello,\n\nYour technical-review request #{req_id}{where} has been FLAGGED "
                "by the district forest manager, so it is not recommended as submitted.\n\n"
                f"Reason: {note or 'significant tree-loss impact'}\n\n"
                "Before cutting, please consider these alternatives:\n"
                f"{_alternatives_text(reason)}\n\n"
                "You can discuss this with your district forest office. Track it here:\n"
                f"{PUBLIC_URL}/my-reviews\n\n- Shishoza")
    EE_POOL.submit(_send_email, email, subject, body)
