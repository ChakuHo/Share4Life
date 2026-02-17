import math

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q, Prefetch
from django.http import Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import CustomUser
from blood.matching import city_aliases, canonical_city
from blood.models import PublicBloodRequest, BloodDonation
from communication.services import broadcast_after_commit

from .forms import OrganizationRegisterForm, AddOrgMemberForm, BloodCampaignForm
from .models import Organization, OrganizationMembership, BloodCampaign
from .permissions import org_member_required


# ----------------------------
# Organization registration
# ----------------------------
@login_required
@transaction.atomic
def organization_register(request):
    """
    Logged-in user registers an organization.
    That user becomes org ADMIN (pending until approval).
    """
    if request.method == "POST":
        form = OrganizationRegisterForm(request.POST, request.FILES)
        if form.is_valid():
            org = form.save(commit=False)

            # fill missing details from user profile
            if not org.email:
                org.email = request.user.email
            if not org.phone:
                org.phone = request.user.phone_number or ""
            if not org.city:
                org.city = request.user.profile.city or ""

            org.status = "PENDING"
            org.save()

            # this user is the org admin
            OrganizationMembership.objects.create(
                organization=org,
                user=request.user,
                role="ADMIN",
                is_active=False,  # becomes True when admin approves org
                added_by=None,
            )

            # Email: registration received
            try:
                send_mail(
                    "Share4Life - Organization Registration Received",
                    (
                        f"Dear {request.user.first_name or request.user.username},\n\n"
                        f"We have received your organization registration for '{org.name}'. "
                        f"Our team will review your documents and notify you once it is approved or rejected.\n\n"
                        f"Thank you,\nShare4Life Team"
                    ),
                    settings.DEFAULT_FROM_EMAIL,
                    [request.user.email],
                    fail_silently=True,
                )
            except Exception:
                pass

            messages.success(request, "Organization registered. Awaiting admin approval.")
            return redirect("org_pending")

        messages.error(request, "Please fix the errors and try again.")
    else:
        profile = getattr(request.user, "profile", None)
        form = OrganizationRegisterForm(initial={
            "email": request.user.email,
            "phone": getattr(request.user, "phone_number", ""),
            "city": getattr(profile, "city", "") if profile else "",
        })

    return render(request, "hospitals/org_register.html", {"form": form})


@login_required
def org_pending(request):
    """
    Show the organizations this user is attached to, and their statuses.
    """
    memberships = OrganizationMembership.objects.filter(user=request.user).select_related("organization")
    return render(request, "hospitals/org_pending.html", {"memberships": memberships})


# ----------------------------
# Institution Portal
# ----------------------------
@org_member_required(roles=["ADMIN", "VERIFIER", "STAFF"])
def org_portal(request):
    org = request.organization
    memberships = org.memberships.select_related("user").order_by("-added_at")
    campaigns = org.campaigns.all().order_by("-date", "-created_at")

    org_city_raw = (org.city or "").strip()
    aliases = city_aliases(org_city_raw) if org_city_raw else set()

    # Canonical value (works even if org.city_canon isn't set yet)
    org_canon = (getattr(org, "city_canon", "") or "").strip() or canonical_city(org_city_raw)

    # Fallback tolerant matching for raw city field
    q_city_req = Q()
    for a in aliases:
        a = (a or "").strip()
        if a:
            q_city_req |= Q(location_city__iexact=a) | Q(location_city__icontains=a)

    q_city_don = Q()
    for a in aliases:
        a = (a or "").strip()
        if a:
            q_city_don |= Q(request__location_city__iexact=a) | Q(request__location_city__icontains=a)

    # Canonical DB matching
    q_canon_req = Q()
    q_canon_don = Q()
    if org_canon:
        q_canon_req = Q(location_city_canon=org_canon)
        q_canon_don = Q(request__location_city_canon=org_canon)

    pending_requests = (
        PublicBloodRequest.objects
        .filter(is_active=True, status__in=["OPEN", "IN_PROGRESS"])
        .filter(verification_status__in=["PENDING", "UNVERIFIED"])
        .filter(
            Q(target_organization=org) |
            (Q(target_organization__isnull=True) & (q_canon_req | q_city_req))
        )
        .order_by("-is_emergency", "-created_at")
    )

    pending_donations = (
        BloodDonation.objects
        .filter(status="COMPLETED", request__isnull=False)
        .filter(
            Q(request__target_organization=org) |
            (Q(request__target_organization__isnull=True) & (q_canon_don | q_city_don))
        )
        .select_related("donor_user", "request")
        .order_by("-donated_at")
    )

    org_city_display = org_canon or org_city_raw

    return render(request, "hospitals/org_portal.html", {
        "org": org,
        "org_city_display": org_city_display,
        "memberships": memberships,
        "campaigns": campaigns[:5],
        "pending_requests": pending_requests[:10],
        "pending_donations": pending_donations[:10],
    })


