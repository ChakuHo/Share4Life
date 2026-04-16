from datetime import timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone


def unread_notifications(request):
    """
    Provides:
      - unread_notifications_count (all unread within retention window)
      - unread_chat_count (only chat notifications within retention window)
      - pending_pings_count (directory donor pings pending + not expired)
    """
    if not request.user.is_authenticated:
        return {
            "unread_notifications_count": 0,
            "unread_chat_count": 0,
            "pending_pings_count": 0,
        }

    days = int(getattr(settings, "NOTIFICATION_RETENTION_DAYS", 7))
    cutoff = timezone.now() - timedelta(days=days)

    # mark old unread as read so badge doesn't stick forever
    try:
        request.user.notifications.filter(
            created_at__lt=cutoff,
            read_at__isnull=True
        ).update(read_at=timezone.now())
    except Exception:
        pass

    unread_qs = request.user.notifications.filter(created_at__gte=cutoff, read_at__isnull=True)
    unread_count = unread_qs.count()
    unread_chat_count = unread_qs.filter(category="CHAT").count()

    # pending pings badge for donors
    pending_pings_count = 0
    if getattr(request.user, "is_donor", False):
        try:
            from communication.models import DirectDonorPing
            now = timezone.now()
            pending_pings_count = (
                DirectDonorPing.objects
                .filter(donor=request.user, status="PENDING")
                .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
                .count()
            )
        except Exception:
            pending_pings_count = 0

    return {
        "unread_notifications_count": unread_count,
        "unread_chat_count": unread_chat_count,
        "pending_pings_count": pending_pings_count,
    }