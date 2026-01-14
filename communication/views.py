from datetime import timedelta

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.utils.http import url_has_allowed_host_and_scheme
from django.urls import reverse

from .models import Notification


@login_required
def inbox(request):
    days = int(getattr(settings, "NOTIFICATION_RETENTION_DAYS", 7))
    cutoff = timezone.now() - timedelta(days=days)

    # stop old unread notifications (>retention) from keeping the badge forever
    request.user.notifications.filter(created_at__lt=cutoff, read_at__isnull=True).update(read_at=timezone.now())

    items = (
        request.user.notifications
        .filter(created_at__gte=cutoff)
        .order_by("-created_at")[:200]
    )
    return render(request, "communication/inbox.html", {"items": items, "cutoff_days": days})


@login_required
def mark_read(request, pk):
    n = get_object_or_404(Notification, pk=pk, user=request.user)
    n.mark_read()
    return redirect("inbox")


@login_required
def open_notification(request, pk):
    """
    Click 'Open' -> mark as read + redirect to notification url.
    """
    n = get_object_or_404(Notification, pk=pk, user=request.user)
    n.mark_read()

    target = (n.url or "").strip()
    if not target:
        return redirect("inbox")

    # Prevent open-redirect attacks; allow only same-host links or relative paths
    if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        # allow relative internal links like "/blood/request/1/"
        if not target.startswith("/"):
            return redirect("inbox")

    return redirect(target)


@require_POST
@login_required
def mark_all_read(request):
    request.user.notifications.filter(read_at__isnull=True).update(read_at=timezone.now())
    return redirect("inbox")


@require_POST
@login_required
def clear_all(request):
    request.user.notifications.all().delete()
    return redirect("inbox")