@org_member_required(roles=["ADMIN"])
def org_members(request):
    """
    Admin can add/update members by username or email.
    """
    org = request.organization

    if request.method == "POST":
        form = AddOrgMemberForm(request.POST)
        if form.is_valid():
            ident = form.cleaned_data["identifier"].strip()
            role = form.cleaned_data["role"]

            user = (
                CustomUser.objects.filter(username__iexact=ident).first()
                or CustomUser.objects.filter(email__iexact=ident).first()
            )
            if not user:
                messages.error(request, "User not found.")
                return redirect("org_members")

            m, created = OrganizationMembership.objects.get_or_create(
                organization=org,
                user=user,
                defaults={"role": role, "is_active": True, "added_by": request.user},
            )
            if not created:
                m.role = role
                m.is_active = True
                m.added_by = request.user
                m.save(update_fields=["role", "is_active", "added_by"])

            messages.success(request, "Member updated.")
            return redirect("org_members")

        messages.error(request, "Please fix the errors and try again.")
    else:
        form = AddOrgMemberForm()

    members = org.memberships.select_related("user").order_by("-added_at")
    return render(request, "hospitals/org_members.html", {
        "org": org,
        "form": form,
        "members": members,
    })


# ----------------------------
# Campaigns (Portal)
# ----------------------------
@org_member_required(roles=["ADMIN", "VERIFIER", "STAFF"])
def org_campaign_list(request):
    org = request.organization
    campaigns = org.campaigns.all().order_by("-date", "-created_at")
    return render(request, "hospitals/org_campaign_list.html", {
        "org": org,
        "campaigns": campaigns,
    })


@org_member_required(roles=["ADMIN"])
def org_campaign_create(request):
    org = request.organization

    if request.method == "POST":
        form = BloodCampaignForm(request.POST, request.FILES, instance=camp)
        if form.is_valid():
            camp = form.save(commit=False)
            camp.organization = org
            camp.save()

            # Notify users in same city (use aliases so Patan->Lalitpur works)
            city = (camp.city or org.city or "").strip()

            users_qs = CustomUser.objects.filter(is_active=True).select_related("profile")
            if city:
                aliases = city_aliases(city)
                q = Q()
                for a in aliases:
                    a = (a or "").strip()
                    if a:
                        q |= Q(profile__city__iexact=a) | Q(profile__city__icontains=a)
                users_qs = users_qs.filter(q | Q(profile__city__isnull=True) | Q(profile__city__exact=""))
            else:
                users_qs = users_qs.filter(Q(profile__city__isnull=True) | Q(profile__city__exact=""))

            title = "New Blood Donation Camp"
            body = f"{org.name} created a camp: {camp.title} on {camp.date}. Venue: {camp.venue_name} ({camp.city or org.city})"
            url = "/blood/campaigns/"
            email_body = body + "\n\nOpen: " + url

            broadcast_after_commit(
                users_qs,
                title=title,
                body=body,
                url=url,
                level="INFO",
                email_subject=title,
                email_body=email_body,
                category="CAMPAIGN",
            )

            messages.success(request, "Campaign created.")
            return redirect("org_campaign_list")

        messages.error(request, "Please fix the errors.")
    else:
        form = BloodCampaignForm(initial={"city": org.city})

    return render(request, "hospitals/org_campaign_form.html", {
        "org": org,
        "form": form,
    })


