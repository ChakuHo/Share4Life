from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify


class Campaign(models.Model):
    # EXISTING fields (kept)
    title = models.CharField(max_length=200)
    patient_name = models.CharField(max_length=100)
    description = models.TextField()
    image = models.ImageField(upload_to="campaigns/", blank=True, null=True)

    target_amount = models.DecimalField(max_digits=12, decimal_places=2)
    raised_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    is_featured = models.BooleanField(default=False, help_text="Check this to show on Home Page")
    created_at = models.DateTimeField(default=timezone.now)

    # NEW workflow fields
    STATUS = [
        ("PENDING", "Pending Review"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
        ("COMPLETED", "Completed"),
        ("ARCHIVED", "Archived"),
    ]
    status = models.CharField(max_length=12, choices=STATUS, default="APPROVED")

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="campaigns_created",
    )

    deadline = models.DateField(null=True, blank=True)  # required via form

    hospital_name = models.CharField(max_length=200, blank=True)
    hospital_city = models.CharField(max_length=100, blank=True)
    hospital_contact_phone = models.CharField(max_length=30, blank=True)

    rejection_reason = models.TextField(blank=True)

    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="campaigns_approved",
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    completed_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    slug = models.SlugField(max_length=220, blank=True, db_index=True)

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        # Canonical slug URL (still keeps legacy /campaign/<id>/ working via redirect logic in view)
        safe_slug = self.slug or (f"campaign-{self.pk}" if self.pk else "campaign")
        return reverse("campaign_detail_slug", kwargs={"pk": self.id, "slug": safe_slug})

    def raised_total(self):
        return (
            self.donations.filter(status="SUCCESS")
            .aggregate(s=Sum("amount"))["s"]
            or Decimal("0.00")
        )

    def refresh_raised_amount(self):
        self.raised_amount = self.raised_total()
        self.save(update_fields=["raised_amount"])

    def disbursed_total(self):
        return (
            self.disbursements.aggregate(s=Sum("amount"))["s"]
            or Decimal("0.00")
        )

    def available_balance(self):
        return max(self.raised_total() - self.disbursed_total(), Decimal("0.00"))

    def get_percentage(self):
        t = self.target_amount or Decimal("0.00")
        if t <= 0:
            return 0
        pct = int((self.raised_total() / t) * 100)
        return max(0, min(100, pct))

    def is_expired(self):
        return bool(self.deadline and timezone.localdate() > self.deadline)

    def should_complete(self):
        return self.raised_total() >= (self.target_amount or Decimal("0.00"))

    def mark_completed_if_needed(self):
        if self.status == "APPROVED" and self.should_complete():
            self.status = "COMPLETED"
            self.completed_at = timezone.now()
            self.save(update_fields=["status", "completed_at"])

    def mark_archived(self):
        self.status = "ARCHIVED"
        self.archived_at = timezone.now()
        self.save(update_fields=["status", "archived_at"])

    def save(self, *args, **kwargs):
        """
        FIXED slug save:
        - generate only if missing (doesn't change existing URLs)
        - includes pk suffix to avoid collisions
        """
        super().save(*args, **kwargs)

        if self.slug:
            return

        base = slugify(f"{self.title} {self.patient_name} {self.hospital_city}").strip("-")
        if not base:
            base = "campaign"

        suffix = f"-{self.pk}"
        max_len = self._meta.get_field("slug").max_length - len(suffix)
        base = base[:max_len].strip("-")

        self.slug = f"{base}{suffix}"
        super().save(update_fields=["slug"])


class CampaignDocument(models.Model):
    DOC_TYPE = [
        ("MEDICAL_REPORT", "Medical Report"),
        ("HOSPITAL_LETTER", "Hospital Letter"),
        ("INVOICE", "Invoice / Bill"),
        ("OTHER", "Other"),
    ]
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name="documents")
    doc_type = models.CharField(max_length=20, choices=DOC_TYPE, default="OTHER")
    file = models.FileField(upload_to="campaign_docs/")
    note = models.CharField(max_length=255, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="campaign_docs_uploaded",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)


class Donation(models.Model):
    STATUS = [
        ("INITIATED", "Initiated"),
        ("SUCCESS", "Success"),
        ("FAILED", "Failed"),
    ]
    GATEWAY = [
        ("KHALTI", "Khalti"),
        ("ESEWA", "eSewa"),
    ]

    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name="donations")

    donor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="donations_made",
    )

    guest_name = models.CharField(max_length=120, blank=True)
    guest_email = models.EmailField(blank=True)
    guest_phone = models.CharField(max_length=30, blank=True)

    amount = models.DecimalField(max_digits=12, decimal_places=2)
    gateway = models.CharField(max_length=10, choices=GATEWAY)
    status = models.CharField(max_length=10, choices=STATUS, default="INITIATED")

    # Khalti fields
    pidx = models.CharField(max_length=120, blank=True)
    payment_url = models.URLField(blank=True)

    # eSewa fields
    esewa_pid = models.CharField(max_length=100, blank=True)
    esewa_ref_id = models.CharField(max_length=120, blank=True)

    gateway_ref = models.CharField(max_length=200, blank=True)
    raw_response = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    esewa_transaction_uuid = models.CharField(max_length=120, blank=True)
    esewa_transaction_code = models.CharField(max_length=120, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["gateway", "status"]),
        ]

    def donor_display(self):
        if self.donor_user_id:
            return self.donor_user.username
        return self.guest_name or "Guest"


class Disbursement(models.Model):
    """
    Central collection release proof.
    Publicly visible on campaign page.
    """
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name="disbursements")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    proof_file = models.FileField(upload_to="campaign_disbursements/")
    note = models.TextField(blank=True)

    released_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="disbursements_released",
    )
    released_at = models.DateTimeField(auto_now_add=True)


class CampaignReport(models.Model):
    STATUS = [
        ("OPEN", "Open"),
        ("REVIEWED", "Reviewed"),
        ("DISMISSED", "Dismissed"),
    ]
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name="reports")
    reporter_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="campaign_reports",
    )
    guest_name = models.CharField(max_length=120, blank=True)
    guest_email = models.EmailField(blank=True)

    reason = models.CharField(max_length=80, default="Suspicious")
    message = models.TextField(blank=True)

    status = models.CharField(max_length=10, choices=STATUS, default="OPEN")
    created_at = models.DateTimeField(auto_now_add=True)


class CampaignAuditLog(models.Model):
    ACTIONS = [
        ("CREATED", "Created"),
        ("SUBMITTED", "Submitted"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
        ("DONATION_INITIATED", "Donation Initiated"),
        ("DONATION_SUCCESS", "Donation Success"),
        ("DONATION_FAILED", "Donation Failed"),
        ("DISBURSED", "Disbursed"),
        ("REPORTED", "Reported"),
        ("COMPLETED", "Completed"),
        ("ARCHIVED", "Archived"),
        ("UPDATED", "Updated"),
    ]
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name="audit_logs")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="campaign_audit_actions",
    )
    action = models.CharField(max_length=30, choices=ACTIONS)
    message = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)