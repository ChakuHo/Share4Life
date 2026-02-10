# imports-------------------------------------------------------------------------------------------
import os
import requests
from typing import Tuple
from datetime import timedelta
from django.core.cache import cache
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction, IntegrityError
from django.db.models import Case, When, Value, IntegerField, Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import CustomUser
from accounts.permissions import donor_required, recipient_required

from communication.models import Notification
from communication.services import broadcast_after_commit

from hospitals.models import BloodCampaign, OrganizationMembership

from .eligibility import is_eligible, next_eligible_datetime
from .forms import (
    EmergencyRequestForm, GuestResponseForm,
    RecipientRequestForm, DonorResponseForm,
    DonationCreateForm, DonationReportForm,
    BloodRequestEditForm
)
from .models import (
    PublicBloodRequest, GuestResponse, DonorResponse,
    BloodDonation, DonationMedicalReport
)
from .matching import city_aliases
from .realtime import push_request_event, push_ping_to_donors
#------------------------------------------------------------------------------------------------


def _notify_user(user, title, body="", url="", level="INFO"):
    if not user:
        return
    Notification.objects.create(user=user, title=title, body=body, url=url, level=level)

def _client_ip(request):
    # supports proxies if configured
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "") or ""

def verify_recaptcha(request) -> Tuple[bool, str]:
    """
    Returns (ok: bool, error_message: str)
    Never raises exceptions (so it won't crash your site).
    """
    if not getattr(settings, "RECAPTCHA_ENABLED", False):
        return True, ""

    token = (request.POST.get("g-recaptcha-response") or "").strip()
    if not token:
        return False, "Please complete the captcha."

    try:
        resp = requests.post(
            "https://www.google.com/recaptcha/api/siteverify",
            data={
                "secret": settings.RECAPTCHA_SECRET_KEY,
                "response": token,
                "remoteip": _client_ip(request),
            },
            timeout=6,
        )
        data = resp.json()
    except Exception:
        return False, "Captcha verification failed due to network error. Please try again."

    if data.get("success") is True:
        return True, ""

    return False, "Captcha failed/expired. Please try again."

def _throttle_key(prefix: str, value: str) -> str:
    value = (value or "").strip().lower()
    return f"s4l:{prefix}:{value}"


def _cache_incr(key: str, ttl_seconds: int) -> int:
    """
    Increment a counter in cache with a TTL.
    Works even if cache backend doesn't support atomic incr.
    """
    try:
        # If key doesn't exist, add it
        added = cache.add(key, 1, timeout=ttl_seconds)
        if added:
            return 1
        # Otherwise increment (some backends)
        val = cache.incr(key)
        return int(val)
    except Exception:
        # fallback for non-incr backends
        val = int(cache.get(key, 0) or 0) + 1
        cache.set(key, val, timeout=ttl_seconds)
        return val


def allow_guest_emergency_post(phone: str, ip: str) -> Tuple[bool, str]:
    """
    Returns (allowed, reason).
    Blocks:
      - too frequent posts by same phone (min interval)
      - too many per hour per IP
      - too many per hour per phone
      - duplicate DB posts in last few minutes (safety even if cache resets)
    """
    phone = (phone or "").strip()
    ip = (ip or "").strip()

    min_interval = int(getattr(settings, "S4L_GUEST_EMERGENCY_MIN_INTERVAL_SECONDS", 300))
    max_ip = int(getattr(settings, "S4L_GUEST_EMERGENCY_MAX_PER_HOUR_IP", 5))
    max_phone = int(getattr(settings, "S4L_GUEST_EMERGENCY_MAX_PER_HOUR_PHONE", 3))

    # DB duplicate protection (works even if cache is cleared)
    recent_cutoff = timezone.now() - timedelta(seconds=min_interval)
    if phone:
        exists = PublicBloodRequest.objects.filter(
            created_by__isnull=True,
            contact_phone=phone,
            created_at__gte=recent_cutoff,
        ).exists()
        if exists:
            return (False, f"Too many requests from this phone. Try again after {min_interval // 60} minutes.")

    # Cache-based hourly throttles
    hour_ttl = 3600

    if ip:
        ip_key = _throttle_key("guest_emergency_ip_hour", ip)
        ip_count = _cache_incr(ip_key, hour_ttl)
        if ip_count > max_ip:
            return (False, "Too many emergency requests from your network. Please try again later.")

    if phone:
        phone_key = _throttle_key("guest_emergency_phone_hour", phone)
        phone_count = _cache_incr(phone_key, hour_ttl)
        if phone_count > max_phone:
            return (False, "Too many emergency requests from this phone number. Please try again later.")

    return (True, "")


