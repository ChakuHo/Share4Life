from django.db import transaction
from django.db.models import Q

from .models import Notification, QueuedEmail, NotificationPreference


def _chunked(lst, size=1000):
    for i in range(0, len(lst), size):
        yield lst[i:i + size]


def _get_prefs_map(user_ids):
    prefs = NotificationPreference.objects.filter(user_id__in=user_ids)
    return {p.user_id: p for p in prefs}


def broadcast_inapp(users_qs, title, body="", url="", level="INFO", category="SYSTEM"):
    user_ids = list(users_qs.values_list("id", flat=True))
    if not user_ids:
        return 0

    prefs_map = _get_prefs_map(user_ids)
    cat = (category or "SYSTEM").upper()

    total = 0
    for batch in _chunked(user_ids, 1000):
        rows = []
        for uid in batch:
            pref = prefs_map.get(uid)
            if pref and pref.is_muted(cat):
                continue
            rows.append(Notification(
                user_id=uid,
                category=cat,
                title=title,
                body=body,
                url=url,
                level=level,
            ))
        if rows:
            Notification.objects.bulk_create(rows)
            total += len(rows)
    return total


def queue_email_broadcast(users_qs, subject, body, category="SYSTEM"):
    """
    Queues emails respecting user preferences.
    """
    users_qs = users_qs.exclude(email__isnull=True).exclude(email__exact="")
    rows = list(users_qs.values_list("id", "email"))
    if not rows:
        return 0

    user_ids = [uid for uid, _ in rows]
    prefs_map = _get_prefs_map(user_ids)
    cat = (category or "SYSTEM").upper()

    total = 0
    for batch in _chunked(rows, 1000):
        email_rows = []
        for (uid, email) in batch:
            pref = prefs_map.get(uid)

            if pref and (not pref.email_enabled):
                continue
            if pref and pref.email_emergency_only and cat != "EMERGENCY":
                continue

            email_rows.append(QueuedEmail(user_id=uid, to_email=email, subject=subject, body=body))

        if email_rows:
            QueuedEmail.objects.bulk_create(email_rows)
            total += len(email_rows)

    return total


def broadcast_after_commit(
    users_qs,
    title,
    body="",
    url="",
    level="INFO",
    email_subject=None,
    email_body=None,
    category="SYSTEM",
):
    """
    Runs after DB commit to reduce sqlite lock problems.
    Backward compatible with existing calls.
    """
    def _run():
        broadcast_inapp(users_qs, title=title, body=body, url=url, level=level, category=category)
        if email_subject and email_body:
            queue_email_broadcast(users_qs, subject=email_subject, body=email_body, category=category)

    transaction.on_commit(_run)