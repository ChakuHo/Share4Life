import os
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from accounts.permissions import donor_required, recipient_required
from communication.models import Notification

from .models import PublicBloodRequest, GuestResponse, DonorResponse, BloodDonation, DonationMedicalReport
from .forms import (
    EmergencyRequestForm, GuestResponseForm,
    RecipientRequestForm, DonorResponseForm,
    DonationCreateForm, DonationReportForm
)
from .eligibility import is_eligible, next_eligible_datetime
from hospitals.models import BloodCampaign

from accounts.models import CustomUser
from communication.services import broadcast_after_commit


def _notify_user(user, title, body="", url="", level="INFO"):
    if not user:
        return
    Notification.objects.create(user=user, title=title, body=body, url=url, level=level)


# Guest emergency request
def emergency_request_view(request):
    if request.method == 'POST':
        form = EmergencyRequestForm(request.POST, request.FILES) 
        if form.is_valid():
            obj = form.save(commit=False)
            obj.created_by = None
            obj.verification_status = "UNVERIFIED"   # guest stays unverified
            obj.status = "OPEN"
            obj.is_active = True
            obj.save()
            messages.success(request, "Emergency posted (Unverified). Proof is attached for donors to view.")
            return redirect('public_dashboard')
    else:
        form = EmergencyRequestForm()

    return render(request, 'blood/emergency_form.html', {'form': form})


# Logged-in recipient request
@login_required
@recipient_required
def recipient_request_view(request):
    require_proof = not request.user.is_verified  # KYC verified => no proof required

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

            # If emergency, broadcast notification + email to all active users
            if obj.is_emergency:
                users_qs = CustomUser.objects.filter(is_active=True)

                title = "URGENT Blood Request"
                url = f"/blood/request/{obj.id}/"
                abs_url = request.build_absolute_uri(url)

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
        form = RecipientRequestForm(require_proof=require_proof)

    return render(request, "blood/recipient_request.html", {
        "form": form,
        "require_proof": require_proof,
    })


# Public feed - show all active, but label verification
def public_dashboard_view(request):
    requests = PublicBloodRequest.objects.filter(is_active=True).order_by('-is_emergency', '-created_at')
    return render(request, 'blood/public_dashboard.html', {'requests': requests})


# Request detail - public
def request_detail_view(request, request_id):
    blood_req = get_object_or_404(PublicBloodRequest, id=request_id)

    guest_responses = blood_req.responses.order_by("-responded_at")
    donor_responses = blood_req.donor_responses.select_related("donor").order_by("-created_at")
    donations = blood_req.donations.select_related("donor_user").order_by("-donated_at")

    eligible_info = None
    if request.user.is_authenticated and getattr(request.user, "is_donor", False):
        eligible_info = {"eligible": is_eligible(request.user), "next_date": next_eligible_datetime(request.user)}

    return render(request, "blood/request_detail.html", {
        "req": blood_req,
        "guest_responses": guest_responses,
        "donor_responses": donor_responses,
        "donations": donations,
        "eligible_info": eligible_info,
    })


# Guest donate and notify recipient if possible
def guest_donate_view(request, request_id):
    blood_req = get_object_or_404(PublicBloodRequest, id=request_id)

    if request.method == 'POST':
        form = GuestResponseForm(request.POST)
        if form.is_valid():
            response = form.save(commit=False)
            response.request = blood_req
            response.save()

            # workflow update
            if blood_req.status == "OPEN":
                blood_req.status = "IN_PROGRESS"
                blood_req.save(update_fields=["status"])

            # notify logged-in requester if exists
            if blood_req.created_by_id:
                _notify_user(
                    blood_req.created_by,
                    "A guest donor is coming",
                    f"{response.donor_name} ({response.donor_phone}) responded to your request.",
                    url=f"/blood/request/{blood_req.id}/",
                    level="SUCCESS",
                )

            messages.success(request, "Thank you! The patient has been notified that you are coming.")
            return redirect('public_dashboard')
    else:
        form = GuestResponseForm()

    return render(request, 'blood/guest_response.html', {'form': form, 'req': blood_req})


