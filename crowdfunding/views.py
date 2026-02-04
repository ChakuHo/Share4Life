from datetime import timedelta
import uuid, base64, hmac, hashlib, json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.db import transaction

from .models import (
    Campaign, CampaignDocument, Donation, Disbursement,
    CampaignAuditLog, CampaignReport
)
from .forms import CampaignCreateForm, DonationForm, DisbursementForm, CampaignReportForm
from .services import notify_user, khalti_initiate, khalti_lookup
from django.db.models import Sum


def _auto_update_campaign(camp: Campaign):
    camp.refresh_raised_amount()

    before = camp.status
    camp.mark_completed_if_needed()
    if before != camp.status and camp.status == "COMPLETED":
        CampaignAuditLog.objects.create(
            campaign=camp, actor=None, action="COMPLETED", message="Target reached"
        )

    if camp.status == "COMPLETED" and camp.completed_at:
        days = int(getattr(settings, "CAMPAIGN_ARCHIVE_AFTER_DAYS", 1))
        if timezone.now() >= camp.completed_at + timedelta(days=days):
            camp.mark_archived()
            CampaignAuditLog.objects.create(
                campaign=camp, actor=None, action="ARCHIVED", message="Auto archived"
            )


def _make_esewa_signature(total_amount: int, transaction_uuid: str) -> str:
    """
    eSewa RC-EPAY v2 signature (same as your teacher)
    """
    msg = f"total_amount={total_amount},transaction_uuid={transaction_uuid},product_code={settings.ESEWA_PRODUCT_CODE}"
    mac = hmac.new(
        settings.ESEWA_SECRET_KEY.encode("utf-8"),
        msg=msg.encode("utf-8"),
        digestmod=hashlib.sha256
    ).digest()
    return base64.b64encode(mac).decode("utf-8")


def campaign_list(request):
    qs = Campaign.objects.exclude(status="ARCHIVED").filter(status__in=["APPROVED", "COMPLETED"]).order_by(
        "-is_featured", "-created_at"
    )

    items = list(qs[:60])
    for c in items:
        _auto_update_campaign(c)

    qs = Campaign.objects.exclude(status="ARCHIVED").filter(status__in=["APPROVED", "COMPLETED"]).order_by(
        "-is_featured", "-created_at"
    )
    return render(request, "crowdfunding/campaign_list.html", {"items": qs})


def campaign_detail(request, pk):
    camp = get_object_or_404(Campaign, pk=pk)

    if camp.status not in ("APPROVED", "COMPLETED"):
        if not (request.user.is_authenticated and (request.user.is_staff or camp.owner_id == request.user.id)):
            raise Http404()

    _auto_update_campaign(camp)

    donation_form = DonationForm(user=request.user)
    report_form = CampaignReportForm(user=request.user)

    return render(request, "crowdfunding/campaign_detail.html", {
        "camp": camp,
        "donation_form": donation_form,
        "report_form": report_form,
        "raised_total": camp.raised_total(),
        "pct": camp.get_percentage(),
        "donor_count": camp.donations.filter(status="SUCCESS").count(),
        "documents": camp.documents.order_by("-uploaded_at"),
        "disbursements": camp.disbursements.order_by("-released_at"),
        "available_balance": camp.available_balance(),
        "open_reports_count": camp.reports.filter(status="OPEN").count(),
    })


@login_required
def campaign_create(request):
    if not (request.user.is_staff or request.user.is_verified):
        messages.error(request, "You must be KYC verified to create a campaign.")
        return redirect("kyc_submit")

    if request.method == "POST":
        form = CampaignCreateForm(request.POST, request.FILES)
        if form.is_valid():
            with transaction.atomic():
                camp = form.save(commit=False)
                camp.owner = request.user

                if request.user.is_staff:
                    camp.status = "APPROVED"
                    camp.approved_by = request.user
                    camp.approved_at = timezone.now()
                else:
                    camp.status = "PENDING"

                camp.save()

                CampaignDocument.objects.create(
                    campaign=camp,
                    doc_type=form.cleaned_data["proof_type"],
                    file=form.cleaned_data["proof_file"],
                    note="Proof uploaded at creation",
                    uploaded_by=request.user,
                )

                CampaignAuditLog.objects.create(
                    campaign=camp, actor=request.user, action="CREATED", message="Campaign created"
                )

                if camp.status == "PENDING":
                    CampaignAuditLog.objects.create(
                        campaign=camp, actor=request.user, action="SUBMITTED", message="Submitted for review"
                    )
                    notify_user(
                        request.user,
                        "Campaign submitted for review",
                        "Your campaign is pending admin approval.",
                        url=camp.get_absolute_url(),
                        level="INFO",
                        email_subject="Share4Life - Campaign Pending Review",
                        email_body=f"Your campaign '{camp.title}' has been submitted and is pending approval.",
                    )

            messages.success(request, "Campaign created.")
            return redirect("campaign_detail", pk=camp.id)

        messages.error(request, "Fix errors and try again.")
    else:
        form = CampaignCreateForm()

    return render(request, "crowdfunding/campaign_create.html", {"form": form})


