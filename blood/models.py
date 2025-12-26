from django.db import models
from django.utils import timezone

class PublicBloodRequest(models.Model):
    """
    Recipients asking for help without login.
    """
    patient_name = models.CharField(max_length=100)
    blood_group = models.CharField(max_length=5, choices=[
        ('A+', 'A+'), ('A-', 'A-'), ('B+', 'B+'), ('B-', 'B-'),
        ('AB+', 'AB+'), ('AB-', 'AB-'), ('O+', 'O+'), ('O-', 'O-'),
    ])
    location_city = models.CharField(max_length=100)
    hospital_name = models.CharField(max_length=150)
    contact_phone = models.CharField(max_length=15)
    units_needed = models.IntegerField(default=1)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"Need {self.blood_group} at {self.location_city}"

class GuestResponse(models.Model):
    """
    Donors responding without login.
    """
    request = models.ForeignKey(PublicBloodRequest, on_delete=models.CASCADE, related_name='responses')
    donor_name = models.CharField(max_length=100)
    donor_phone = models.CharField(max_length=15)
    
    # Status: 'Incoming' means they are on their way.
    status = models.CharField(max_length=20, default='Incoming') 
    responded_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.donor_name} is helping {self.request.patient_name}"