def _notify_org_members(org, title, body="", url="", level="INFO"):
    if not org:
        return
    from hospitals.models import OrganizationMembership
    members = (
        OrganizationMembership.objects
        .filter(organization=org, is_active=True, role__in=["ADMIN", "VERIFIER"])
        .select_related("user")
    )
    for m in members:
        _notify_user(m.user, title, body, url=url, level=level)


# Guest emergency request
def emergency_request_view(request):
    """
    Guest emergency blood request:
    - Proof required (handled by form)
    - Anti-spam: 10-minute cooldown per phone (and hourly limits via cache helper)
    - reCAPTCHA: enabled when RECAPTCHA_ENABLED=True
    """
    if request.method == "POST":
        form = EmergencyRequestForm(request.POST, request.FILES)
        if form.is_valid():
            phone = (form.cleaned_data.get("contact_phone") or "").strip()
            ip = _client_ip(request)

            # 1) Anti-spam throttle FIRST (so user doesn't redo captcha just to be throttled)
            ok_th, reason = allow_guest_emergency_post(phone=phone, ip=ip)
            if not ok_th:
                messages.error(request, reason)
                return render(request, "blood/emergency_form.html", {
                    "form": form,
                    "recaptcha_enabled": getattr(settings, "RECAPTCHA_ENABLED", False),
                    "recaptcha_site_key": getattr(settings, "RECAPTCHA_SITE_KEY", ""),
                })

            # 2) Captcha check
            ok_cap, err = verify_recaptcha(request)
            if not ok_cap:
                messages.error(request, err)
                return render(request, "blood/emergency_form.html", {
                    "form": form,
                    "recaptcha_enabled": getattr(settings, "RECAPTCHA_ENABLED", False),
                    "recaptcha_site_key": getattr(settings, "RECAPTCHA_SITE_KEY", ""),
                })

            # 3) Save request
            obj = form.save(commit=False)
            obj.created_by = None
            obj.is_emergency = True
            obj.status = "OPEN"
            obj.is_active = True
            obj.verification_status = "PENDING"
            obj.save()

            # 4) Ping donors after commit
            transaction.on_commit(lambda: push_ping_to_donors(obj))

            messages.success(request, "Emergency posted. Proof attached and visible to donors.")
            return redirect("public_dashboard")

    else:
        form = EmergencyRequestForm()

    return render(request, "blood/emergency_form.html", {
        "form": form,
        "recaptcha_enabled": getattr(settings, "RECAPTCHA_ENABLED", False),
        "recaptcha_site_key": getattr(settings, "RECAPTCHA_SITE_KEY", ""),
    })


