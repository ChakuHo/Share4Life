from django.conf import settings
from django.db import models
from django.utils import timezone

class Notification(models.Model):
    LEVELS = [("INFO","Info"), ("SUCCESS","Success"), ("WARNING","Warning"), ("DANGER","Danger")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    title = models.CharField(max_length=120)
    body = models.TextField(blank=True)
    url = models.CharField(max_length=255, blank=True)  # where to go when clicked
    level = models.CharField(max_length=10, choices=LEVELS, default="INFO")

    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    def mark_read(self):
        if not self.read_at:
            self.read_at = timezone.now()
            self.save(update_fields=["read_at"])