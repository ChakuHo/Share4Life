from django.conf import settings
from django.db import models
from django.utils import timezone


class Notification(models.Model):
    LEVELS = [("INFO", "Info"), ("SUCCESS", "Success"), ("WARNING", "Warning"), ("DANGER", "Danger")]

    CATEGORIES = [
        ("SYSTEM", "System"),
        ("BLOOD", "Blood"),
        ("EMERGENCY", "Emergency"),
        ("DONATION", "Donation"),
        ("CAMPAIGN", "Campaign"),
        ("KYC", "KYC"),
        ("CHAT", "Chat"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")

    category = models.CharField(max_length=20, choices=CATEGORIES, default="SYSTEM", db_index=True)

    title = models.CharField(max_length=120)
    body = models.TextField(blank=True)
    url = models.CharField(max_length=255, blank=True)
    level = models.CharField(max_length=10, choices=LEVELS, default="INFO")

    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["user", "read_at"]),
            models.Index(fields=["user", "category", "created_at"]),
        ]

    def mark_read(self):
        if not self.read_at:
            self.read_at = timezone.now()
            self.save(update_fields=["read_at"])


class NotificationPreference(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notif_pref")

    mute_system = models.BooleanField(default=False)
    mute_blood = models.BooleanField(default=False)
    mute_emergency = models.BooleanField(default=False)
    mute_donation = models.BooleanField(default=False)
    mute_campaign = models.BooleanField(default=False)
    mute_kyc = models.BooleanField(default=False)
    mute_chat = models.BooleanField(default=False)

    email_enabled = models.BooleanField(default=True)
    email_emergency_only = models.BooleanField(default=False)

    updated_at = models.DateTimeField(auto_now=True)

    def is_muted(self, category: str) -> bool:
        c = (category or "SYSTEM").upper()
        return {
            "SYSTEM": self.mute_system,
            "BLOOD": self.mute_blood,
            "EMERGENCY": self.mute_emergency,
            "DONATION": self.mute_donation,
            "CAMPAIGN": self.mute_campaign,
            "KYC": self.mute_kyc,
            "CHAT": self.mute_chat,
        }.get(c, False)

    def __str__(self):
        return f"NotifPref({self.user.username})"


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


# -------------------- CHAT --------------------

class ChatThread(models.Model):
    request = models.ForeignKey(
        "blood.PublicBloodRequest",
        on_delete=models.CASCADE,
        related_name="chat_threads",
    )

    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_threads_as_requester",
    )

    donor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_threads_as_donor",
    )

    last_message_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["request", "donor"], name="uniq_chat_thread_request_donor"),
        ]
        indexes = [
            models.Index(fields=["updated_at"]),
            models.Index(fields=["last_message_at"]),
        ]

    def __str__(self):
        return f"ChatThread#{self.id} Req#{self.request_id} Donor#{self.donor_id}"


class ChatMessage(models.Model):
    thread = models.ForeignKey(ChatThread, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chat_messages_sent")
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["thread", "created_at"]),
        ]

    def __str__(self):
        return f"Msg#{self.id} Thread#{self.thread_id}"


# -------------------- DIRECTORY DONOR PING (NEW) --------------------

class DirectDonorPing(models.Model):
    """
    Safe contact workflow for Public Donor Directory:
      - Recipient pings a donor with request details
      - Donor accepts/declines/delays
      - Donor phone is only shown to requester AFTER ACCEPT
    """

    STATUS = [
        ("PENDING", "Pending"),
        ("ACCEPTED", "Accepted"),
        ("DECLINED", "Declined"),
        ("DELAYED", "Delayed"),
        ("EXPIRED", "Expired"),
    ]

    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="direct_pings_sent",
    )
    donor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="direct_pings_received",
    )

    # request details
    blood_group_needed = models.CharField(max_length=5)
    units_needed = models.PositiveIntegerField(default=1)
    hospital_name = models.CharField(max_length=150)
    city = models.CharField(max_length=100)
    is_emergency = models.BooleanField(default=True)

    requester_phone = models.CharField(max_length=30, blank=True)
    message = models.TextField(blank=True)

    status = models.CharField(max_length=10, choices=STATUS, default="PENDING", db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)

    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["donor", "status", "created_at"]),
            models.Index(fields=["requester", "created_at"]),
        ]

    def is_expired(self) -> bool:
        return bool(self.expires_at and timezone.now() >= self.expires_at)

    def __str__(self):
        return f"Ping#{self.id} {self.requester_id}->{self.donor_id} [{self.status}]"