# Logged-in recipient request
@login_required
@recipient_required
def recipient_request_view(request):
    require_proof = not request.user.is_verified  # KYC verified => no proof required

    initial = {
        "patient_name": (request.user.get_full_name().strip() or request.user.username),
        "contact_phone": (request.user.phone_number or ""),
        "location_city": (getattr(request.user, "profile", None).city or "") if getattr(request.user, "profile", None) else "",
    }

    if request.method == "POST":
        form = RecipientRequestForm(request.POST, request.FILES, require_proof=require_proof)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.created_by = request.user
            obj.status = "OPEN"
            obj.is_active = True

            # Blood: KYC verified users are auto-verified
            obj.verification_status = "VERIFIED" if request.user.is_verified else "PENDING"
            obj.save()
            
            transaction.on_commit(lambda: push_ping_to_donors(obj))

            # If emergency, broadcast notification + email to all active users
            if obj.is_emergency:
                users_qs = CustomUser.objects.filter(is_active=True)

                title = "URGENT Blood Request"
                url = obj.get_absolute_url()
                abs_url = request.build_absolute_uri(obj.get_absolute_url())

                body = (
                    f"Urgent need: {obj.blood_group} in {obj.location_city}. "
                    f"Hospital: {obj.hospital_name}. Contact: {obj.contact_phone}"
                )
                email_body = body + f"\n\nOpen: {abs_url}"

                broadcast_after_commit(
                    users_qs,
                    title=title,
                    body=body,
                    url=url,
                    level="DANGER",
                    email_subject=title,
                    email_body=email_body,
                )
            messages.success(request, "Request created successfully.")
            return redirect("my_blood_requests")

        messages.error(request, "Please fix the errors and try again.")
    else:
        form = RecipientRequestForm(require_proof=require_proof, initial=initial)

    return render(request, "blood/recipient_request.html", {
        "form": form,
        "require_proof": require_proof,
    })


# Public feed - show all active, but label verification
def public_dashboard_view(request):
    qs = (
        PublicBloodRequest.objects
        .filter(is_active=True, status__in=["OPEN", "IN_PROGRESS"])
        .exclude(verification_status="REJECTED")
        .annotate(
            v_rank=Case(
                When(verification_status="VERIFIED", then=Value(0)),
                When(verification_status="PENDING", then=Value(1)),
                default=Value(2),
                output_field=IntegerField(),
            )
        )
        .order_by("-is_emergency", "v_rank", "-created_at")
        .exclude(verification_status__in=["REJECTED", "UNVERIFIED"])
    )

    blood_group = (request.GET.get("blood_group") or "").strip()
    city = (request.GET.get("city") or "").strip()

    if blood_group and blood_group in ["A+","A-","B+","B-","AB+","AB-","O+","O-"]:
        qs = qs.filter(blood_group=blood_group)

    if city:
        aliases = city_aliases(city)  # {"ktm","kathmandu",...} etc
        q = Q()
        for a in aliases:
            q |= Q(location_city__iexact=a)
        qs = qs.filter(q)

    donor_eligible = None
    donor_next_eligible = None
    if request.user.is_authenticated and getattr(request.user, "is_donor", False):
        donor_eligible = is_eligible(request.user)
        donor_next_eligible = next_eligible_datetime(request.user)

    return render(request, "blood/public_dashboard.html", {
        "requests": qs,
        "donor_eligible": donor_eligible,
        "donor_next_eligible": donor_next_eligible,
    })


