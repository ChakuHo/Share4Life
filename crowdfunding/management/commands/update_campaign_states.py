from datetime import timedelta

from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone
from django.db import transaction

from crowdfunding.models import Campaign, CampaignAuditLog


class Command(BaseCommand):
    help = "Auto-update crowdfunding campaigns: refresh totals, mark COMPLETED, mark EXPIRED, auto-archive."

    def handle(self, *args, **options):
        now = timezone.now()
        today = timezone.localdate()
        archive_days = int(getattr(settings, "CAMPAIGN_ARCHIVE_AFTER_DAYS", 1))

        # We update campaigns that can change state:
        # - APPROVED: may become COMPLETED or EXPIRED
        # - EXPIRED: may still become COMPLETED if late payments get confirmed
        # - COMPLETED: may become ARCHIVED
        qs = Campaign.objects.filter(status__in=["APPROVED", "EXPIRED", "COMPLETED"])

        completed = 0
        expired = 0
        archived = 0
        refreshed = 0

        for camp in qs.iterator():
            with transaction.atomic():
                # refresh totals
                camp.refresh_raised_amount()
                refreshed += 1

                before = camp.status

                # 1) complete if needed (APPROVED/EXPIRED -> COMPLETED)
                camp.mark_completed_if_needed()
                if before != camp.status and camp.status == "COMPLETED":
                    completed += 1
                    CampaignAuditLog.objects.create(
                        campaign=camp, actor=None, action="COMPLETED", message="Target reached (auto)"
                    )

                # 2) expire if needed (APPROVED only)
                before2 = camp.status
                changed = camp.mark_expired_if_needed()
                if changed and before2 != camp.status and camp.status == "EXPIRED":
                    expired += 1
                    CampaignAuditLog.objects.create(
                        campaign=camp, actor=None, action="EXPIRED", message="Deadline passed, goal not reached (auto)"
                    )

                # 3) archive after completion
                if camp.status == "COMPLETED" and camp.completed_at:
                    if now >= camp.completed_at + timedelta(days=archive_days):
                        camp.mark_archived()
                        archived += 1
                        CampaignAuditLog.objects.create(
                            campaign=camp, actor=None, action="ARCHIVED", message="Auto archived"
                        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Campaign states updated. Refreshed={refreshed}, Completed={completed}, "
                f"Expired={expired}, Archived={archived} (today={today})"
            )
        )