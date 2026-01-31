import os
import uuid

from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils import timezone


# ---------- Upload paths ----------
def pledge_doc_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    return f"organ/pledges/pledge_{instance.pledge_id}/{uuid.uuid4().hex}{ext}"


def request_doc_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    return f"organ/requests/request_{instance.request_id}/{uuid.uuid4().hex}{ext}"


class OrganPledge(models.Model):
    """
    Donor pledge. Only VERIFIED pledges are matchable/searchable by organizations.
    """

    PLEDGE_TYPE = [
        ("LIVING", "Living Donation"),
        ("DECEASED", "Deceased Donation (after death)"),
    ]

    STATUS = [
        ("DRAFT", "Draft"),
        ("SUBMITTED", "Submitted"),
        ("UNDER_REVIEW", "Under Review"),
        ("VERIFIED", "Verified"),
        ("REJECTED", "Rejected"),
        ("REVOKED", "Revoked"),
    ]

    ORGANS = [
        ("KIDNEY", "Kidney"),
        ("LIVER", "Liver"),
        ("HEART", "Heart"),
        ("LUNG", "Lung"),
        ("PANCREAS", "Pancreas"),
        ("INTESTINE", "Intestine"),
        ("CORNEA", "Cornea"),
        ("SKIN", "Skin"),
        ("BONE_MARROW", "Bone Marrow"),
        ("OTHER", "Other"),
    ]

    donor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="organ_pledges",
    )

    pledge_type = models.CharField(max_length=10, choices=PLEDGE_TYPE)
    organs = models.JSONField(default=list, help_text="List of organ codes from ORGANS choices")

    # Consent & legal
    consent_confirmed = models.BooleanField(default=False)
    consent_at = models.DateTimeField(null=True, blank=True)

    # donor note
    note = models.TextField(blank=True)

    status = models.CharField(max_length=20, choices=STATUS, default="DRAFT")

    # verification (by org)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="organ_pledges_verified_by",
    )
    verified_by_org = models.ForeignKey(
        "hospitals.Organization",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="verified_organ_pledges",
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    submitted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["pledge_type", "status"]),
        ]

    def __str__(self):
        return f"Pledge#{self.id} {self.donor.username} ({self.pledge_type})"

    @property
    def organ_names(self):
        """
        Human readable organ names for templates.
        FIXED: this property must be inside the model.
        """
        m = dict(self.ORGANS)
        return [m.get(code, code) for code in (self.organs or [])]

    def submit(self):
        self.status = "SUBMITTED"
        self.submitted_at = timezone.now()
        if self.consent_confirmed and not self.consent_at:
            self.consent_at = timezone.now()
        self.save(update_fields=["status", "submitted_at", "consent_at"])

    def revoke(self):
        self.status = "REVOKED"
        self.revoked_at = timezone.now()
        self.save(update_fields=["status", "revoked_at"])


class OrganPledgeDocument(models.Model):
    DOC_TYPE = [
        ("CONSENT_FORM", "Consent Form"),
        ("MEDICAL_REPORT", "Medical Report"),
        ("OTHER", "Other"),
    ]

    pledge = models.ForeignKey(OrganPledge, on_delete=models.CASCADE, related_name="documents")
    doc_type = models.CharField(max_length=20, choices=DOC_TYPE, default="OTHER")

    file = models.FileField(
        upload_to=pledge_doc_path,
        validators=[FileExtensionValidator(allowed_extensions=["pdf", "jpg", "jpeg", "png"])],
    )
    note = models.CharField(max_length=255, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)


class OrganRequest(models.Model):
    """
    Recipient request. Can be created by:
    - recipient user
    - org staff (on behalf), stored as created_by user
    """

    URGENCY = [
        ("LOW", "Low"),
        ("MEDIUM", "Medium"),
        ("HIGH", "High"),
        ("CRITICAL", "Critical"),
    ]

    STATUS = [
        ("DRAFT", "Draft"),
        ("SUBMITTED", "Submitted"),
        ("UNDER_REVIEW", "Under Review"),
        ("ACTIVE", "Active"),
        ("MATCH_IN_PROGRESS", "Match In Progress"),
        ("CLOSED", "Closed"),
        ("CANCELLED", "Cancelled"),
        ("REJECTED", "Rejected"),
        ("EXPIRED", "Expired"),
    ]

    ORGAN = OrganPledge.ORGANS

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="organ_requests_created",
    )

    patient_name = models.CharField(max_length=120)
    organ_needed = models.CharField(max_length=20, choices=ORGAN)
    urgency = models.CharField(max_length=10, choices=URGENCY, default="MEDIUM")

    hospital_name = models.CharField(max_length=150)
    city = models.CharField(max_length=100)
    contact_phone = models.CharField(max_length=20)

    note = models.TextField(blank=True)

    status = models.CharField(max_length=20, choices=STATUS, default="SUBMITTED")

    # org handling
    target_organization = models.ForeignKey(
        "hospitals.Organization",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="organ_requests",
    )

    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="organ_requests_verified_by",
    )
    verified_by_org = models.ForeignKey(
        "hospitals.Organization",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="verified_organ_requests",
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["organ_needed", "status"]),
        ]

    def __str__(self):
        return f"OrganRequest#{self.id} {self.organ_needed} ({self.city})"


class OrganRequestDocument(models.Model):
    DOC_TYPE = [
        ("MEDICAL_REPORT", "Medical Report"),
        ("HOSPITAL_LETTER", "Hospital Letter"),
        ("OTHER", "Other"),
    ]

    request = models.ForeignKey(OrganRequest, on_delete=models.CASCADE, related_name="documents")
    doc_type = models.CharField(max_length=20, choices=DOC_TYPE, default="MEDICAL_REPORT")

    file = models.FileField(
        upload_to=request_doc_path,
        validators=[FileExtensionValidator(allowed_extensions=["pdf", "jpg", "jpeg", "png"])],
    )
    note = models.CharField(max_length=255, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)


class OrganMatch(models.Model):
    """
    Org-managed match record (case management).
    Only uses VERIFIED pledges (enforced in view).
    """

    STATUS = [
        ("PROPOSED", "Proposed"),
        ("CONTACTED", "Contacted"),
        ("SCREENING", "Screening"),
        ("APPROVED", "Approved"),
        ("COMPLETED", "Completed"),
        ("FAILED", "Failed"),
        ("CANCELLED", "Cancelled"),
    ]

    request = models.ForeignKey(OrganRequest, on_delete=models.CASCADE, related_name="matches")
    pledge = models.ForeignKey(OrganPledge, on_delete=models.CASCADE, related_name="matches")

    organization = models.ForeignKey(
        "hospitals.Organization",
        on_delete=models.CASCADE,
        related_name="organ_matches",
    )

    status = models.CharField(max_length=20, choices=STATUS, default="PROPOSED")
    notes = models.TextField(blank=True)

    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="organ_match_updates",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["status", "updated_at"]),
        ]
        # Prevent duplicate matches for same pledge + request
        constraints = [
            models.UniqueConstraint(fields=["request", "pledge"], name="uniq_match_per_request_pledge"),
        ]

    def __str__(self):
        return f"Match#{self.id} Req#{self.request_id} Pledge#{self.pledge_id} ({self.status})"