# Request detail - public
def request_detail_view(request, request_id, slug=None):
    blood_req = get_object_or_404(PublicBloodRequest, id=request_id)

    # SEO: redirect legacy URL -> canonical slug URL (GET only)
    if request.method == "GET":
        canonical = blood_req.get_absolute_url()
        if slug != (blood_req.slug or ""):
            return redirect(canonical, permanent=True)

    guest_responses = blood_req.responses.order_by("-responded_at")
    donor_responses = blood_req.donor_responses.select_related("donor").order_by("-responded_at", "-created_at")
    donations = blood_req.donations.select_related("donor_user").order_by("-donated_at")

    is_active_request = bool(blood_req.is_active and blood_req.status in ("OPEN", "IN_PROGRESS"))

    org_membership_req = None
    org_can_verify = False

    if request.user.is_authenticated:
        memberships = (
            OrganizationMembership.objects
            .filter(user=request.user, is_active=True, organization__status="APPROVED")
            .select_related("organization")
            .order_by("-added_at")
        )

        req_city = (blood_req.location_city or "").strip().lower()
        target_org_id = blood_req.target_organization_id

        for m in memberships:
            org = m.organization
            org_city = (org.city or "").strip().lower()

            allowed = False
            if target_org_id:
                allowed = (org.id == target_org_id)
            else:
                allowed = bool(req_city and org_city and req_city == org_city)

            if allowed:
                org_membership_req = m
                break

        if org_membership_req and org_membership_req.role in ("ADMIN", "VERIFIER"):
            org_can_verify = True

    can_view_proof = bool(
        blood_req.proof_document and (
            (request.user.is_authenticated and (
                request.user.is_staff
                or getattr(request.user, "is_hospital_admin", False)
                or (blood_req.created_by_id == request.user.id)
                or (org_membership_req is not None)
            ))
        )
    )

    can_view_donor_contact = (
        request.user.is_authenticated and (
            request.user.is_staff
            or getattr(request.user, "is_hospital_admin", False)
            or (blood_req.created_by_id == request.user.id)
        )
    )

    eligible_info = None
    my_response = None
    my_donation = None
    can_mark_donation = False
    can_respond = False

    if request.user.is_authenticated and getattr(request.user, "is_donor", False):
        eligible = is_eligible(request.user)
        eligible_info = {
            "eligible": eligible,
            "next_date": next_eligible_datetime(request.user),
        }

        my_response = DonorResponse.objects.filter(request=blood_req, donor=request.user).first()
        my_donation = BloodDonation.objects.filter(request=blood_req, donor_user=request.user).first()

        can_respond = is_active_request

        can_mark_donation = (
            is_active_request
            and eligible
            and my_donation is None
            and my_response is not None
            and my_response.status == "ACCEPTED"
        )

    return render(request, "blood/request_detail.html", {
        "req": blood_req,
        "guest_responses": guest_responses,
        "donor_responses": donor_responses,
        "donations": donations,
        "is_active_request": is_active_request,
        "can_view_proof": can_view_proof,
        "org_membership_req": org_membership_req,
        "org_can_verify": org_can_verify,
        "eligible_info": eligible_info,
        "my_response": my_response,
        "my_donation": my_donation,
        "can_mark_donation": can_mark_donation,
        "can_respond": can_respond,
        "can_view_donor_contact": can_view_donor_contact,
    })

# Guest donate and notify recipient if possible
def guest_donate_view(request, request_id):
    blood_req = get_object_or_404(PublicBloodRequest, id=request_id)

    # If logged in, guest flow is not needed
    if request.user.is_authenticated:
        messages.info(request, "You are logged in. Please use donor response instead of guest donation.")
        return redirect("blood_request_detail", request_id=blood_req.id)

    # Don't allow guest response if request closed
    if blood_req.status in ("FULFILLED", "CANCELLED") or not blood_req.is_active:
        messages.error(request, "This request is closed.")
        return redirect("public_dashboard")

    if request.method == "POST":
        form = GuestResponseForm(request.POST)
        if form.is_valid():
            response = form.save(commit=False)
            response.request = blood_req
            response.save()

            if blood_req.status == "OPEN":
                blood_req.status = "IN_PROGRESS"
                blood_req.save(update_fields=["status"])

            # Notify the requester ONLY if this request was created by a logged-in user
            if blood_req.created_by_id:
                _notify_user(
                    blood_req.created_by,
                    "A guest donor is coming",
                    f"{response.donor_name} ({response.donor_phone}) responded to your request.",
                    url=f"/blood/request/{blood_req.id}/",
                    level="SUCCESS",
                )

            messages.success(request, "Thank you! The patient has been notified that you are coming.")
            return redirect("public_dashboard")
    else:
        form = GuestResponseForm()

    return render(request, "blood/guest_response.html", {"form": form, "req": blood_req})


