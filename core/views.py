from django.shortcuts import render
from django.shortcuts import render, get_object_or_404
from blood.models import PublicBloodRequest, BloodDonation
from hospitals.models import BloodCampaign
from .models import TeamMember, GalleryImage

def about(request):
    stats = {
        "active_requests": PublicBloodRequest.objects.filter(is_active=True, status__in=["OPEN", "IN_PROGRESS"]).count(),
        "verified_donations": BloodDonation.objects.filter(status="VERIFIED").count(),
        "upcoming_camps": BloodCampaign.objects.filter(status__in=["UPCOMING", "ONGOING"]).count(),
    }

    team = TeamMember.objects.filter(is_active=True).order_by("order")
    gallery = GalleryImage.objects.filter(is_active=True).order_by("order")[:12]

    return render(request, "core/about.html", {
        "stats": stats,
        "team": team,
        "gallery": gallery,
    })

def gallery_list(request):
    items = GalleryImage.objects.filter(is_active=True).order_by("order", "-event_date", "-created_at")
    return render(request, "core/gallery_list.html", {"items": items})

def gallery_detail(request, pk):
    item = get_object_or_404(GalleryImage, pk=pk, is_active=True)
    return render(request, "core/gallery_detail.html", {"item": item})