@org_member_required(roles=["ADMIN"])
def org_campaign_edit(request, campaign_id):
    org = request.organization
    camp = get_object_or_404(BloodCampaign, id=campaign_id, organization=org)

    if request.method == "POST":
        form = BloodCampaignForm(request.POST, request.FILES, instance=camp)
        if form.is_valid():
            form.save()
            messages.success(request, "Campaign updated.")
            return redirect("org_campaign_list")
        messages.error(request, "Please fix the errors.")
    else:
        form = BloodCampaignForm(instance=camp)

    return render(request, "hospitals/org_campaign_form.html", {
        "org": org,
        "form": form,
        "is_edit": True,
        "camp": camp,
    })


@require_POST
@org_member_required(roles=["ADMIN"])
def org_campaign_delete(request, campaign_id):
    org = request.organization
    camp = get_object_or_404(BloodCampaign, id=campaign_id, organization=org)
    camp.delete()
    messages.success(request, "Campaign deleted.")
    return redirect("org_campaign_list")


# ----------------------------
# Request / Donation verification (Portal)
# ----------------------------
def _notify_user(user, title, body="", url="", level="INFO"):
    try:
        from communication.models import Notification
    except Exception:
        return
    if not user:
        return
    Notification.objects.create(user=user, title=title, body=body, url=url, level=level)


