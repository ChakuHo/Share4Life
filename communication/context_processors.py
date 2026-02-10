from datetime import timedelta
from django.conf import settings
from django.utils import timezone


def unread_notifications(request):
    """
    Provides:
      - unread_notifications_count (all unread)
      - unread_chat_count (only chat notifications)
    """
    if not request.user.is_authenticated:
        return {"unread_notifications_count": 0, "unread_chat_count": 0}

    days = int(getattr(settings, "NOTIFICATION_RETENTION_DAYS", 7))
    cutoff = timezone.now() - timedelta(days=days)

    # mark old unread as read so badge doesn't stick forever
    request.user.notifications.filter(created_at__lt=cutoff, read_at__isnull=True).update(read_at=timezone.now())

    unread_qs = request.user.notifications.filter(created_at__gte=cutoff, read_at__isnull=True)
    unread_count = unread_qs.count()

    unread_chat_count = unread_qs.filter(title="New chat message").count()

    return {
        "unread_notifications_count": unread_count,
        "unread_chat_count": unread_chat_count,
    }