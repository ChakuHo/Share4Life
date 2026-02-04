from django.core.exceptions import FieldDoesNotExist
from django.shortcuts import render, get_object_or_404
from django.utils import timezone

from blood.models import PublicBloodRequest, BloodDonation
from hospitals.models import BloodCampaign
from .models import TeamMember, GalleryImage


def _has_field(model, name: str) -> bool:
    try:
        model._meta.get_field(name)
        return True
    except FieldDoesNotExist:
        return False


def _safe_order(qs, *fields):
    """
    Only orders by fields that actually exist on the model.
    Always falls back to '-id' to keep deterministic ordering.
    """
    model = qs.model
    valid = []
    for f in fields:
        fname = f.lstrip("-")
        if _has_field(model, fname):
            valid.append(f)

    if not valid:
        valid = ["-id"]
    elif "-id" not in valid and "id" not in [v.lstrip("-") for v in valid]:
        valid.append("-id")

    return qs.order_by(*valid)


def about(request):
    # -----------------------------
    # Active blood requests
    # -----------------------------
    req_qs = PublicBloodRequest.objects.filter(is_active=True)

    # If your model has status (OPEN/IN_PROGRESS), use it; otherwise ignore
    if _has_field(PublicBloodRequest, "status"):
        req_qs = req_qs.filter(status__in=["OPEN", "IN_PROGRESS"])

    # If your model has verification_status, hide rejected (matches your home feed behavior)
    if _has_field(PublicBloodRequest, "verification_status"):
        req_qs = req_qs.exclude(verification_status="REJECTED")

    active_requests = req_qs.count()

    # -----------------------------
    # Verified blood donations
    # -----------------------------
    don_qs = BloodDonation.objects.all()

    # Your project sometimes uses 'verification_status' and sometimes 'status' in different models.
    # So we check safely.
    if _has_field(BloodDonation, "verification_status"):
        don_qs = don_qs.filter(verification_status="VERIFIED")
    elif _has_field(BloodDonation, "status"):
        don_qs = don_qs.filter(status="VERIFIED")

    verified_donations = don_qs.count()

    # -----------------------------
    # Upcoming / ongoing camps
    # -----------------------------
    camp_qs = BloodCampaign.objects.all()
    if _has_field(BloodCampaign, "status"):
        camp_qs = camp_qs.filter(status__in=["UPCOMING", "ONGOING"])
        upcoming_camps = camp_qs.count()
    else:
        # fallback: if status doesn't exist, try date-based logic
        if _has_field(BloodCampaign, "start_date"):
            upcoming_camps = BloodCampaign.objects.filter(start_date__gte=timezone.now().date()).count()
        else:
            upcoming_camps = BloodCampaign.objects.count()

    stats = {
        "active_requests": active_requests,
        "verified_donations": verified_donations,
        "upcoming_camps": upcoming_camps,
    }

    # -----------------------------
    # Team
    # -----------------------------
    team_qs = TeamMember.objects.all()
    if _has_field(TeamMember, "is_active"):
        team_qs = team_qs.filter(is_active=True)
    team_qs = _safe_order(team_qs, "order", "id")
    team = team_qs

    # -----------------------------
    # Gallery preview
    # -----------------------------
    gallery_qs = GalleryImage.objects.all()
    if _has_field(GalleryImage, "is_active"):
        gallery_qs = gallery_qs.filter(is_active=True)
    gallery_qs = _safe_order(gallery_qs, "order", "-event_date", "-created_at", "-id")
    gallery = gallery_qs[:12]

    return render(request, "core/about.html", {
        "stats": stats,
        "team": team,
        "gallery": gallery,
    })


def gallery_list(request):
    qs = GalleryImage.objects.all()
    if _has_field(GalleryImage, "is_active"):
        qs = qs.filter(is_active=True)

    qs = _safe_order(qs, "order", "-event_date", "-created_at", "-id")
    return render(request, "core/gallery_list.html", {"items": qs})


def gallery_detail(request, pk):
    qs = GalleryImage.objects.all()
    if _has_field(GalleryImage, "is_active"):
        qs = qs.filter(is_active=True)

    item = get_object_or_404(qs, pk=pk)
    return render(request, "core/gallery_detail.html", {"item": item})