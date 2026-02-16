from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.utils.http import url_has_allowed_host_and_scheme

from .models import Notification, ChatThread, ChatMessage, NotificationPreference
from .forms import NotificationPreferenceForm
from blood.models import PublicBloodRequest, DonorResponse
from django.urls import reverse

# ---------------- Notifications ----------------
@login_required
def inbox(request):
    days = int(getattr(settings, "NOTIFICATION_RETENTION_DAYS", 7))
    cutoff = timezone.now() - timedelta(days=days)

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
    n = get_object_or_404(Notification, pk=pk, user=request.user)
    n.mark_read()

    target = (n.url or "").strip()
    if not target:
        return redirect("inbox")

    if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
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


# ---------------- Chat ----------------
@login_required
def chat_threads(request):
    qs = (
        ChatThread.objects
        .filter(Q(requester=request.user) | Q(donor=request.user))
        .select_related("request", "requester", "donor")
        .order_by("-last_message_at", "-updated_at")
    )
    return render(request, "communication/chat_threads.html", {"items": qs[:200]})


@login_required
def chat_thread_detail(request, thread_id):
    thread = get_object_or_404(
        ChatThread.objects.select_related("request", "requester", "donor"),
        id=thread_id
    )

    if request.user.id not in (thread.requester_id, thread.donor_id):
        return redirect("chat_threads")

    # mark related chat notifications read
    thread_url = reverse("chat_thread_detail", args=[thread.id])
    request.user.notifications.filter(
        read_at__isnull=True,
        category="CHAT",
        url=thread_url
    ).update(read_at=timezone.now())

    messages_qs = (
        ChatMessage.objects
        .filter(thread=thread)
        .select_related("sender")
        .order_by("created_at")
    )

    return render(request, "communication/chat_thread_detail.html", {
        "thread": thread,
        "messages": messages_qs[:300],
    })


@login_required
def start_blood_chat(request, request_id, donor_id):
    """
    Create/open chat ONLY when:
      - request has an owner (created_by)
      - donor has ACCEPTED that request
      - current user is either requester or that donor
    """
    blood_req = get_object_or_404(PublicBloodRequest, id=request_id)

    if not blood_req.created_by_id:
        messages.error(request, "Chat is not available for guest-created requests.")
        return redirect(blood_req.get_absolute_url())

    requester_id = blood_req.created_by_id

    # current user must be requester or the donor himself
    if request.user.id not in (requester_id, donor_id):
        messages.error(request, "Not allowed.")
        return redirect(blood_req.get_absolute_url())

    accepted = DonorResponse.objects.filter(
        request=blood_req,
        donor_id=donor_id,
        status="ACCEPTED"
    ).exists()

    if not accepted:
        messages.error(request, "Chat opens only after donor ACCEPTS the request.")
        return redirect(blood_req.get_absolute_url())

    thread, _ = ChatThread.objects.get_or_create(
        request=blood_req,
        donor_id=donor_id,
        defaults={"requester_id": requester_id}
    )

    return redirect("chat_thread_detail", thread_id=thread.id)

@login_required
def notification_settings_view(request):
    pref, _ = NotificationPreference.objects.get_or_create(user=request.user)

    if request.method == "POST":
        form = NotificationPreferenceForm(request.POST, instance=pref)
        if form.is_valid():
            form.save()
            messages.success(request, "Notification settings saved.")
            return redirect("notification_settings")
        messages.error(request, "Please fix the errors.")
    else:
        form = NotificationPreferenceForm(instance=pref)

    return render(request, "communication/notification_settings.html", {"form": form})