# Registered donor respond
@login_required
@donor_required
def donor_respond_view(request, request_id):
    blood_req = get_object_or_404(PublicBloodRequest, id=request_id)

    # block self-response
    if blood_req.created_by_id and blood_req.created_by_id == request.user.id:
        messages.error(request, "You created this request. You cannot respond as a donor to your own request.")
        return redirect("blood_request_detail", request_id=blood_req.id)

    if blood_req.status in ("FULFILLED", "CANCELLED") or not blood_req.is_active:
        messages.error(request, "This request is closed.")
        return redirect("blood_request_detail", request_id=blood_req.id)

    if not is_eligible(request.user):
        nxt = next_eligible_datetime(request.user)
        messages.error(request, f"You are not eligible yet. Eligible again on: {nxt.date() if nxt else 'N/A'}")
        return redirect("blood_request_detail", request_id=blood_req.id)

    obj = DonorResponse.objects.filter(request=blood_req, donor=request.user).first()

    if request.method == "POST":
        if obj is None:
            obj = DonorResponse(request=blood_req, donor=request.user)

        form = DonorResponseForm(request.POST, instance=obj)
        if form.is_valid():
            resp = form.save(commit=False)
            resp.responded_at = timezone.now()
            resp.save()

            if resp.status == "ACCEPTED" and blood_req.status == "OPEN":
                blood_req.status = "IN_PROGRESS"
                blood_req.save(update_fields=["status"])

            if blood_req.created_by_id:
                phone = (request.user.phone_number or "").strip()
                phone_txt = f" Phone: {phone}" if phone else ""
                _notify_user(
                    blood_req.created_by,
                    "Donor response",
                    f"Donor {request.user.username} responded: {resp.status}.{phone_txt}",
                    url=f"/blood/request/{blood_req.id}/",
                    level="INFO",
                )

            messages.success(request, "Response submitted.")
            return redirect("blood_request_detail", request_id=blood_req.id)

        messages.error(request, "Please fix the errors.")
    else:
        form = DonorResponseForm(instance=obj)

    return render(request, "blood/donor_respond.html", {"form": form, "req": blood_req})


# Donor marks donation completed (creates donation history)
@login_required
@donor_required
def donation_create_view(request, request_id):
    blood_req = get_object_or_404(PublicBloodRequest, id=request_id)

    # block self-donation (request owner cannot record donation for own request)
    if blood_req.created_by_id and blood_req.created_by_id == request.user.id:
        messages.error(request, "You created this request. You cannot record donation to your own request.")
        return redirect("blood_request_detail", request_id=blood_req.id)

    # block if request is closed
    if blood_req.status in ("FULFILLED", "CANCELLED") or not blood_req.is_active:
        messages.error(request, "This request is closed.")
        return redirect("blood_request_detail", request_id=blood_req.id)

    # donor eligibility check
    if not is_eligible(request.user):
        nxt = next_eligible_datetime(request.user)
        messages.error(request, f"You are not eligible yet. Eligible again on: {nxt.date() if nxt else 'N/A'}")
        return redirect("blood_request_detail", request_id=blood_req.id)

    # quick check
    existing = BloodDonation.objects.filter(request=blood_req, donor_user=request.user).first()
    if existing:
        messages.info(request, "You already recorded a donation for this request.")
        return redirect("donor_history")

    if request.method == "POST":
        form = DonationCreateForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    donation, created = BloodDonation.objects.get_or_create(
                        request=blood_req,
                        donor_user=request.user,
                        defaults={
                            "hospital_name": form.cleaned_data["hospital_name"],
                            "units": form.cleaned_data["units"],
                            "donated_at": form.cleaned_data["donated_at"],
                            "blood_group": request.user.profile.blood_group or "",
                            "status": "COMPLETED",
                        }
                    )

                if not created:
                    messages.info(request, "You already recorded a donation for this request.")
                    return redirect("donor_history")

            except IntegrityError:
                messages.info(request, "You already recorded a donation for this request.")
                return redirect("donor_history")

            # Move request to IN_PROGRESS if it was OPEN
            if blood_req.status == "OPEN":
                blood_req.status = "IN_PROGRESS"
                blood_req.save(update_fields=["status"])

            # notify requester if exists
            if blood_req.created_by_id:
                _notify_user(
                    blood_req.created_by,
                    "Donation marked completed",
                    f"Donor {request.user.username} marked donation completed. Awaiting verification.",
                    url=f"/blood/request/{blood_req.id}/",
                    level="SUCCESS",
                )

            # Notify org members (if request is linked to an org)
            if blood_req.target_organization_id:
                _notify_org_members(
                    blood_req.target_organization,
                    "Donation awaiting verification",
                    f"Donation marked COMPLETED by {request.user.username} for request #{blood_req.id}.",
                    url="/institutions/portal/",
                    level="INFO",
                )

            messages.success(request, "Donation recorded. Awaiting verification.")
            return redirect("donor_history")

        messages.error(request, "Please fix the errors.")
    else:
        form = DonationCreateForm(initial={
            "hospital_name": blood_req.hospital_name,
            "units": blood_req.units_needed,
        })

    return render(request, "blood/donation_create.html", {"form": form, "req": blood_req})


