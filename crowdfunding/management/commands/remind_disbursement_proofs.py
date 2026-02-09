from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Sum, Min

from crowdfunding.models import Campaign, CampaignAuditLog
from crowdfunding.services import notify_user
from django.contrib.auth import get_user_model

User = get_user_model()

class Command(BaseCommand):
    help = "Remind staff/owners to upload disbursement proof if campaigns have raised money but have no disbursement records."

    def handle(self, *args, **options):
        days = int(getattr(settings, "DISBURSEMENT_PROOF_REMINDER_DAYS", 3))
        cooldown_hours = int(getattr(settings, "DISBURSEMENT_PROOF_REMINDER_COOLDOWN_HOURS", 24))

        now = timezone.now()
        cutoff = now - timedelta(days=days)
        cooldown_cutoff = now - timedelta(hours=cooldown_hours)

        # campaigns with successful donations but no disbursement yet
        qs = (
            Campaign.objects
            .filter(status__in=["APPROVED", "COMPLETED"])
            .annotate(
                first_success_at=Min("donations__created_at"),
                success_total=Sum("donations__amount"),
            )
            .filter(donations__status="SUCCESS")
        ).distinct()

        staff_users = list(User.objects.filter(is_staff=True, is_active=True))

        sent = 0
        for camp in qs:
            if camp.disbursements.exists():
                continue

            # must have some successful donation long enough ago
            if not camp.first_success_at or camp.first_success_at > cutoff:
                continue

            # avoid spamming (check audit log marker)
            already = (
                CampaignAuditLog.objects
                .filter(campaign=camp, action="UPDATED", message__startswith="DISBURSEMENT_PROOF_REMINDER_SENT")
                .filter(created_at__gte=cooldown_cutoff)
                .exists()
            )
            if already:
                continue

            # notify owner
            if camp.owner_id:
                notify_user(
                    camp.owner,
                    "Disbursement proof pending",
                    "Your campaign has raised funds but disbursement proof has not been uploaded yet. "
                    "Staff will upload proof after releasing funds.",
                    url=camp.get_absolute_url(),
                    level="INFO",
                )

            # notify staff
            for u in staff_users:
                notify_user(
                    u,
                    "Disbursement proof pending",
                    f"Campaign '{camp.title}' has raised funds but has no disbursement proof yet.",
                    url=camp.get_absolute_url(),
                    level="WARNING",
                )

            CampaignAuditLog.objects.create(
                campaign=camp,
                actor=None,
                action="UPDATED",
                message=f"DISBURSEMENT_PROOF_REMINDER_SENT {now.strftime('%Y-%m-%d %H:%M')}",
            )
            sent += 1

        self.stdout.write(self.style.SUCCESS(f"Done. Reminders sent for {sent} campaigns."))