# Registered donor respond
@login_required
@donor_required
def donor_respond_view(request, request_id):
    blood_req = get_object_or_404(PublicBloodRequest, id=request_id)

    if blood_req.status in ("FULFILLED", "CANCELLED") or not blood_req.is_active:
        messages.error(request, "This request is closed.")
        return redirect("blood_request_detail", request_id=blood_req.id)

    if not is_eligible(request.user):
        nxt = next_eligible_datetime(request.user)
        messages.error(request, f"You are not eligible yet. Eligible again on: {nxt.date() if nxt else 'N/A'}")
        return redirect("blood_request_detail", request_id=blood_req.id)

    obj, _ = DonorResponse.objects.get_or_create(request=blood_req, donor=request.user)

    if request.method == "POST":
        form = DonorResponseForm(request.POST, instance=obj)
        if form.is_valid():
            resp = form.save(commit=False)
            resp.responded_at = timezone.now()
            resp.save()

            if resp.status == "ACCEPTED" and blood_req.status == "OPEN":
                blood_req.status = "IN_PROGRESS"
                blood_req.save(update_fields=["status"])

            # notify requester if exists
            if blood_req.created_by_id:
                _notify_user(
                    blood_req.created_by,
                    "A donor responded to your request",
                    f"Donor {request.user.username} responded: {resp.status}.",
                    url=f"/blood/request/{blood_req.id}/",
                    level="INFO",
                )

            messages.success(request, "Response submitted.")
            return redirect("blood_request_detail", request_id=blood_req.id)
    else:
        form = DonorResponseForm(instance=obj)

    return render(request, "blood/donor_respond.html", {"form": form, "req": blood_req})


# Donor marks donation completed (creates donation history)
@login_required
@donor_required
def donation_create_view(request, request_id):
    blood_req = get_object_or_404(PublicBloodRequest, id=request_id)

    if not is_eligible(request.user):
        nxt = next_eligible_datetime(request.user)
        messages.error(request, f"You are not eligible yet. Eligible again on: {nxt.date() if nxt else 'N/A'}")
        return redirect("blood_request_detail", request_id=blood_req.id)

    existing = BloodDonation.objects.filter(request=blood_req, donor_user=request.user).first()
    if existing:
        messages.info(request, "You already recorded a donation for this request.")
        return redirect("donor_history") 

    if request.method == "POST":
        form = DonationCreateForm(request.POST)
        if form.is_valid():
            d = form.save(commit=False)
            d.request = blood_req
            d.donor_user = request.user
            d.blood_group = request.user.profile.blood_group or ""
            d.status = "COMPLETED"
            d.save()

            if blood_req.created_by_id:
                _notify_user(
                    blood_req.created_by,
                    "Donation marked completed",
                    f"Donor {request.user.username} marked donation completed. Awaiting verification.",
                    url=f"/blood/request/{blood_req.id}/",
                    level="SUCCESS",
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

    action = request.POST.get("action")
    if request.method == "POST":
        if action == "approve":
            req.verification_status = "VERIFIED"
            req.verified_by = request.user
            req.verified_at = timezone.now()
            req.rejection_reason = ""
            req.save(update_fields=["verification_status", "verified_by", "verified_at", "rejection_reason"])
            if req.created_by_id:
                _notify_user(req.created_by, "Request verified", "Your blood request has been verified.", url=f"/blood/request/{req.id}/", level="SUCCESS")
            messages.success(request, "Request verified.")
        elif action == "reject":
            reason = (request.POST.get("reason") or "").strip()
            req.verification_status = "REJECTED"
            req.verified_by = request.user
            req.verified_at = timezone.now()
            req.rejection_reason = reason or "Rejected by hospital/admin."
            req.save(update_fields=["verification_status", "verified_by", "verified_at", "rejection_reason"])
            if req.created_by_id:
                _notify_user(req.created_by, "Request rejected", req.rejection_reason, url=f"/blood/request/{req.id}/", level="DANGER")
            messages.error(request, "Request rejected.")
        return redirect("blood_request_detail", request_id=req.id)

    raise Http404()

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