# Donor history
@login_required
@donor_required
def donor_history_view(request):
    donations = BloodDonation.objects.filter(donor_user=request.user).prefetch_related("reports").order_by("-donated_at")
    return render(request, "blood/donor_history.html", {
        "donations": donations,
        "eligible": is_eligible(request.user),
        "next_eligible": next_eligible_datetime(request.user),
    })

@login_required
@recipient_required
def blood_request_edit_view(request, request_id):
    req = get_object_or_404(PublicBloodRequest, id=request_id, created_by=request.user)

    if req.status in ("FULFILLED", "CANCELLED") or not req.is_active:
        messages.error(request, "You cannot edit a closed request.")
        return redirect("blood_request_detail", request_id=req.id)

    if request.method == "POST":
        form = BloodRequestEditForm(request.POST, request.FILES, instance=req, user=request.user)
        if form.is_valid():
            obj = form.save(commit=False)

            # re-review after edit (keeps platform trustworthy)
            obj.verification_status = "VERIFIED" if request.user.is_verified else "PENDING"
            obj.rejection_reason = ""
            obj.verified_by = None
            obj.verified_at = None

            obj.save()
            messages.success(request, "Request updated.")
            return redirect("blood_request_detail", request_id=obj.id)
        messages.error(request, "Please fix the errors.")
    else:
        form = BloodRequestEditForm(instance=req, user=request.user)

    return render(request, "blood/request_edit.html", {"form": form, "req": req})


@require_POST
@login_required
def blood_request_cancel_view(request, request_id):
    req = get_object_or_404(PublicBloodRequest, id=request_id)

    if not (request.user.is_staff or req.created_by_id == request.user.id):
        raise Http404()

    if req.status in ("FULFILLED", "CANCELLED") or not req.is_active:
        messages.info(request, "This request is already closed.")
        return redirect("blood_request_detail", request_id=req.id)

    req.status = "CANCELLED"
    req.is_active = False
    req.save(update_fields=["status", "is_active"])

    messages.success(request, "Request cancelled.")
    return redirect("my_blood_requests")

# Upload medical report
@login_required
def donation_report_upload_view(request, donation_id):
    donation = get_object_or_404(BloodDonation, id=donation_id)

    if not (request.user.is_staff or donation.donor_user_id == request.user.id):
        raise Http404()

    if request.method == "POST":
        form = DonationReportForm(request.POST, request.FILES)
        if form.is_valid():
            rep = form.save(commit=False)
            rep.donation = donation
            rep.uploaded_by = request.user
            rep.save()
            messages.success(request, "Report uploaded.")
            return redirect("donor_history")
        messages.error(request, "Please fix the errors.")
    else:
        form = DonationReportForm()

    return render(request, "blood/report_upload.html", {"form": form, "donation": donation})


# Protected report download
@login_required
def donation_report_download_view(request, report_id):
    report = get_object_or_404(DonationMedicalReport, id=report_id)
    donation = report.donation
    if not (request.user.is_staff or donation.donor_user_id == request.user.id):
        raise Http404()
    return FileResponse(report.file.open("rb"), as_attachment=True, filename=os.path.basename(report.file.name))

# Protected report inline view
@login_required
def donation_report_view_inline(request, report_id):
    report = get_object_or_404(DonationMedicalReport, id=report_id)
    donation = report.donation
    if not (request.user.is_staff or donation.donor_user_id == request.user.id):
        raise Http404()
    return FileResponse(report.file.open("rb"), as_attachment=False)


