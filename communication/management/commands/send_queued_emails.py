from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.utils import timezone

from communication.models import QueuedEmail


class Command(BaseCommand):
    help = "Send queued emails in batches with duplicate suppression."

    def handle(self, *args, **options):
        if not getattr(settings, "ENABLE_SCHEDULED_EMAILS", True):
            self.stdout.write("Scheduled emails are disabled.")
            return

        batch_size = int(getattr(settings, "EMAIL_QUEUE_BATCH_SIZE", 40))
        max_attempts = int(getattr(settings, "EMAIL_QUEUE_MAX_ATTEMPTS", 3))
        dedupe_hours = int(getattr(settings, "EMAIL_DEDUPE_HOURS", 24))

        now = timezone.now()
        recent_cutoff = now - timedelta(hours=dedupe_hours)

        qs = (
            QueuedEmail.objects
            .filter(status="PENDING", attempts__lt=max_attempts)
            .order_by("created_at", "id")[:batch_size]
        )

        if not qs:
            self.stdout.write("No queued emails.")
            return

        sent = 0
        failed = 0
        suppressed = 0

        for item in qs:
            older_pending_exists = QueuedEmail.objects.filter(
                to_email=item.to_email,
                subject=item.subject,
                body=item.body,
                status="PENDING",
                id__lt=item.id,
            ).exists()

            recent_sent_exists = QueuedEmail.objects.filter(
                to_email=item.to_email,
                subject=item.subject,
                body=item.body,
                status="SENT",
                sent_at__gte=recent_cutoff,
            ).exists()

            if older_pending_exists or recent_sent_exists:
                item.status = "FAILED"
                item.last_error = "Duplicate suppressed by send_queued_emails safeguard."
                item.save(update_fields=["status", "last_error"])
                suppressed += 1
                continue

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

        self.stdout.write(
            self.style.SUCCESS(
                f"Sent: {sent}, Failed: {failed}, Suppressed duplicates: {suppressed}"
            )
        )