@require_POST
def donate_start(request, pk):
    camp = get_object_or_404(Campaign, pk=pk, status="APPROVED")
    _auto_update_campaign(camp)

    if camp.is_expired():
        messages.error(request, "Campaign deadline has passed.")
        return redirect("campaign_detail", pk=camp.id)

    if camp.should_complete():
        messages.info(request, "This campaign has reached its target.")
        return redirect("campaign_detail", pk=camp.id)

    form = DonationForm(request.POST, user=request.user)
    if not form.is_valid():
        messages.error(request, "Please fix the donation form.")
        return redirect("campaign_detail", pk=camp.id)

    with transaction.atomic():
        donation = form.save(commit=False)
        donation.campaign = camp
        donation.status = "INITIATED"
        if request.user.is_authenticated:
            donation.donor_user = request.user
        donation.save()

        CampaignAuditLog.objects.create(
            campaign=camp,
            actor=donation.donor_user,
            action="DONATION_INITIATED",
            message=f"{donation.gateway} Rs.{donation.amount}",
        )

    # ---------- KHALTI ----------
    if donation.gateway == "KHALTI":
        try:
            return_url = request.build_absolute_uri(reverse("khalti_return", args=[donation.id]))
            customer_info = {
                "name": donation.donor_display(),
                "email": donation.guest_email or (donation.donor_user.email if donation.donor_user_id else ""),
                "phone": donation.guest_phone or (donation.donor_user.phone_number if donation.donor_user_id else ""),
            }

            data = khalti_initiate(
                amount_npr=float(donation.amount),
                purchase_order_id=donation.id,
                purchase_order_name=camp.title,
                return_url=return_url,
                customer_info=customer_info,
            )

            donation.pidx = data.get("pidx", "")
            donation.payment_url = data.get("payment_url", "")
            donation.raw_response = {**(donation.raw_response or {}), "khalti_initiate": data}
            donation.save(update_fields=["pidx", "payment_url", "raw_response"])

            if not donation.payment_url:
                raise RuntimeError("Missing payment_url from Khalti")

            return redirect(donation.payment_url)

        except Exception as e:
            donation.status = "FAILED"
            donation.raw_response = {**(donation.raw_response or {}), "khalti_error": str(e)}
            donation.save(update_fields=["status", "raw_response"])
            CampaignAuditLog.objects.create(
                campaign=camp, actor=donation.donor_user, action="DONATION_FAILED", message=str(e)
            )
            messages.error(request, f"Khalti initiate failed: {e}")
            return redirect("campaign_detail", pk=camp.id)

    # ---------- ESEWA RC-EPAY v2 (teacher style) ----------
    if donation.gateway == "ESEWA":
        try:
            total_amount = int(round(float(donation.amount)))
            if total_amount <= 0:
                raise RuntimeError("Invalid donation amount")

            txn_uuid = f"C{camp.id}-D{donation.id}-{uuid.uuid4().hex[:8]}"
            signature = _make_esewa_signature(total_amount, txn_uuid)

            # requires these fields in Donation model; if missing you must add and migrate
            donation.esewa_transaction_uuid = txn_uuid
            donation.save(update_fields=["esewa_transaction_uuid"])

            return_url = request.build_absolute_uri(reverse("esewa_return", args=[donation.id]))

            form_data = {
                "amount": total_amount,
                "tax_amount": 0,
                "total_amount": total_amount,
                "transaction_uuid": txn_uuid,
                "product_code": settings.ESEWA_PRODUCT_CODE,
                "product_service_charge": 0,
                "product_delivery_charge": 0,
                "success_url": return_url,
                "failure_url": return_url,
                "signed_field_names": "total_amount,transaction_uuid,product_code",
                "signature": signature,
            }

            donation.raw_response = {**(donation.raw_response or {}), "esewa_form": form_data}
            donation.save(update_fields=["raw_response"])

            return render(request, "crowdfunding/esewa_redirect.html", {
                "ESEWA_FORM_URL": settings.ESEWA_FORM_URL,
                "form": form_data,
                "camp": camp,
                "donation": donation,
            })

        except Exception as e:
            donation.status = "FAILED"
            donation.raw_response = {**(donation.raw_response or {}), "esewa_error": str(e)}
            donation.save(update_fields=["status", "raw_response"])
            CampaignAuditLog.objects.create(
                campaign=camp, actor=donation.donor_user, action="DONATION_FAILED",
                message=f"eSewa start error: {e}"
            )
            messages.error(request, f"eSewa initiate failed: {e}")
            return redirect("campaign_detail", pk=camp.id)

    messages.error(request, "Unsupported gateway.")
    return redirect("campaign_detail", pk=camp.id)