# Recipient: My Requests
@login_required
@recipient_required
def my_blood_requests_view(request):
    items = PublicBloodRequest.objects.filter(created_by=request.user).order_by("-created_at")
    return render(request, "blood/my_requests.html", {"items": items})


# Hospital/Admin verifies request proof
@login_required
def verify_request_view(request, request_id):
    if not (request.user.is_staff or getattr(request.user, "is_hospital_admin", False)):
        raise Http404()

    req = get_object_or_404(PublicBloodRequest, id=request_id)

    if request.method != "POST":
        raise Http404()

    action = (request.POST.get("action") or "").strip()

    if action == "approve":
        req.verification_status = "VERIFIED"
        req.verified_by = request.user
        req.verified_at = timezone.now()
        req.rejection_reason = ""
        req.save(update_fields=["verification_status", "verified_by", "verified_at", "rejection_reason"])

        if req.created_by_id:
            _notify_user(
                req.created_by,
                "Request verified",
                "Your blood request has been verified.",
                url=f"/blood/request/{req.id}/",
                level="SUCCESS"
            )

        messages.success(request, "Request verified.")
        return redirect("blood_request_detail", request_id=req.id)

    elif action == "reject":
        reason = (request.POST.get("reason") or "").strip()

        req.verification_status = "REJECTED"
        req.verified_by = request.user
        req.verified_at = timezone.now()
        req.rejection_reason = reason or "Rejected by staff/admin."

        # Close it so it disappears from public + can't be interacted with
        req.status = "CANCELLED"
        req.is_active = False

        req.save(update_fields=[
            "verification_status", "verified_by", "verified_at", "rejection_reason",
            "status", "is_active"
        ])

        if req.created_by_id:
            _notify_user(
                req.created_by,
                "Request rejected",
                req.rejection_reason,
                url=f"/blood/request/{req.id}/",
                level="DANGER"
            )

        messages.error(request, "Request rejected.")
        return redirect("blood_request_detail", request_id=req.id)

    messages.error(request, "Invalid action.")
    return redirect("blood_request_detail", request_id=req.id)

@require_POST
@login_required
def verify_donation_view(request, donation_id):
    donation = get_object_or_404(
        BloodDonation.objects.select_related("request", "request__target_organization", "donor_user"),
        id=donation_id
    )

    if not donation.request_id:
        raise Http404()

    req = donation.request

    # Staff / hospital admin always allowed
    if request.user.is_staff or getattr(request.user, "is_hospital_admin", False):
        allowed_org = req.target_organization if req.target_organization_id else None
    else:
        # Org members (ADMIN/VERIFIER) allowed only in scope (target org OR city match)
        memberships = (
            OrganizationMembership.objects
            .filter(user=request.user, is_active=True, organization__status="APPROVED")
            .select_related("organization")
            .order_by("-added_at")
        )

        req_city = (req.location_city or "").strip().lower()
        target_org_id = req.target_organization_id

        allowed_org = None
        ok = False

        for m in memberships:
            if m.role not in ("ADMIN", "VERIFIER"):
                continue
            org = m.organization
            org_city = (org.city or "").strip().lower()

            if target_org_id:
                if org.id == target_org_id:
                    ok = True
                    allowed_org = org
                    break
            else:
                if req_city and org_city and req_city == org_city:
                    ok = True
                    allowed_org = org
                    break

        if not ok:
            raise Http404()

    # Verify (idempotent)
    before = donation.status
    donation.mark_verified(request.user, verified_org=allowed_org)

    # Notifications
    if before != "VERIFIED":
        if donation.donor_user_id:
            _notify_user(
                donation.donor_user,
                "Blood donation verified",
                f"Your donation for request #{req.id} was verified.",
                url=req.get_absolute_url(),
                level="SUCCESS",
            )
        if req.created_by_id:
            _notify_user(
                req.created_by,
                "Donation verified",
                f"A donation was verified for your request #{req.id}.",
                url=req.get_absolute_url(),
                level="SUCCESS",
            )

    messages.success(request, "Donation verified.")
    return redirect(req.get_absolute_url())