@require_POST
@org_member_required(roles=["ADMIN", "VERIFIER"])
def org_verify_request(request, request_id):
    org = request.organization
    req = get_object_or_404(PublicBloodRequest, id=request_id)

    # Scope check: target org OR canonical city match
    allowed = (req.target_organization_id == org.id) or (
        req.target_organization_id is None
        and canonical_city(req.location_city) == canonical_city(org.city)
    )
    if not allowed:
        raise Http404()

    action = (request.POST.get("action") or "").strip()

    if action == "approve":
        req.verification_status = "VERIFIED"
        req.verified_by = request.user
        req.verified_at = timezone.now()
        req.rejection_reason = ""

        if req.target_organization_id is None:
            req.target_organization = org

        req.save(update_fields=[
            "verification_status", "verified_by", "verified_at",
            "rejection_reason", "target_organization"
        ])

        if req.created_by_id:
            _notify_user(
                req.created_by,
                "Request verified",
                f"{org.name} verified your blood request.",
                url=f"/blood/request/{req.id}/",
                level="SUCCESS"
            )

        messages.success(request, "Request approved and verified.")
        return redirect("org_portal")

    elif action == "reject":
        reason = (request.POST.get("reason") or "").strip()

        req.verification_status = "REJECTED"
        req.verified_by = request.user
        req.verified_at = timezone.now()
        req.rejection_reason = reason or "Rejected by institution."

        req.status = "CANCELLED"
        req.is_active = False

        if req.target_organization_id is None:
            req.target_organization = org

        req.save(update_fields=[
            "verification_status", "verified_by", "verified_at", "rejection_reason",
            "status", "is_active", "target_organization"
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
        return redirect("org_portal")

    messages.error(request, "Invalid action.")
    return redirect("org_portal")


@require_POST
@org_member_required(roles=["ADMIN", "VERIFIER"])
def org_verify_donation(request, donation_id):
    org = request.organization
    donation = get_object_or_404(
        BloodDonation.objects.select_related("request", "donor_user"),
        id=donation_id
    )

    if donation.status != "COMPLETED":
        messages.info(request, "This donation is not pending verification.")
        return redirect("org_portal")

    req = donation.request
    if not req:
        raise Http404()

    allowed = (req.target_organization_id == org.id) or (
        req.target_organization_id is None
        and canonical_city(req.location_city) == canonical_city(org.city)
    )
    if not allowed:
        raise Http404()

    donation.mark_verified(request.user, verified_org=org)

    if donation.donor_user_id:
        _notify_user(
            donation.donor_user,
            "Donation verified",
            f"{org.name} verified your blood donation.",
            url="/blood/donor/history/",
            level="SUCCESS"
        )
    if req.created_by_id:
        _notify_user(
            req.created_by,
            "Donation verified",
            f"{org.name} verified a donation for your request.",
            url=f"/blood/request/{req.id}/",
            level="SUCCESS"
        )

    messages.success(request, "Donation verified successfully.")
    return redirect("org_portal")


# ----------------------------
# Institutions Home routing
# ----------------------------
def institutions_home(request):
    if request.user.is_authenticated:
        approved = (
            OrganizationMembership.objects
            .filter(user=request.user, is_active=True, organization__status="APPROVED")
            .select_related("organization")
            .order_by("-added_at")
            .first()
        )
        if approved:
            return redirect("org_portal")

        any_m = (
            OrganizationMembership.objects
            .filter(user=request.user)
            .select_related("organization")
            .order_by("-added_at")
            .first()
        )
        if any_m:
            return redirect("org_pending")

        return redirect("org_register")

    return render(request, "hospitals/institutions_home.html")


# ----------------------------
# Public Directory helpers + view
# ----------------------------
def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = (math.sin(dlat / 2) ** 2) + math.cos(p1) * math.cos(p2) * (math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def _tokens(q: str):
    q = (q or "").strip().lower()
    return [t for t in q.replace(",", " ").split() if t]


def institutions_directory(request):
    """
    Public institutions directory:
      - filters: type + city aliases + token search
      - optional: lat/lng -> nearest sort + distance
      - campaigns shown inline (active + past) WITHOUT org portal access
    """
    active_campaigns = (
        BloodCampaign.objects
        .filter(status__in=["UPCOMING", "ONGOING"])
        .order_by("date", "start_time")
    )
    past_campaigns = (
        BloodCampaign.objects
        .filter(status__in=["COMPLETED", "CANCELLED"])
        .order_by("-date", "-created_at")
    )

    qs = (
        Organization.objects
        .filter(status="APPROVED")
        .prefetch_related(
            Prefetch("campaigns", queryset=active_campaigns, to_attr="active_campaigns"),
            Prefetch("campaigns", queryset=past_campaigns, to_attr="past_campaigns"),
        )
    )

    org_type = (request.GET.get("type") or "").strip().upper()
    city = (request.GET.get("city") or "").strip()
    q_raw = (request.GET.get("q") or "").strip()
    toks = _tokens(q_raw)

    if org_type:
        qs = qs.filter(org_type=org_type)

    if city:
        aliases = city_aliases(city)
        q_city = Q()
        for a in aliases:
            a = (a or "").strip()
            if a:
                q_city |= Q(city__iexact=a) | Q(city__icontains=a)
        qs = qs.filter(q_city)

    if toks:
        for t in toks:
            qs = qs.filter(
                Q(name__icontains=t) |
                Q(phone__icontains=t) |
                Q(email__icontains=t) |
                Q(address__icontains=t) |
                Q(city__icontains=t)
            )

    orgs = list(qs.order_by("name"))

    lat = request.GET.get("lat")
    lng = request.GET.get("lng")
    user_lat = user_lng = None
    try:
        if lat and lng:
            user_lat = float(lat)
            user_lng = float(lng)
    except Exception:
        user_lat = user_lng = None

    if user_lat is not None and user_lng is not None:
        for o in orgs:
            o.distance_km = None
            if o.latitude is not None and o.longitude is not None:
                try:
                    o.distance_km = round(_haversine_km(user_lat, user_lng, o.latitude, o.longitude), 2)
                except Exception:
                    o.distance_km = None

        orgs.sort(key=lambda x: (x.distance_km is None, x.distance_km or 10**9, (x.name or "").lower()))

    return render(request, "hospitals/directory.html", {
        "orgs": orgs,
        "city": city,
        "org_type": org_type,
        "q": q_raw,
        "user_lat": user_lat,
        "user_lng": user_lng,
        "ORG_TYPES": Organization.TYPE,
        "results_count": len(orgs),
    })