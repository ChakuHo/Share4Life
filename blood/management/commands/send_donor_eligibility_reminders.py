from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Max, Q

from accounts.models import CustomUser
from communication.models import Notification, QueuedEmail, NotificationPreference


class Command(BaseCommand):
    help = "Send donor eligibility reminders (90 days after VERIFIED donation). In-app + email."

    def handle(self, *args, **options):
        if not getattr(settings, "ENABLE_SCHEDULED_EMAILS", True):
            self.stdout.write("Scheduled emails are disabled.")
            return

        now = timezone.localtime(timezone.now())
        today = now.date()

        days_before = int(getattr(settings, "S4L_ELIGIBILITY_REMIND_DAYS_BEFORE", 0))
        repeat_days = int(getattr(settings, "S4L_ELIGIBILITY_REMIND_REPEAT_DAYS", 7))
        recent_cutoff = now - timedelta(days=repeat_days)

        site_base = (getattr(settings, "SITE_BASE_URL", "") or "").rstrip("/")

        target_date = today + timedelta(days=days_before)

        donors = (
            CustomUser.objects
            .filter(is_active=True, is_donor=True)
            .annotate(
                last_verified=Max(
                    "blood_donations__donated_at",
                    filter=Q(blood_donations__status="VERIFIED")
                )
            )
            .only("id", "email", "username")
        )

        donor_ids = [d.id for d in donors]
        prefs = {
            p.user_id: p
            for p in NotificationPreference.objects.filter(user_id__in=donor_ids)
        }

        sent = 0
        skipped_duplicates = 0

        for d in donors:
            if not d.last_verified:
                continue

            eligible_date = timezone.localtime(d.last_verified).date() + timedelta(days=90)
            if eligible_date != target_date:
                continue

            pref = prefs.get(d.id)

            if pref and pref.is_muted("DONATION"):
                continue

            title = "You can donate blood again"
            body = f"You are eligible to donate again from {eligible_date}."
            url = "/blood/feed/"
            open_url = f"{site_base}{url}" if site_base else url

            recent_notification_exists = Notification.objects.filter(
                user_id=d.id,
                category="DONATION",
                title=title,
                created_at__gte=recent_cutoff,
            ).exists()

            recent_email_exists = QueuedEmail.objects.filter(
                user_id=d.id,
                subject="Share4Life - You are eligible to donate again",
                created_at__gte=recent_cutoff,
            ).exists()

            if recent_notification_exists or recent_email_exists:
                skipped_duplicates += 1
                continue

            Notification.objects.create(
                user_id=d.id,
                category="DONATION",
                title=title,
                body=body,
                url=url,
                level="SUCCESS",
            )

            if d.email:
                if not (pref and pref.email_enabled is False):
                    if not (pref and pref.email_emergency_only):
                        QueuedEmail.objects.create(
                            user_id=d.id,
                            to_email=d.email,
                            subject="Share4Life - You are eligible to donate again",
                            body=body + f"\n\nOpen: {open_url}",
                            status="PENDING",
                        )

            sent += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Eligibility reminders done. Sent/queued: {sent}, skipped duplicates: {skipped_duplicates}"
            )
        )