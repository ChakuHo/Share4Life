from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils import timezone
from blood.matching import canonical_city


class Organization(models.Model):
    TYPE = [
        ("HOSPITAL", "Hospital"),
        ("NGO", "NGO"),
        ("RED_CROSS", "Red Cross"),
        ("BLOOD_BANK", "Blood Bank"),
        ("GOV", "Government"),
        ("OTHER", "Other"),
    ]
    STATUS = [
        ("PENDING", "Pending"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
        ("SUSPENDED", "Suspended"),
    ]

    name = models.CharField(max_length=200, unique=True)
    org_type = models.CharField(max_length=20, choices=TYPE, default="HOSPITAL")

    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)

    city_canon = models.CharField(max_length=100, blank=True, db_index=True)
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)

    proof_document = models.FileField(
        upload_to="org_proofs/",
        null=True, blank=True,
        validators=[FileExtensionValidator(allowed_extensions=["pdf", "jpg", "jpeg", "png"])],
    )

    status = models.CharField(max_length=12, choices=STATUS, default="PENDING")
    rejection_reason = models.TextField(blank=True)

    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="organizations_approved",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

    def __str__(self):
        return f"{self.name} ({self.get_org_type_display()})"
    
    def save(self, *args, **kwargs):
        self.city_canon = canonical_city(self.city)
        super().save(*args, **kwargs)


class OrganizationMembership(models.Model):
    ROLE = [
        ("ADMIN", "Admin"),
        ("VERIFIER", "Verifier"),
        ("STAFF", "Staff"),
    ]

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="org_memberships")

    role = models.CharField(max_length=10, choices=ROLE, default="STAFF")
    is_active = models.BooleanField(default=False)  # becomes true when org is approved

    added_at = models.DateTimeField(auto_now_add=True)
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="org_members_added",
    )

    class Meta:
        unique_together = ("organization", "user")

    def __str__(self):
        return f"{self.user.username} -> {self.organization.name} ({self.role})"
    

class BloodCampaign(models.Model):
    STATUS = [
        ("UPCOMING", "Upcoming"),
        ("ONGOING", "Ongoing"),
        ("COMPLETED", "Completed"),
        ("CANCELLED", "Cancelled"),
    ]

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="campaigns",
    )

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    date = models.DateField()
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)

    venue_name = models.CharField(max_length=200)
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)

    target_units = models.PositiveIntegerField(default=0)
    blood_groups_needed = models.CharField(
        max_length=100,
        blank=True,
        help_text="e.g. O+, O-, A+ (comma separated)",
    )

    status = models.CharField(max_length=10, choices=STATUS, default="UPCOMING")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "start_time"]

    def __str__(self):
        return f"{self.title} ({self.organization.name})"