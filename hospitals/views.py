from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404

from django.utils import timezone

from accounts.models import CustomUser
from communication.services import broadcast_after_commit
from .forms import OrganizationRegisterForm, AddOrgMemberForm, BloodCampaignForm
from .models import Organization, OrganizationMembership, BloodCampaign
from .permissions import org_member_required

from django.db.models import Q
from blood.models import PublicBloodRequest, BloodDonation

from django.views.decorators.http import require_POST
from django.http import Http404

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


@org_member_required(roles=["ADMIN", "VERIFIER", "STAFF"])
def org_portal(request):
    org = request.organization
    memberships = org.memberships.select_related("user").order_by("-added_at")
    campaigns = org.campaigns.all().order_by("-date", "-created_at")

    # Pending blood requests for this org:
    # - if target_organization is set, match exactly
    # - else fallback by same city (so portal is not empty)
    pending_requests = (
        PublicBloodRequest.objects
        .filter(is_active=True, status__in=["OPEN", "IN_PROGRESS"])
        .filter(verification_status__in=["PENDING", "UNVERIFIED"])
        .filter(
            Q(target_organization=org) |
            Q(target_organization__isnull=True, location_city__iexact=(org.city or ""))
        )
        .order_by("-is_emergency", "-created_at")
    )

    # Pending donations: donor marked COMPLETED, now hospital/org should verify
    pending_donations = (
        BloodDonation.objects
        .filter(status="COMPLETED", request__isnull=False)
        .filter(
            Q(request__target_organization=org) |
            Q(request__target_organization__isnull=True, request__location_city__iexact=(org.city or ""))
        )
        .select_related("donor_user", "request")
        .order_by("-donated_at")
    )

    return render(request, "hospitals/org_portal.html", {
        "org": org,
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


@org_member_required(roles=["ADMIN", "VERIFIER", "STAFF"])
def org_campaign_list(request):
    """
    List all campaigns for this organization.
    """
    org = request.organization
    campaigns = org.campaigns.all().order_by("-date", "-created_at")
    return render(request, "hospitals/org_campaign_list.html", {
        "org": org,
        "campaigns": campaigns,
    })


@org_member_required(roles=["ADMIN"])
def org_campaign_create(request):
    """
    Create a new blood donation campaign.
    """
    org = request.organization

    if request.method == "POST":
        form = BloodCampaignForm(request.POST)
        if form.is_valid():
            camp = form.save(commit=False)
            camp.organization = org
            camp.save()

            # Notify users in the same city

            city = (camp.city or org.city or "").strip()

            users_qs = CustomUser.objects.filter(is_active=True).select_related("profile")

            if city:
                users_qs = users_qs.filter(
                    Q(profile__city__iexact=city) | Q(profile__city__isnull=True) | Q(profile__city__exact="")
                )
            else:
                # if campaign city is missing, notify only blank-city users
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
        form = BloodCampaignForm(request.POST, instance=camp)
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


def _notify_user(user, title, body="", url="", level="INFO"):
    # safe import so hospitals app won't crash if communication changes
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

    # Scope check: this org can verify only its own city or explicitly targeted requests
    allowed = (req.target_organization_id == org.id) or (
        req.target_organization_id is None
        and org.city
        and req.location_city.strip().lower() == org.city.strip().lower()
    )
    if not allowed:
        raise Http404()

    action = (request.POST.get("action") or "").strip()

    if action == "approve":
        req.verification_status = "VERIFIED"
        req.verified_by = request.user
        req.verified_at = timezone.now()
        req.rejection_reason = ""

        # bind target org if not already set
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

        # Close it so it disappears from public + can't be interacted with
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
    donation = get_object_or_404(BloodDonation.objects.select_related("request", "donor_user"), id=donation_id)

    if donation.status != "COMPLETED":
        messages.info(request, "This donation is not pending verification.")
        return redirect("org_portal")

    req = donation.request
    if not req:
        raise Http404()

    allowed = (req.target_organization_id == org.id) or (
        req.target_organization_id is None and org.city and req.location_city.strip().lower() == org.city.strip().lower()
    )
    if not allowed:
        raise Http404()

    donation.mark_verified(request.user, verified_org=org)

    # Notify donor + requester (if exists)
    if donation.donor_user_id:
        _notify_user(donation.donor_user, "Donation verified",
                     f"{org.name} verified your blood donation.",
                     url="/blood/donor/history/", level="SUCCESS")
    if req.created_by_id:
        _notify_user(req.created_by, "Donation verified",
                     f"{org.name} verified a donation for your request.",
                     url=f"/blood/request/{req.id}/", level="SUCCESS")

    messages.success(request, "Donation verified successfully.")
    return redirect("org_portal")

def institutions_home(request):
    # If logged in, send them to the correct place automatically
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
