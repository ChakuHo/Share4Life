from django.core.exceptions import FieldDoesNotExist
from django.shortcuts import render, get_object_or_404
from django.utils import timezone

from blood.models import PublicBloodRequest, BloodDonation
from hospitals.models import BloodCampaign
from .models import TeamMember, GalleryImage
from django.db.models import Sum, Count, Q
from crowdfunding.models import Campaign, Donation, Disbursement


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

    if _has_field(PublicBloodRequest, "status"):
        req_qs = req_qs.filter(status__in=["OPEN", "IN_PROGRESS"])

    if _has_field(PublicBloodRequest, "verification_status"):
        req_qs = req_qs.exclude(verification_status="REJECTED")

    active_requests = req_qs.count()

    # -----------------------------
    # Verified blood donations
    # -----------------------------
    don_qs = BloodDonation.objects.all()
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
    # Crowdfunding impact stats
    # -----------------------------
    total_raised = Donation.objects.filter(status="SUCCESS").aggregate(s=Sum("amount"))["s"] or 0
    total_disbursed = Disbursement.objects.aggregate(s=Sum("amount"))["s"] or 0

    # Active = can still accept donations
    active_campaigns = Campaign.objects.filter(status="APPROVED").count()

    # Completed on About = COMPLETED + ARCHIVED (because you auto-archive after 1 day)
    completed_campaigns = Campaign.objects.filter(status__in=["COMPLETED", "ARCHIVED"]).count()
    archived_campaigns = Campaign.objects.filter(status="ARCHIVED").count()

    # Pending proof: campaigns that have SUCCESS donations but no disbursement records yet
    pending_disbursement_proof = (
        Campaign.objects.filter(status__in=["APPROVED", "COMPLETED", "ARCHIVED"])
        .annotate(dcnt=Count("disbursements"))
        .filter(dcnt=0)
        .annotate(success_cnt=Count("donations", filter=Q(donations__status="SUCCESS")))
        .filter(success_cnt__gt=0)
        .count()
    )

    # Avg days to complete: include ARCHIVED too (they still have completed_at)
    completed_qs = Campaign.objects.filter(
        status__in=["COMPLETED", "ARCHIVED"],
        completed_at__isnull=False
    ).only("created_at", "completed_at")

    days_list = []
    for c in completed_qs:
        if c.created_at and c.completed_at:
            days_list.append((c.completed_at.date() - c.created_at.date()).days)
    avg_days_to_complete = round(sum(days_list) / len(days_list), 1) if days_list else None

    top_contributors = (
        Donation.objects.filter(status="SUCCESS", donor_user__isnull=False)
        .values("donor_user__username", "donor_user__first_name", "donor_user__last_name")
        .annotate(total=Sum("amount"), cnt=Count("id"))
        .order_by("-total")[:5]
    )

    # Top campaigns by raised: include ARCHIVED for transparency
    top_campaigns = (
        Campaign.objects.filter(status__in=["APPROVED", "COMPLETED", "ARCHIVED"])
        .annotate(raised=Sum("donations__amount", filter=Q(donations__status="SUCCESS")))
        .annotate(disbursed=Sum("disbursements__amount"))
        .order_by("-raised")[:5]
    )

    cf = {
        "active_campaigns": active_campaigns,
        "completed_campaigns": completed_campaigns,  # now includes archived too
        "archived_campaigns": archived_campaigns,    # extra metric (optional to show)
        "total_raised": total_raised,
        "total_disbursed": total_disbursed,
        "pending_disbursement_proof": pending_disbursement_proof,
        "avg_days_to_complete": avg_days_to_complete,
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
        "cf": cf,
        "top_contributors": top_contributors,
        "top_campaigns": top_campaigns,
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