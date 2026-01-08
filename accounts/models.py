from django.db import models
from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.db.models.signals import post_save
from django.utils import timezone
from django.core.validators import FileExtensionValidator
import os   
import uuid
from django.dispatch import receiver

class CustomUser(AbstractUser):
    """
    Core User model. 
    Users can be donors AND recipients at the same time.
    """
    is_donor = models.BooleanField(default=False)
    is_recipient = models.BooleanField(default=False)
    is_hospital_admin = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False)
    email_verified = models.BooleanField(default=False)
    phone_number = models.CharField(max_length=15, blank=True)
    profile_image = models.ImageField(upload_to='profile_pics/', blank=True, null=True)

    def __str__(self):
        return self.username

class UserProfile(models.Model):
    """
    Extended details for medical info and location.
    """
    BLOOD_GROUPS = (
        ('A+', 'A+'), ('A-', 'A-'),
        ('B+', 'B+'), ('B-', 'B-'),
        ('AB+', 'AB+'), ('AB-', 'AB-'),
        ('O+', 'O+'), ('O-', 'O-'),
    )

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile')
    
    blood_group = models.CharField(max_length=5, choices=BLOOD_GROUPS, blank=True)
    medical_history = models.TextField(blank=True, help_text="Allergies, past surgeries, etc.")
    
    # Location
    city = models.CharField(max_length=100, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    
    # Gamification
    points = models.IntegerField(default=0)

    # Personal
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=20, blank=True)

    # Address (basic KYC/profile)
    address_line = models.CharField(max_length=255, blank=True)
    state = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=100, blank=True)

    # Emergency contact
    emergency_contact_name = models.CharField(max_length=120, blank=True)
    emergency_contact_phone = models.CharField(max_length=30, blank=True)
    
    def __str__(self):
        return f"Profile of {self.user.username}"

class FamilyMember(models.Model):
    primary_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="family_members"
    )
    name = models.CharField(max_length=100)
    relationship = models.CharField(max_length=50)
    phone_number = models.CharField(max_length=15, blank=True)

    # NEW: emergency profile fields (additive)
    blood_group = models.CharField(max_length=5, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    medical_history = models.TextField(blank=True)

    city = models.CharField(max_length=100, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

    is_emergency_profile = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.name} ({self.relationship})"
    

def kyc_upload_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    return f"kyc/user_{instance.user_id}/{uuid.uuid4().hex}{ext}"


class KYCProfile(models.Model):
    STATUS = (
        ("NOT_SUBMITTED", "Not Submitted"),
        ("PENDING", "Pending Review"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
    )

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="kyc")
    status = models.CharField(max_length=20, choices=STATUS, default="NOT_SUBMITTED")

    # Basic KYC info
    full_name = models.CharField(max_length=150, blank=True)
    id_type = models.CharField(max_length=50, blank=True)   # "Citizenship", "Passport", etc.
    id_number = models.CharField(max_length=80, blank=True)

    # Review tracking
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="kyc_reviews"
    )
    rejection_reason = models.TextField(blank=True)

    def mark_submitted(self):
        self.status = "PENDING"
        self.submitted_at = timezone.now()
        self.rejection_reason = ""
        self.save()

    def __str__(self):
        return f"KYC({self.user.username}) - {self.status}"


class KYCDocument(models.Model):
    DOC_TYPE = (
        ("ID_FRONT", "ID Front"),
        ("ID_BACK", "ID Back"),
        ("SELFIE", "Selfie"),
        ("ADDRESS_PROOF", "Proof of Address"),
    )

    kyc = models.ForeignKey(KYCProfile, on_delete=models.CASCADE, related_name="documents")
    doc_type = models.CharField(max_length=30, choices=DOC_TYPE)
    file = models.FileField(
        upload_to=kyc_upload_path,
        validators=[FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png", "pdf"])],
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("kyc", "doc_type")

    def __str__(self):
        return f"{self.kyc.user.username} - {self.doc_type}"

# --- SIGNALS (AUTOMATICALLY CREATE PROFILE) ---
@receiver(post_save, sender=CustomUser)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)

@receiver(post_save, sender=CustomUser)
def save_user_profile(sender, instance, **kwargs):
    instance.profile.save()

@receiver(post_save, sender=CustomUser)
def create_kyc_profile(sender, instance, created, **kwargs):
    if created:
        KYCProfile.objects.create(user=instance)