from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db import transaction
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.utils.http import url_has_allowed_host_and_scheme
from django.urls import reverse

from accounts.permissions import donor_required, recipient_required
from accounts.models import CustomUser, UserProfile

from blood.eligibility import is_eligible
from blood.matching import blood_group_allowed

from .models import Notification, ChatThread, ChatMessage, NotificationPreference, DirectDonorPing
from .forms import NotificationPreferenceForm
from .services import broadcast_after_commit


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
    from blood.models import PublicBloodRequest, DonorResponse

    blood_req = get_object_or_404(PublicBloodRequest, id=request_id)

    if not blood_req.created_by_id:
        messages.error(request, "Chat is not available for guest-created requests.")
        return redirect(blood_req.get_absolute_url())

    requester_id = blood_req.created_by_id

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


# ---------------- Directory Donor Ping----------------

def _cache_incr(key: str, ttl_seconds: int) -> int:
    try:
        added = cache.add(key, 1, timeout=ttl_seconds)
        if added:
            return 1
        return int(cache.incr(key))
    except Exception:
        val = int(cache.get(key, 0) or 0) + 1
        cache.set(key, val, timeout=ttl_seconds)
        return val


@login_required
@recipient_required
def donor_ping_create(request, donor_id):
    """
    Recipient pings a donor from Public Donor Directory.
    Donor receives in-app notification + queued emaiL.
    """
    donor = get_object_or_404(
        CustomUser.objects.select_related("profile", "kyc"),
        id=donor_id,
        is_active=True,
        is_donor=True,
    )

    # donor must be verified enough for directory safety (same rule as directory)
    donor_verified = bool(donor.is_verified or (getattr(donor, "kyc", None) and donor.kyc.status == "APPROVED"))
    if not donor_verified:
        messages.error(request, "This donor is not verified.")
        return redirect("public_donor_directory")

    # donor must be eligible now
    if not is_eligible(donor):
        messages.error(request, "This donor is currently not eligible.")
        return redirect("public_donor_directory")

    # anti-spam throttles
    today_key = timezone.localdate().strftime("%Y%m%d")
    max_req = int(getattr(settings, "S4L_DONOR_PING_MAX_PER_DAY_PER_REQUESTER", 10))
    max_donor = int(getattr(settings, "S4L_DONOR_PING_MAX_PER_DAY_PER_DONOR", 15))
    cooldown = int(getattr(settings, "S4L_DONOR_PING_PAIR_COOLDOWN_SECONDS", 600))

    req_day_key = f"s4l:ping:req:{request.user.id}:{today_key}"
    donor_day_key = f"s4l:ping:donor:{donor.id}:{today_key}"
    pair_cd_key = f"s4l:ping:pair:{request.user.id}:{donor.id}"

    if request.method == "POST":
        # cooldown same pair
        if cache.get(pair_cd_key):
            messages.error(request, "Please wait a bit before pinging the same donor again.")
            return redirect("donor_ping_create", donor_id=donor.id)

        # daily limits
        if _cache_incr(req_day_key, ttl_seconds=24 * 3600) > max_req:
            messages.error(request, "Daily ping limit reached. Please use the blood request flow.")
            return redirect("public_donor_directory")

        if _cache_incr(donor_day_key, ttl_seconds=24 * 3600) > max_donor:
            messages.error(request, "This donor is receiving too many pings today. Try another donor.")
            return redirect("public_donor_directory")

        blood_group_needed = (request.POST.get("blood_group_needed") or "").strip().upper()
        hospital_name = (request.POST.get("hospital_name") or "").strip()
        city = (request.POST.get("city") or "").strip()
        units_needed = request.POST.get("units_needed") or "1"
        is_emergency = (request.POST.get("is_emergency") or "").strip().lower() in ("1", "true", "yes", "on")
        msg = (request.POST.get("message") or "").strip()
        requester_phone = (request.POST.get("requester_phone") or request.user.phone_number or "").strip()

        # validation
        allowed_groups = {bg for bg, _ in UserProfile.BLOOD_GROUPS}
        if blood_group_needed not in allowed_groups:
            messages.error(request, "Invalid blood group.")
            return redirect("donor_ping_create", donor_id=donor.id)

        try:
            units_needed_int = max(1, int(units_needed))
        except Exception:
            units_needed_int = 1

        if not hospital_name or not city:
            messages.error(request, "Hospital name and city are required.")
            return redirect("donor_ping_create", donor_id=donor.id)

        # IMPORTANT: enforce strict/hybrid blood match between "needed group" and donor group
        donor_bg = (getattr(getattr(donor, "profile", None), "blood_group", "") or "").strip().upper()
        if not donor_bg:
            messages.error(request, "Donor blood group is not set.")
            return redirect("public_donor_directory")

        if not blood_group_allowed(blood_group_needed, donor_bg):
            messages.error(request, f"Blood group mismatch. This donor ({donor_bg}) is not suitable for {blood_group_needed}.")
            return redirect("public_donor_directory")

        # prevent too many open pings in DB (extra safety)
        recent_cutoff = timezone.now() - timedelta(seconds=cooldown)
        if DirectDonorPing.objects.filter(
            requester=request.user, donor=donor, status="PENDING", created_at__gte=recent_cutoff
        ).exists():
            messages.error(request, "You already sent a ping recently. Please wait.")
            return redirect("donor_ping_create", donor_id=donor.id)

        expire_mins = int(getattr(settings, "S4L_DONOR_PING_EXPIRE_MINUTES", 60))
        expires_at = timezone.now() + timedelta(minutes=expire_mins)

        with transaction.atomic():
            ping = DirectDonorPing.objects.create(
                requester=request.user,
                donor=donor,
                blood_group_needed=blood_group_needed,
                units_needed=units_needed_int,
                hospital_name=hospital_name,
                city=city,
                is_emergency=is_emergency,
                requester_phone=requester_phone,
                message=msg,
                status="PENDING",
                expires_at=expires_at,
            )

            # cooldown cache for same pair
            cache.set(pair_cd_key, True, timeout=cooldown)

            # notify donor (in-app + queued email)
            title = "Blood Help Request (Directory Ping)"
            body = (
                f"{request.user.get_full_name() or request.user.username} requests {blood_group_needed} "
                f"({units_needed_int} unit(s)) at {hospital_name}, {city}. "
                f"{'EMERGENCY' if is_emergency else 'Non-emergency'}."
            )
            if msg:
                short = msg if len(msg) <= 160 else (msg[:160] + "…")
                body += f" Message: {short}"

            url = reverse("donor_ping_detail", args=[ping.id])
            users_qs = CustomUser.objects.filter(id=donor.id)

            broadcast_after_commit(
                users_qs,
                title=title,
                body=body,
                url=url,
                level="DANGER" if is_emergency else "INFO",
                email_subject="Share4Life - A recipient needs blood help",
                email_body=body + "\n\nOpen: " + request.build_absolute_uri(url),
                category="EMERGENCY" if is_emergency else "BLOOD",
            )

        messages.success(request, "Ping sent to donor. Wait for their response.")
        return redirect("donor_ping_detail", ping_id=ping.id)

    # GET: render form
    prof = getattr(request.user, "profile", None)
    initial_city = (getattr(prof, "city", "") or "").strip()
    return render(request, "communication/donor_ping_create.html", {
        "donor": donor,
        "blood_groups": UserProfile.BLOOD_GROUPS,
        "initial_city": initial_city,
        "initial_phone": (request.user.phone_number or "").strip(),
        "expire_minutes": int(getattr(settings, "S4L_DONOR_PING_EXPIRE_MINUTES", 60)),
    })


