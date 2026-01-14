from django.core.management.base import BaseCommand
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from communication.models import QueuedEmail

class Command(BaseCommand):
    help = "Send queued emails in batches (safe for sqlite/Gmail)."

    def handle(self, *args, **options):
        batch_size = int(getattr(settings, "EMAIL_QUEUE_BATCH_SIZE", 40))
        max_attempts = int(getattr(settings, "EMAIL_QUEUE_MAX_ATTEMPTS", 3))

        qs = (QueuedEmail.objects
              .filter(status="PENDING", attempts__lt=max_attempts)
              .order_by("created_at")[:batch_size])

        if not qs:
            self.stdout.write("No queued emails.")
            return

        sent = 0
        failed = 0

        for item in qs:
            try:
                send_mail(
                    item.subject,
                    item.body,
                    settings.DEFAULT_FROM_EMAIL,
                    [item.to_email],
                    fail_silently=False,
                )
                item.status = "SENT"
                item.sent_at = timezone.now()
                item.last_error = ""
                item.save(update_fields=["status", "sent_at", "last_error"])
                sent += 1
            except Exception as e:
                item.attempts += 1
                item.last_error = str(e)[:2000]
                if item.attempts >= max_attempts:
                    item.status = "FAILED"
                    item.save(update_fields=["attempts", "last_error", "status"])
                else:
                    item.save(update_fields=["attempts", "last_error"])
                failed += 1

        self.stdout.write(f"Sent: {sent}, Failed: {failed}")