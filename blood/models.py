import os
import uuid

from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.db import models
from django.db.models import Q, Sum
from django.utils import timezone


class PublicBloodRequest(models.Model):
    """
    Blood request posted by guest or logged-in recipient.
    """
    STATUS = [
        ("OPEN", "Open"),
        ("IN_PROGRESS", "In Progress"),
        ("FULFILLED", "Fulfilled"),
        ("CANCELLED", "Cancelled"),
    ]

    BLOOD_GROUPS = [
        ("A+", "A+"), ("A-", "A-"),
        ("B+", "B+"), ("B-", "B-"),
        ("AB+", "AB+"), ("AB-", "AB-"),
        ("O+", "O+"), ("O-", "O-"),
    ]

    patient_name = models.CharField(max_length=100)
    blood_group = models.CharField(max_length=5, choices=BLOOD_GROUPS)

    location_city = models.CharField(max_length=100)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    hospital_name = models.CharField(max_length=150)

    # increased for E.164 phone format like +9779812345678
    contact_phone = models.CharField(max_length=20)

    units_needed = models.IntegerField(default=1)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    is_emergency = models.BooleanField(default=False)

    # workflow fields
    status = models.CharField(max_length=12, choices=STATUS, default="OPEN")
    fulfilled_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="blood_requests_created",
    )

    VERIFICATION = [
        ("UNVERIFIED", "Unverified (Guest/No proof)"),
        ("PENDING", "Pending Verification"),
        ("VERIFIED", "Verified"),
        ("REJECTED", "Rejected"),
    ]

    verification_status = models.CharField(
        max_length=12,
        choices=VERIFICATION,
        default="UNVERIFIED",
    )

    proof_document = models.FileField(
        upload_to="blood_request_proofs/",
        blank=True, null=True,
        validators=[FileExtensionValidator(allowed_extensions=["pdf", "jpg", "jpeg", "png"])],
        help_text="Hospital letter / report / proof document (PDF/JPG/PNG)."
    )

    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="blood_requests_verified_by",
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    target_organization = models.ForeignKey(
        "hospitals.Organization",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="blood_requests",
        help_text="Which organization should verify/handle this request.",
    )

    def __str__(self):
        return f"Need {self.blood_group} at {self.location_city}"


class GuestResponse(models.Model):
    """
    Donors responding without login.
    """
    request = models.ForeignKey(
        PublicBloodRequest,
        on_delete=models.CASCADE,
        related_name="responses",
    )
    donor_name = models.CharField(max_length=100)

    # increased for E.164 phone format like +9779812345678
    donor_phone = models.CharField(max_length=20)

    status = models.CharField(max_length=20, default="Incoming")
    responded_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.donor_name} is helping {self.request.patient_name}"


class DonorResponse(models.Model):
    STATUS = [
        ("PENDING", "Pending"),
        ("ACCEPTED", "Accepted"),
        ("DECLINED", "Declined"),
        ("DELAYED", "Delayed"),
    ]

    request = models.ForeignKey(
        PublicBloodRequest,
        on_delete=models.CASCADE,
        related_name="donor_responses",
    )
    donor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="blood_responses",
    )

    status = models.CharField(max_length=10, choices=STATUS, default="PENDING")
    message = models.CharField(max_length=255, blank=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("request", "donor")


class BloodDonation(models.Model):
    STATUS = [
        ("COMPLETED", "Completed"),
        ("VERIFIED", "Verified"),
        ("REJECTED", "Rejected"),
    ]

    request = models.ForeignKey(
        PublicBloodRequest,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="donations",
    )

    donor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="blood_donations",
    )

    blood_group = models.CharField(max_length=5, blank=True)
    units = models.PositiveIntegerField(default=1)
    hospital_name = models.CharField(max_length=150, blank=True)

    donated_at = models.DateTimeField(default=timezone.now)

    status = models.CharField(max_length=10, choices=STATUS, default="COMPLETED")
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="blood_donations_verified_by",
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    verified_by_org = models.ForeignKey(
        "hospitals.Organization",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="verified_donations",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["request", "donor_user"],
                condition=Q(request__isnull=False, donor_user__isnull=False),
                name="uniq_donation_per_request_per_donor",
            )
        ]

    def mark_verified(self, verifier_user, verified_org=None):
        """
        Mark donation VERIFIED and update the linked request:
        - Request becomes FULFILLED only when total VERIFIED units >= units_needed
        - Otherwise keep request IN_PROGRESS

        Gamification:
          +150 base points + (20 × units) when donation becomes VERIFIED (only once)
        """
        if self.status == "VERIFIED":
            return

        self.status = "VERIFIED"
        self.verified_by = verifier_user
        self.verified_by_org = verified_org
        self.verified_at = timezone.now()
        self.rejection_reason = ""

        self.save(update_fields=[
            "status", "verified_by", "verified_by_org", "verified_at", "rejection_reason"
        ])

        # award points (only on first verification)
        if self.donor_user_id:
            try:
                from django.apps import apps
                from django.db.models import F
                Profile = apps.get_model("accounts", "UserProfile")

                units = int(self.units or 0)
                add_points = 150 + (20 * units)

                Profile.objects.filter(user_id=self.donor_user_id).update(points=F("points") + add_points)
            except Exception:
                pass

        if not self.request_id:
            return

        req = self.request

        verified_units = (
            BloodDonation.objects
            .filter(request_id=req.id, status="VERIFIED")
            .aggregate(s=Sum("units"))["s"] or 0
        )

        needed = int(req.units_needed or 1)

        if verified_units >= needed:
            req.status = "FULFILLED"
            req.is_active = False
            req.fulfilled_at = timezone.now()
            req.save(update_fields=["status", "is_active", "fulfilled_at"])
        else:
            if req.status == "OPEN":
                req.status = "IN_PROGRESS"
                req.save(update_fields=["status"])


def donation_report_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    return f"medical_reports/donation_{instance.donation_id}/{uuid.uuid4().hex}{ext}"


class DonationMedicalReport(models.Model):
    donation = models.ForeignKey(
        BloodDonation,
        on_delete=models.CASCADE,
        related_name="reports",
    )
    file = models.FileField(
        upload_to=donation_report_path,
        validators=[FileExtensionValidator(allowed_extensions=["pdf", "jpg", "jpeg", "png"])],
    )
    note = models.CharField(max_length=255, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="donation_reports_uploaded",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)