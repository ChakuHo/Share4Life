from django.db import transaction
from django.db.models import Q

from .models import Notification, QueuedEmail

def _chunked(lst, size=1000):
    for i in range(0, len(lst), size):
        yield lst[i:i+size]

def broadcast_inapp(users_qs, title, body="", url="", level="INFO"):
    user_ids = list(users_qs.values_list("id", flat=True))
    if not user_ids:
        return 0

    total = 0
    for batch in _chunked(user_ids, 1000):
        Notification.objects.bulk_create([
            Notification(user_id=uid, title=title, body=body, url=url, level=level)
            for uid in batch
        ])
        total += len(batch)
    return total

def queue_email_broadcast(users_qs, subject, body):
    users_qs = users_qs.exclude(email__isnull=True).exclude(email__exact="")
    rows = list(users_qs.values_list("id", "email"))
    if not rows:
        return 0

    total = 0
    for batch in _chunked(rows, 1000):
        QueuedEmail.objects.bulk_create([
            QueuedEmail(user_id=uid, to_email=email, subject=subject, body=body)
            for (uid, email) in batch
        ])
        total += len(batch)
    return total

def broadcast_after_commit(users_qs, title, body="", url="", level="INFO",
                          email_subject=None, email_body=None):
    """
    Runs after DB commit (reduces sqlite lock problems).
    """
    def _run():
        broadcast_inapp(users_qs, title=title, body=body, url=url, level=level)
        if email_subject and email_body:
            queue_email_broadcast(users_qs, subject=email_subject, body=email_body)

    transaction.on_commit(_run)