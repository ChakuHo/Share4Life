"""
python manage.py expire_stale_requests

Run daily (or hourly). Safe to run multiple times.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings
from datetime import timedelta

from blood.models import PublicBloodRequest
from communication.models import Notification


class Command(BaseCommand):
    help = "Expire stale blood requests (OPEN > 7 days, IN_PROGRESS > 14 days)"

    def handle(self, *args, **options):
        now = timezone.now()
        max_open_days = int(getattr(settings, "S4L_PUBLIC_FEED_MAX_DAYS", 7))
        max_progress_days = max_open_days * 2  # 14 days for IN_PROGRESS

        open_cutoff = now - timedelta(days=max_open_days)
        progress_cutoff = now - timedelta(days=max_progress_days)

        # 1) Expire OPEN requests older than 7 days
        open_stale = PublicBloodRequest.objects.filter(
            is_active=True,
            status="OPEN",
            created_at__lt=open_cutoff,
        )

        open_count = 0
        for req in open_stale:
            req.status = "EXPIRED"
            req.is_active = False
            req.save(update_fields=["status", "is_active"])
            open_count += 1

            if req.created_by_id:
                Notification.objects.create(
                    user_id=req.created_by_id,
                    title="Blood request expired",
                    body=(
                        f"Your request for {req.blood_group} at {req.location_city} "
                        f"expired after {max_open_days} days with no donor. "
                        f"You can reactivate it from My Requests."
                    ),
                    url=f"/blood/request/{req.id}/",
                    level="WARNING",
                    category="BLOOD",
                )

        # 2) Expire IN_PROGRESS requests older than 14 days
        progress_stale = PublicBloodRequest.objects.filter(
            is_active=True,
            status="IN_PROGRESS",
            created_at__lt=progress_cutoff,
        )

        progress_count = 0
        for req in progress_stale:
            req.status = "EXPIRED"
            req.is_active = False
            req.save(update_fields=["status", "is_active"])
            progress_count += 1

            if req.created_by_id:
                Notification.objects.create(
                    user_id=req.created_by_id,
                    title="Blood request expired",
                    body=(
                        f"Your request for {req.blood_group} has been open for "
                        f"{max_progress_days} days without verified donation. "
                        f"You can reactivate it from My Requests."
                    ),
                    url=f"/blood/request/{req.id}/",
                    level="WARNING",
                    category="BLOOD",
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Expired {open_count} OPEN + {progress_count} IN_PROGRESS requests."
            )
        )