@login_required
@donor_required
def donor_ping_inbox(request):
    qs = (
        DirectDonorPing.objects
        .filter(donor=request.user)
        .select_related("requester", "donor")
        .order_by("-created_at")
    )
    # mark expired visually
    return render(request, "communication/donor_ping_inbox.html", {"items": qs[:200]})


@login_required
def donor_ping_detail(request, ping_id):
    ping = get_object_or_404(
        DirectDonorPing.objects.select_related("requester", "donor"),
        id=ping_id
    )

    # only donor or requester (or staff) can view
    if not (request.user.is_staff or request.user.id in (ping.requester_id, ping.donor_id)):
        return redirect("home")

    expired = ping.is_expired()

    # if donor views and it is expired + still pending => show as expired
    if expired and ping.status == "PENDING":
        pass

    can_donor_respond = bool(request.user.id == ping.donor_id and ping.status == "PENDING" and not expired)
    show_donor_contact_to_requester = bool(request.user.id == ping.requester_id and ping.status == "ACCEPTED")

    return render(request, "communication/donor_ping_detail.html", {
        "ping": ping,
        "expired": expired,
        "can_donor_respond": can_donor_respond,
        "show_donor_contact_to_requester": show_donor_contact_to_requester,
    })


@require_POST
@login_required
@donor_required
def donor_ping_respond(request, ping_id):
    ping = get_object_or_404(
        DirectDonorPing.objects.select_related("requester", "donor"),
        id=ping_id,
        donor=request.user
    )

    if ping.status != "PENDING":
        messages.info(request, "This ping is already responded.")
        return redirect("donor_ping_detail", ping_id=ping.id)

    if ping.is_expired():
        messages.error(request, "This ping has expired.")
        return redirect("donor_ping_detail", ping_id=ping.id)

    action = (request.POST.get("action") or "").strip().upper()
    if action not in ("ACCEPTED", "DECLINED", "DELAYED"):
        messages.error(request, "Invalid action.")
        return redirect("donor_ping_detail", ping_id=ping.id)

    ping.status = action
    ping.responded_at = timezone.now()
    if action == "ACCEPTED":
        ping.accepted_at = timezone.now()

    ping.save(update_fields=["status", "responded_at", "accepted_at"])

    # notify requester
    title = "Donor response (Directory Ping)"
    if action == "ACCEPTED":
        body = (
            f"Donor {request.user.get_full_name() or request.user.username} ACCEPTED your ping "
            f"for {ping.blood_group_needed} at {ping.hospital_name}, {ping.city}."
        )
        if request.user.phone_number:
            body += f" Donor phone: {request.user.phone_number}"
        level = "SUCCESS"
    elif action == "DELAYED":
        body = f"Donor {request.user.get_full_name() or request.user.username} delayed your ping."
        level = "WARNING"
    else:
        body = f"Donor {request.user.get_full_name() or request.user.username} declined your ping."
        level = "DANGER"

    Notification.objects.create(
        user=ping.requester,
        category="BLOOD",
        title=title,
        body=body,
        url=reverse("donor_ping_detail", args=[ping.id]),
        level=level,
    )

    messages.success(request, "Response saved.")
    return redirect("donor_ping_detail", ping_id=ping.id)