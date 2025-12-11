from django.db import models
from django.contrib.auth.models import AbstractUser
from django.conf import settings

class CustomUser(AbstractUser):
    """
    Core User model. 
    Users can be donors, recipients, or medical professionals.
    """
    is_donor = models.BooleanField(default=False)
    is_recipient = models.BooleanField(default=False)
    is_hospital_admin = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False)
    
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
    
    # Location (For InDrive-style matching)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    city = models.CharField(max_length=100, blank=True)
    
    # Gamification
    points = models.IntegerField(default=0)
    
    def __str__(self):
        return f"Profile of {self.user.username}"

class FamilyMember(models.Model):
    """
    Links users to family members.
    """
    primary_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='family_members')
    name = models.CharField(max_length=100)
    relationship = models.CharField(max_length=50) # e.g., Father
    phone_number = models.CharField(max_length=15, blank=True)

    def __str__(self):
        return f"{self.name} ({self.relationship})"