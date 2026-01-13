from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from .models import Notification

def unread_notifications(request):
    if not request.user.is_authenticated:
        return {"unread_notifications_count": 0}

    days = int(getattr(settings, "NOTIFICATION_RETENTION_DAYS", 7))
    cutoff = timezone.now() - timedelta(days=days)

    count = Notification.objects.filter(
        user=request.user,
        read_at__isnull=True,
        created_at__gte=cutoff,
    ).count()

    return {"unread_notifications_count": count}