from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.db import IntegrityError
from django.db.models import Q
from django.db.utils import NotSupportedError

from communication.models import Notification
from hospitals.permissions import org_member_required
from hospitals.models import OrganizationMembership

from .models import (
    OrganPledge, OrganPledgeDocument,
    OrganRequest, OrganRequestDocument,
    OrganMatch
)
from .forms import (
    OrganPledgeForm, OrganPledgeDocumentForm,
    OrganRequestForm, OrganRequestDocumentForm,
    OrganMatchCreateForm, OrganMatchStatusForm
)


def _notify_user(user, title, body="", url="", level="INFO"):
    if not user:
        return
    Notification.objects.create(user=user, title=title, body=body, url=url, level=level)


def _norm_city(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


def _notify_org_members(org, title, body="", url="", level="INFO"):
    """
    Notify all active org members (ADMIN/VERIFIER/STAFF) of a single organization.
    """
    if not org:
        return

    members = (
        OrganizationMembership.objects
        .filter(
            organization=org,
            is_active=True,
            role__in=["ADMIN", "VERIFIER", "STAFF"],
            organization__status="APPROVED",
        )
        .select_related("user")
    )
    for m in members:
        _notify_user(m.user, title, body, url=url, level=level)


def _notify_orgs_in_city(city: str, title, body="", url="", level="INFO"):
    """
    Option 1: Notify ALL approved organizations in the same city.
    """
    from hospitals.models import Organization  # local import avoids circular imports

    city_raw = (city or "").strip()
    if not city_raw:
        return

    orgs = Organization.objects.filter(status="APPROVED", city__iexact=city_raw)
    for org in orgs:
        _notify_org_members(org, title, body, url=url, level=level)


def _user_org_membership(user):
    """
    Returns latest approved active org membership or None.
    """
    if not user.is_authenticated:
        return None
    return (
        OrganizationMembership.objects
        .filter(user=user, is_active=True, organization__status="APPROVED")
        .select_related("organization")
        .order_by("-added_at")
        .first()
    )


def _org_can_access_request(org, req: OrganRequest) -> bool:
    """
    Org scope rule:
      - if req.target_organization is set => must match org
      - else => city match (iexact)
    """
    if req.target_organization_id is not None:
        return req.target_organization_id == org.id

    oc = _norm_city(org.city)
    rc = _norm_city(req.city)
    return bool(oc and rc and oc == rc)


def _org_can_verify_pledge(org, pledge: OrganPledge) -> bool:
    """
    City-scoped if org.city exists, else global fallback.
    SAFETY: donor may not have a profile in some edge cases.
    """
    oc = _norm_city(org.city)
    if not oc:
        return True

    donor_profile = getattr(pledge.donor, "profile", None)
    donor_city = _norm_city(getattr(donor_profile, "city", ""))
    return donor_city == oc


# ---------------- Donor pledge ----------------
@login_required
def pledge_create(request):
    if request.method == "POST":
        form = OrganPledgeForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.donor = request.user
            obj.status = "DRAFT"
            obj.save()
            obj.organs = form.cleaned_data["organs"]
            obj.save(update_fields=["organs"])
            messages.success(request, "Pledge created. Upload documents and submit for review.")
            return redirect("organ_pledge_detail", pledge_id=obj.id)
        messages.error(request, "Please fix the errors.")
    else:
        form = OrganPledgeForm()

    return render(request, "organ/pledge_create.html", {"form": form})


@login_required
def pledge_list(request):
    pledges = OrganPledge.objects.filter(donor=request.user).order_by("-created_at")
    return render(request, "organ/pledge_list.html", {"pledges": pledges})


@login_required
def pledge_detail(request, pledge_id):
    pledge = get_object_or_404(OrganPledge, id=pledge_id, donor=request.user)
    doc_form = OrganPledgeDocumentForm()
    return render(request, "organ/pledge_detail.html", {"pledge": pledge, "doc_form": doc_form})


@require_POST
@login_required
def pledge_doc_upload(request, pledge_id):
    pledge = get_object_or_404(OrganPledge, id=pledge_id, donor=request.user)
    form = OrganPledgeDocumentForm(request.POST, request.FILES)
    if form.is_valid():
        doc = form.save(commit=False)
        doc.pledge = pledge
        doc.save()
        messages.success(request, "Document uploaded.")
    else:
        messages.error(request, "Please fix the errors.")
    return redirect("organ_pledge_detail", pledge_id=pledge.id)


@require_POST
@login_required
def pledge_submit(request, pledge_id):
    pledge = get_object_or_404(OrganPledge, id=pledge_id, donor=request.user)

    if pledge.status in ("VERIFIED", "UNDER_REVIEW"):
        messages.info(request, "This pledge is already under review/verified.")
        return redirect("organ_pledge_detail", pledge_id=pledge.id)

    if not pledge.consent_confirmed:
        messages.error(request, "Consent must be confirmed before submitting.")
        return redirect("organ_pledge_detail", pledge_id=pledge.id)

    if pledge.documents.count() == 0:
        messages.error(request, "Upload at least one document (consent/medical report) before submitting.")
        return redirect("organ_pledge_detail", pledge_id=pledge.id)

    pledge.status = "UNDER_REVIEW"
    pledge.submitted_at = timezone.now()
    if not pledge.consent_at:
        pledge.consent_at = timezone.now()
    pledge.save(update_fields=["status", "submitted_at", "consent_at"])

    # Donor notification (already)
    _notify_user(
        request.user,
        "Organ pledge submitted",
        "Your pledge is submitted for verification.",
        url=f"/organ/pledge/{pledge.id}/",
        level="INFO",
    )

    # - Org notification: all orgs in donor city
    donor_city = getattr(getattr(request.user, "profile", None), "city", "")
    _notify_orgs_in_city(
        donor_city,
        "New organ pledge pending verification",
        f"Pledge #{pledge.id} submitted by {request.user.username}.",
        url="/organ/portal/",
        level="INFO",
    )

    messages.success(request, "Pledge submitted for verification.")
    return redirect("organ_pledge_detail", pledge_id=pledge.id)


@require_POST
@login_required
def pledge_revoke(request, pledge_id):
    pledge = get_object_or_404(OrganPledge, id=pledge_id, donor=request.user)

    pledge.status = "REVOKED"
    pledge.revoked_at = timezone.now()
    pledge.save(update_fields=["status", "revoked_at"])

    messages.success(request, "Pledge revoked.")
    return redirect("organ_pledge_list")


# ---------------- Recipient requests ----------------
@login_required
def organ_request_create(request):
    is_org_member = OrganizationMembership.objects.filter(
        user=request.user, is_active=True, organization__status="APPROVED"
    ).exists()

    if not (getattr(request.user, "is_recipient", False) or is_org_member):
        messages.error(request, "Enable Recipient role or join an institution to create organ requests.")
        return redirect("profile_edit")

    mem = _user_org_membership(request.user)

    if request.method == "POST":
        form = OrganRequestForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.created_by = request.user
            obj.status = "UNDER_REVIEW"

            # If org staff creates it, bind to their org (helps verification routing; doesn’t remove anything)
            if mem:
                obj.target_organization = mem.organization

            obj.save()

            # - notify org reviewers
            if obj.target_organization_id:
                _notify_org_members(
                    obj.target_organization,
                    "New organ request pending verification",
                    f"Request #{obj.id} needs verification ({obj.get_organ_needed_display()}).",
                    url="/organ/portal/",
                    level="INFO",
                )
            else:
                _notify_orgs_in_city(
                    obj.city,
                    "New organ request pending verification",
                    f"Request #{obj.id} needs verification ({obj.get_organ_needed_display()}).",
                    url="/organ/portal/",
                    level="INFO",
                )

            messages.success(request, "Organ request submitted. Upload medical documents for verification.")
            return redirect("organ_request_detail", request_id=obj.id)
        messages.error(request, "Please fix the errors.")
    else:
        form = OrganRequestForm(initial={
            "patient_name": (request.user.get_full_name() or request.user.username),
        })

    return render(request, "organ/request_create.html", {"form": form})


@login_required
def organ_request_list(request):
    items = OrganRequest.objects.filter(created_by=request.user).order_by("-created_at")
    return render(request, "organ/request_list.html", {"items": items})


@login_required
def organ_request_detail(request, request_id):
    obj = get_object_or_404(OrganRequest, id=request_id)

    doc_form = OrganRequestDocumentForm()

    # defaults (safe)
    back_url = "/"
    back_label = "Back"

    # Owner view
    if obj.created_by_id == request.user.id:
        back_url = "/organ/my/requests/"
        back_label = "Back to My Requests"
        return render(request, "organ/request_detail.html", {
            "obj": obj,
            "doc_form": doc_form,
            "back_url": back_url,
            "back_label": back_label,
        })

    # Staff / hospital admin can view
    if request.user.is_staff or getattr(request.user, "is_hospital_admin", False):
        back_url = "/organ/portal/"
        back_label = "Back to Portal"
        return render(request, "organ/request_detail.html", {
            "obj": obj,
            "doc_form": doc_form,
            "back_url": back_url,
            "back_label": back_label,
        })

    # Org members in scope can view
    mem = _user_org_membership(request.user)
    if mem and _org_can_access_request(mem.organization, obj):
        back_url = "/organ/portal/"
        back_label = "Back to Portal"
        return render(request, "organ/request_detail.html", {
            "obj": obj,
            "doc_form": doc_form,
            "back_url": back_url,
            "back_label": back_label,
        })

    raise Http404()


@require_POST
@login_required
def organ_request_doc_upload(request, request_id):
    obj = get_object_or_404(OrganRequest, id=request_id)

    # allowed actors
    if request.user.is_staff or obj.created_by_id == request.user.id or getattr(request.user, "is_hospital_admin", False):
        pass
    else:
        mem = _user_org_membership(request.user)
        if not (mem and _org_can_access_request(mem.organization, obj)):
            raise Http404()

    form = OrganRequestDocumentForm(request.POST, request.FILES)
    if form.is_valid():
        doc = form.save(commit=False)
        doc.request = obj
        doc.save()
        messages.success(request, "Document uploaded.")

        # - If still pending review, notify org(s) that docs are added
        if obj.status == "UNDER_REVIEW":
            if obj.target_organization_id:
                _notify_org_members(
                    obj.target_organization,
                    "Medical document uploaded (Organ request)",
                    f"Request #{obj.id} now has new documents.",
                    url=f"/organ/request/{obj.id}/",
                    level="INFO",
                )
            else:
                _notify_orgs_in_city(
                    obj.city,
                    "Medical document uploaded (Organ request)",
                    f"Request #{obj.id} now has new documents.",
                    url=f"/organ/request/{obj.id}/",
                    level="INFO",
                )
    else:
        messages.error(request, "Please fix the errors.")
    return redirect("organ_request_detail", request_id=obj.id)


# ---------------- Org portal (serious workflow) ----------------
@org_member_required(roles=["ADMIN", "VERIFIER", "STAFF"])
def organ_portal(request):
    org = request.organization
    org_city = _norm_city(org.city)

    pending_pledges = (
        OrganPledge.objects
        .filter(status="UNDER_REVIEW")
        .select_related("donor", "donor__profile")
        .order_by("-submitted_at", "-created_at")
    )
    if org_city:
        pending_pledges = pending_pledges.filter(donor__profile__city__iexact=org.city)

    pending_requests = (
        OrganRequest.objects
        .filter(status="UNDER_REVIEW")
        .filter(Q(target_organization=org) | Q(target_organization__isnull=True, city__iexact=(org.city or "")))
        .order_by("-created_at")
    )

    active_requests = (
        OrganRequest.objects
        .filter(status__in=["ACTIVE", "MATCH_IN_PROGRESS"])
        .filter(Q(target_organization=org) | Q(target_organization__isnull=True, city__iexact=(org.city or "")))
        .order_by("-created_at")
    )

    matches = (
        OrganMatch.objects
        .filter(organization=org)
        .select_related("request", "pledge", "pledge__donor")
        .order_by("-updated_at")[:20]
    )

    return render(request, "organ/org_portal.html", {
        "org": org,
        "pending_pledges": pending_pledges[:20],
        "pending_requests": pending_requests[:20],
        "active_requests": active_requests[:20],
        "matches": matches,
    })

@require_POST
@org_member_required(roles=["ADMIN", "VERIFIER"])
def org_verify_pledge(request, pledge_id):
    org = request.organization
    pledge = get_object_or_404(OrganPledge, id=pledge_id)

    # only verify pending items
    if pledge.status != "UNDER_REVIEW":
        messages.info(request, "This pledge is not pending verification.")
        return redirect("organ_portal")

    # city-scoped if org.city exists, else global fallback
    if not _org_can_verify_pledge(org, pledge):
        raise Http404()

    action = (request.POST.get("action") or "").strip()

    if action == "approve":
        old_status = pledge.status

        pledge.status = "VERIFIED"
        pledge.verified_by = request.user
        pledge.verified_by_org = org
        pledge.verified_at = timezone.now()
        pledge.rejection_reason = ""
        pledge.save(update_fields=["status", "verified_by", "verified_by_org", "verified_at", "rejection_reason"])

        # award points only when transitioning into VERIFIED
        if old_status != "VERIFIED":
            try:
                from django.apps import apps
                from django.db.models import F
                Profile = apps.get_model("accounts", "UserProfile")
                Profile.objects.filter(user_id=pledge.donor_id).update(points=F("points") + 150)
            except Exception:
                pass

        _notify_user(
            pledge.donor,
            "Organ pledge verified",
            f"{org.name} verified your organ pledge.",
            url=f"/organ/pledge/{pledge.id}/",
            level="SUCCESS",
        )

        messages.success(request, "Pledge verified.")
        return redirect("organ_portal")

    if action == "reject":
        reason = (request.POST.get("reason") or "").strip()
        pledge.status = "REJECTED"
        pledge.verified_by = request.user
        pledge.verified_by_org = org
        pledge.verified_at = timezone.now()
        pledge.rejection_reason = reason or "Rejected by institution."
        pledge.save(update_fields=["status", "verified_by", "verified_by_org", "verified_at", "rejection_reason"])

        _notify_user(
            pledge.donor,
            "Organ pledge rejected",
            pledge.rejection_reason,
            url=f"/organ/pledge/{pledge.id}/",
            level="DANGER",
        )
        messages.error(request, "Pledge rejected.")
        return redirect("organ_portal")

    messages.error(request, "Invalid action.")
    return redirect("organ_portal")


@org_member_required(roles=["ADMIN", "VERIFIER", "STAFF"])
def org_pledge_detail(request, pledge_id):
    """
    Org-side pledge review page (so verifiers can view donor pledge + documents).
    This avoids the donor-only restriction of pledge_detail().
    """
    org = request.organization

    pledge = get_object_or_404(
        OrganPledge.objects
        .select_related("donor", "donor__profile")
        .prefetch_related("documents"),
        id=pledge_id
    )

    # scope check same as verification (only show if org can verify, else 404)
    if not _org_can_verify_pledge(org, pledge):
        raise Http404()

    return render(request, "organ/org_pledge_detail.html", {
        "org": org,
        "pledge": pledge,
    })


@require_POST
@org_member_required(roles=["ADMIN", "VERIFIER"])
def org_verify_organ_request(request, request_id):
    org = request.organization
    obj = get_object_or_404(OrganRequest, id=request_id)

    if obj.status != "UNDER_REVIEW":
        messages.info(request, "This request is not pending verification.")
        return redirect("organ_portal")

    if not _org_can_access_request(org, obj):
        raise Http404()

    action = (request.POST.get("action") or "").strip()

    if obj.target_organization_id is None:
        obj.target_organization = org

    if action == "approve":
        obj.status = "ACTIVE"
        obj.verified_by = request.user
        obj.verified_by_org = org
        obj.verified_at = timezone.now()
        obj.rejection_reason = ""
        obj.save(update_fields=["status", "verified_by", "verified_by_org", "verified_at", "rejection_reason", "target_organization"])

        if obj.created_by_id:
            _notify_user(
                obj.created_by,
                "Organ request activated",
                f"{org.name} verified and activated your request.",
                url=f"/organ/request/{obj.id}/",
                level="SUCCESS",
            )

        # - org internal notification
        _notify_org_members(
            org,
            "Organ request approved",
            f"Request #{obj.id} approved by {request.user.username}.",
            url="/organ/portal/",
            level="SUCCESS",
        )

        messages.success(request, "Request verified and activated.")
        return redirect("organ_portal")

    if action == "reject":
        reason = (request.POST.get("reason") or "").strip()
        obj.status = "REJECTED"
        obj.verified_by = request.user
        obj.verified_by_org = org
        obj.verified_at = timezone.now()
        obj.rejection_reason = reason or "Rejected by institution."
        obj.save(update_fields=["status", "verified_by", "verified_by_org", "verified_at", "rejection_reason", "target_organization"])

        if obj.created_by_id:
            _notify_user(
                obj.created_by,
                "Organ request rejected",
                obj.rejection_reason,
                url=f"/organ/request/{obj.id}/",
                level="DANGER",
            )

        # - org internal notification
        _notify_org_members(
            org,
            "Organ request rejected",
            f"Request #{obj.id} rejected by {request.user.username}.",
            url="/organ/portal/",
            level="WARNING",
        )

        messages.error(request, "Request rejected.")
        return redirect("organ_portal")

    messages.error(request, "Invalid action.")
    return redirect("organ_portal")


@org_member_required(roles=["ADMIN", "VERIFIER", "STAFF"])
def org_match_create(request, request_id):
    org = request.organization
    req = get_object_or_404(OrganRequest, id=request_id)

    # scope-check (prevents matching foreign requests via URL)
    if not _org_can_access_request(org, req):
        raise Http404()

    if req.status not in ("ACTIVE", "MATCH_IN_PROGRESS"):
        messages.error(request, "This request is not active for matching.")
        return redirect("organ_portal")

    # Base queryset (NO JSON contains here)
    base_qs = (
        OrganPledge.objects
        .filter(status="VERIFIED", pledge_type__in=["LIVING", "DECEASED"])
        .select_related("donor", "donor__profile")
        .order_by("-verified_at", "-created_at")
    )

    # city-scope pledges if org has a city, else global fallback
    if _norm_city(org.city):
        base_qs = base_qs.filter(donor__profile__city__iexact=org.city)

    # Organ-needed filter:
    # Try DB JSON contains (works on Postgres)
    # Fallback to Python filtering (needed on SQLite)
    try:
        pledges_qs = base_qs.filter(organs__contains=[req.organ_needed])
        pledges_count = pledges_qs.count()
    except NotSupportedError:
        ids = []
        for p in base_qs:  # using base_qs not the contains filter
            organs = p.organs or []
            if req.organ_needed in organs:
                ids.append(p.id)

        pledges_qs = (
            OrganPledge.objects
            .filter(id__in=ids)
            .select_related("donor", "donor__profile")
            .order_by("-verified_at", "-created_at")
        )
        pledges_count = len(ids)

    form = OrganMatchCreateForm(request.POST or None)
    form.fields["pledge"].queryset = pledges_qs

    if request.method == "POST" and form.is_valid():
        match = form.save(commit=False)
        match.request = req
        match.organization = org
        match.updated_by = request.user
        match.status = "PROPOSED"

        try:
            match.save()
        except IntegrityError:
            messages.info(request, "A match already exists for this pledge and request.")
            return redirect("organ_portal")

        if req.status == "ACTIVE":
            req.status = "MATCH_IN_PROGRESS"
            req.save(update_fields=["status"])

        # notify recipient + donor 
        if req.created_by_id:
            _notify_user(
                req.created_by,
                "Organ match proposed",
                f"{org.name} proposed a donor match for your request.",
                url=f"/organ/request/{req.id}/",
                level="INFO",
            )
        _notify_user(
            match.pledge.donor,
            "Organ match proposed",
            f"{org.name} proposed a match based on your verified pledge.",
            url=f"/organ/pledge/{match.pledge.id}/",
            level="INFO",
        )

        try:
            _notify_org_members(
                org,
                "Organ match created",
                f"Match #{match.id} created for Request #{req.id}.",
                url=f"/organ/portal/matches/{match.id}/update/",
                level="SUCCESS",
            )
        except Exception:
            pass

        messages.success(request, "Match created.")
        return redirect("organ_portal")

    return render(request, "organ/organ_match_create.html", {
        "org": org,
        "req": req,
        "form": form,
        "pledges_count": pledges_count,
    })

@org_member_required(roles=["ADMIN", "VERIFIER", "STAFF"])
def org_match_update(request, match_id):
    org = request.organization
    match = get_object_or_404(OrganMatch, id=match_id, organization=org)

    old_status = match.status

    form = OrganMatchStatusForm(request.POST or None, instance=match)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.updated_by = request.user
        obj.save()

        new_status = obj.status
        status_txt = obj.get_status_display()
        notes_txt = (obj.notes or "").strip()

 
        # Keep OrganRequest status in sync based on match status
        req = obj.request

        # statuses that mean "matching still ongoing"
        ONGOING = {"PROPOSED", "CONTACTED", "SCREENING", "APPROVED"}

        # Do not override closed/cancelled/rejected requests
        if req.status not in ("CLOSED", "CANCELLED", "REJECTED", "EXPIRED"):
            if new_status == "COMPLETED":
                # When match completes, close the request
                req.status = "CLOSED"
                req.save(update_fields=["status"])

            elif new_status in ("FAILED", "CANCELLED"):
                # If this match failed/cancelled and there are NO other ongoing matches,
                # revert request back to ACTIVE (so org can create another match)
                other_ongoing_exists = (
                    req.matches
                    .exclude(id=obj.id)
                    .filter(status__in=list(ONGOING))
                    .exists()
                )
                if not other_ongoing_exists and req.status == "MATCH_IN_PROGRESS":
                    req.status = "ACTIVE"
                    req.save(update_fields=["status"])

            else:
                # any ongoing match status should push request to MATCH_IN_PROGRESS
                if new_status in ONGOING and req.status == "ACTIVE":
                    req.status = "MATCH_IN_PROGRESS"
                    req.save(update_fields=["status"])

    # notes
        extra = ""
        if notes_txt:
            short_notes = notes_txt if len(notes_txt) <= 220 else (notes_txt[:220] + "…")
            extra = f"\nReason/Notes: {short_notes}"

        # notify requester
        if req.created_by_id:
            _notify_user(
                req.created_by,
                "Match update",
                f"Match #{obj.id} status updated: {status_txt}.{extra}",
                url=f"/organ/request/{req.id}/",
                level="INFO",
            )

        # notify donor
        _notify_user(
            obj.pledge.donor,
            "Match update",
            f"Match #{obj.id} status updated: {status_txt}.{extra}",
            url=f"/organ/pledge/{obj.pledge.id}/",
            level="INFO",
        )

        # notify org members (internal tracking)
        try:
            _notify_org_members(
                org,
                "Match update",
                f"Match #{obj.id} status updated: {status_txt}.{extra}",
                url=f"/organ/portal/matches/{obj.id}/update/",
                level="INFO",
            )
        except Exception:
            pass

        # message
        if old_status != new_status:
            messages.success(request, "Match updated.")
        else:
            messages.success(request, "Saved (no status change).")

        return redirect("organ_portal")

    return render(request, "organ/organ_match_update.html", {"org": org, "match": match, "form": form})