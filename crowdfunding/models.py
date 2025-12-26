from django.db import models
from django.utils import timezone

class Campaign(models.Model):
    title = models.CharField(max_length=200)
    patient_name = models.CharField(max_length=100)
    description = models.TextField()
    image = models.ImageField(upload_to='campaigns/')
    
    target_amount = models.DecimalField(max_digits=10, decimal_places=2)
    raised_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    is_featured = models.BooleanField(default=False, help_text="Check this to show on Home Page")
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return self.title

    def get_percentage(self):
        if self.target_amount > 0:
            return int((self.raised_amount / self.target_amount) * 100)
        return 0