def khalti_return(request, donation_id):
    donation = get_object_or_404(Donation.objects.select_related("campaign", "donor_user"), pk=donation_id)
    camp = donation.campaign

    pidx = (request.GET.get("pidx") or donation.pidx or "").strip()
    if not pidx:
        donation.status = "FAILED"
        donation.raw_response = {**(donation.raw_response or {}), "khalti_error": "Missing pidx"}
        donation.save(update_fields=["status", "raw_response"])
        CampaignAuditLog.objects.create(campaign=camp, actor=donation.donor_user, action="DONATION_FAILED", message="Missing pidx")
        messages.error(request, "Payment verification failed.")
        return redirect("campaign_detail", pk=camp.id)

    try:
        data = khalti_lookup(pidx)
        donation.raw_response = {**(donation.raw_response or {}), "khalti_lookup": data}

        status_txt = (data.get("status") or "").lower()
        if status_txt in ("completed", "complete", "success"):
            if donation.status != "SUCCESS":
                donation.status = "SUCCESS"
                donation.verified_at = timezone.now()
                donation.gateway_ref = data.get("transaction_id") or data.get("idx") or pidx
                donation.save(update_fields=["status", "verified_at", "gateway_ref", "raw_response"])

                camp.refresh_raised_amount()
                camp.mark_completed_if_needed()

                CampaignAuditLog.objects.create(
                    campaign=camp, actor=donation.donor_user, action="DONATION_SUCCESS",
                    message=f"Khalti Rs.{donation.amount}"
                )

                if camp.owner_id:
                    notify_user(
                        camp.owner,
                        "New donation received",
                        f"Rs. {donation.amount} received via Khalti from {donation.donor_display()}",
                        url=camp.get_absolute_url(),
                        level="SUCCESS",
                        email_subject="Share4Life - New Donation Received",
                        email_body=f"Your campaign '{camp.title}' received Rs. {donation.amount}.",
                    )

            messages.success(request, "Payment successful. Thank you for donating.")
        else:
            donation.status = "FAILED"
            donation.save(update_fields=["status", "raw_response"])
            CampaignAuditLog.objects.create(
                campaign=camp, actor=donation.donor_user, action="DONATION_FAILED",
                message=f"Khalti status: {data.get('status')}"
            )
            messages.error(request, "Payment not completed.")

    except Exception as e:
        donation.status = "FAILED"
        donation.raw_response = {**(donation.raw_response or {}), "khalti_error": str(e)}
        donation.save(update_fields=["status", "raw_response"])
        CampaignAuditLog.objects.create(campaign=camp, actor=donation.donor_user, action="DONATION_FAILED", message=str(e))
        messages.error(request, f"Verification error: {e}")

    return redirect("campaign_detail", pk=camp.id)