# showing feed proof document
def request_proof_view(request, request_id):
    req = get_object_or_404(PublicBloodRequest, id=request_id)
    if not req.proof_document:
        raise Http404()
    return FileResponse(req.proof_document.open("rb"), as_attachment=False)

def blood_campaigns_view(request):
    today = timezone.now().date()
    campaigns = (
        BloodCampaign.objects
        .filter(
            organization__status="APPROVED",
            status__in=["UPCOMING", "ONGOING"],
            date__gte=today
        )
        .select_related("organization")
        .order_by("date", "start_time")
    )
    return render(request, "blood/campaign_list.html", {"campaigns": campaigns})

@require_POST
@login_required
@donor_required
def quick_respond_view(request, request_id):
    blood_req = get_object_or_404(PublicBloodRequest, id=request_id)

    # detect fetch/ajax
    wants_json = (
        request.headers.get("x-requested-with") == "XMLHttpRequest"
        or "application/json" in (request.headers.get("accept") or "").lower()
    )

    def _json_error(msg, status=400, redirect_url=""):
        return JsonResponse({"ok": False, "error": msg, "redirect_url": redirect_url}, status=status)

    # block self response
    if blood_req.created_by_id and blood_req.created_by_id == request.user.id:
        if wants_json:
            return _json_error("You cannot respond to your own request.", status=403,
                               redirect_url=f"/blood/request/{blood_req.id}/")
        return redirect("blood_request_detail", request_id=blood_req.id)

    # closed?
    if blood_req.status in ("FULFILLED", "CANCELLED") or not blood_req.is_active:
        if wants_json:
            return _json_error("This request is closed.", status=409,
                               redirect_url=f"/blood/request/{blood_req.id}/")
        messages.error(request, "This request is closed.")
        return redirect("blood_request_detail", request_id=blood_req.id)

    # eligibility check
    if not is_eligible(request.user):
        if wants_json:
            return _json_error("You are not eligible to donate right now.", status=403,
                               redirect_url=f"/blood/request/{blood_req.id}/")
        messages.error(request, "You are not eligible to donate right now.")
        return redirect("blood_request_detail", request_id=blood_req.id)

    status = (request.POST.get("status") or "").strip().upper()
    message_txt = (request.POST.get("message") or "").strip()

    if status not in ("ACCEPTED", "DECLINED", "DELAYED"):
        if wants_json:
            return _json_error("Invalid response.", status=400,
                               redirect_url=f"/blood/request/{blood_req.id}/")
        messages.error(request, "Invalid response.")
        return redirect("blood_request_detail", request_id=blood_req.id)

    obj, _ = DonorResponse.objects.get_or_create(request=blood_req, donor=request.user)
    old_status = obj.status

    obj.status = status
    obj.message = message_txt
    obj.responded_at = timezone.now()
    obj.save(update_fields=["status", "message", "responded_at"])

    if status == "ACCEPTED" and blood_req.status == "OPEN":
        blood_req.status = "IN_PROGRESS"
        blood_req.save(update_fields=["status"])

    # notify requester (avoid spam if clicking same button repeatedly)
    if blood_req.created_by_id and old_status != status:
        phone = (request.user.phone_number or "").strip()
        phone_txt = f" Phone: {phone}" if phone else ""
        _notify_user(
            blood_req.created_by,
            "Donor response",
            f"{request.user.username} responded: {status}.{phone_txt}",
            url=f"/blood/request/{blood_req.id}/",
            level="INFO",
        )

    # realtime update to request room
    push_request_event(blood_req.id, {
        "type": "DONOR_RESPONSE",
        "donor": request.user.username,
        "status": status,
        "message": message_txt,
        "at": obj.responded_at.isoformat(),
    })

    # JSON for fetch, redirect for normal browser POST
    if wants_json:
        return JsonResponse({
            "ok": True,
            "request_id": blood_req.id,
            "status": status,
            "redirect_url": blood_req.get_absolute_url(),
        })

    messages.success(request, "Response sent.")
    return redirect("blood_request_detail", request_id=blood_req.id)