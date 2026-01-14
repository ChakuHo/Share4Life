from django.conf import settings
from django.db import models
from django.utils import timezone

class Notification(models.Model):
    LEVELS = [("INFO","Info"), ("SUCCESS","Success"), ("WARNING","Warning"), ("DANGER","Danger")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    title = models.CharField(max_length=120)
    body = models.TextField(blank=True)
    url = models.CharField(max_length=255, blank=True) 
    level = models.CharField(max_length=10, choices=LEVELS, default="INFO")

    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    def mark_read(self):
        if not self.read_at:
            self.read_at = timezone.now()
            self.save(update_fields=["read_at"])

class QueuedEmail(models.Model):
    STATUS = [
        ("PENDING", "Pending"),
        ("SENT", "Sent"),
        ("FAILED", "Failed"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="queued_emails"
    )
    to_email = models.EmailField()
    subject = models.CharField(max_length=200)
    body = models.TextField()

    status = models.CharField(max_length=10, choices=STATUS, default="PENDING")
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self):
        return f"{self.to_email} [{self.status}]"