def esewa_return(request, donation_id):
    donation = get_object_or_404(Donation.objects.select_related("campaign", "donor_user"), pk=donation_id)
    camp = donation.campaign

    encoded = (
        request.GET.get("data") or request.POST.get("data")
        or request.GET.get("response") or request.POST.get("response")
    )

    payload = {}
    status = ""
    txn_code = ""

    if encoded:
        try:
            payload = json.loads(base64.b64decode(encoded).decode("utf-8"))
            status = str(payload.get("status", "")).upper()
            txn_code = payload.get("transaction_code", "") or payload.get("transactionCode", "")
        except Exception as e:
            payload = {"decode_error": str(e), "raw": encoded}

    donation.raw_response = {**(donation.raw_response or {}), "esewa_return": payload}
    donation.save(update_fields=["raw_response"])

    if status == "COMPLETE":
        if donation.status != "SUCCESS":
            donation.status = "SUCCESS"
            donation.verified_at = timezone.now()
            donation.esewa_transaction_code = txn_code
            donation.gateway_ref = txn_code or donation.gateway_ref
            donation.save(update_fields=["status", "verified_at", "esewa_transaction_code", "gateway_ref", "raw_response"])

            camp.refresh_raised_amount()
            camp.mark_completed_if_needed()

            CampaignAuditLog.objects.create(
                campaign=camp, actor=donation.donor_user, action="DONATION_SUCCESS",
                message=f"eSewa success Rs.{donation.amount} txn={txn_code}"
            )

            if camp.owner_id:
                notify_user(
                    camp.owner,
                    "New donation received",
                    f"Rs. {donation.amount} received via eSewa from {donation.donor_display()}",
                    url=camp.get_absolute_url(),
                    level="SUCCESS",
                    email_subject="Share4Life - New Donation Received",
                    email_body=f"Your campaign '{camp.title}' received Rs. {donation.amount} via eSewa.",
                )

        messages.success(request, "eSewa payment successful. Thank you for donating.")
        return redirect("campaign_detail", pk=camp.id)

    # failed/cancelled
    if donation.status != "SUCCESS":
        donation.status = "FAILED"
        donation.save(update_fields=["status", "raw_response"])
        CampaignAuditLog.objects.create(
            campaign=camp, actor=donation.donor_user, action="DONATION_FAILED",
            message=f"eSewa status={status or 'UNKNOWN'}"
        )
    messages.error(request, "eSewa payment was not completed.")
    return redirect("campaign_detail", pk=camp.id)


# Backward compatible stubs (in case you still have old URLs/templates somewhere)
def esewa_success(request, donation_id):
    messages.info(request, "This endpoint is deprecated. Please use the eSewa return flow.")
    return redirect("campaign_detail", pk=get_object_or_404(Donation, pk=donation_id).campaign_id)

def esewa_failure(request, donation_id):
    messages.error(request, "eSewa payment failed or was cancelled.")
    return redirect("campaign_detail", pk=get_object_or_404(Donation, pk=donation_id).campaign_id)


@login_required
def disburse_create(request, pk):
    if not request.user.is_staff:
        raise Http404()

    camp = get_object_or_404(Campaign, pk=pk)

    if request.method == "POST":
        form = DisbursementForm(request.POST, request.FILES)
        if form.is_valid():
            dis = form.save(commit=False)
            dis.campaign = camp
            dis.released_by = request.user

            if dis.amount > camp.available_balance():
                messages.error(request, f"Disbursement exceeds available balance. Available: Rs. {camp.available_balance()}")
                return redirect("disburse_create", pk=camp.id)

            dis.save()
            CampaignAuditLog.objects.create(campaign=camp, actor=request.user, action="DISBURSED", message=f"Rs.{dis.amount}")

            if camp.owner_id:
                notify_user(
                    camp.owner,
                    "Disbursement proof uploaded",
                    f"Rs. {dis.amount} was released for hospital payment. Proof is public on the campaign page.",
                    url=camp.get_absolute_url(),
                    level="INFO",
                )

            messages.success(request, "Disbursement proof saved.")
            return redirect("campaign_detail", pk=camp.id)

        messages.error(request, "Please fix the errors.")
    else:
        form = DisbursementForm()

    return render(request, "crowdfunding/disburse_create.html", {
        "camp": camp,
        "form": form,
        "available": camp.available_balance()
    })


@login_required
def my_campaigns(request):
    items = Campaign.objects.filter(owner=request.user).order_by("-created_at")
    return render(request, "crowdfunding/my_campaigns.html", {"items": items})


@require_POST
def report_campaign(request, pk):
    camp = get_object_or_404(Campaign, pk=pk)

    form = CampaignReportForm(request.POST, user=request.user)
    if not form.is_valid():
        messages.error(request, "Please fix the report form.")
        return redirect("campaign_detail", pk=camp.id)

    rep = form.save(commit=False)
    rep.campaign = camp
    if request.user.is_authenticated:
        rep.reporter_user = request.user
    rep.save()

    CampaignAuditLog.objects.create(
        campaign=camp, actor=rep.reporter_user, action="REPORTED", message=rep.reason
    )

    messages.success(request, "Report submitted. Admin will review.")
    return redirect("campaign_detail", pk=camp.id)



@login_required
def my_donations(request):
    qs = (
        Donation.objects
        .filter(donor_user=request.user)
        .select_related("campaign")
        .order_by("-created_at")
    )

    totals = qs.filter(status="SUCCESS").aggregate(
        total_amount=Sum("amount"),
    )
    total_amount = totals["total_amount"] or 0

    return render(request, "crowdfunding/my_donations.html", {
        "items": qs[:200],
        "total_amount": total_amount,
    })