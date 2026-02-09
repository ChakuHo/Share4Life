from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db.models import Sum
from django.db import transaction

from accounts.models import UserProfile
from blood.models import BloodDonation
from organ.models import OrganPledge
from crowdfunding.models import Donation


User = get_user_model()


class Command(BaseCommand):
    help = "Recalculate UserProfile.points from verified data (KYC + blood + organ + crowdfunding)."

    def add_arguments(self, parser):
        parser.add_argument("--user", type=int, default=None, help="Recalculate for only this user id")
        parser.add_argument("--dry-run", action="store_true", help="Do not save, just print results")

    @transaction.atomic
    def handle(self, *args, **opts):
        user_id = opts["user"]
        dry = bool(opts["dry_run"])

        qs = UserProfile.objects.select_related("user").all()
        if user_id:
            qs = qs.filter(user_id=user_id)

        updated = 0

        for prof in qs:
            u = prof.user

            total = 0

            # 1) KYC APPROVED: +200
            try:
                if getattr(u, "kyc", None) and u.kyc.status == "APPROVED":
                    total += 200
            except Exception:
                pass

            # 2) Blood VERIFIED: +150 + (20 * units) per VERIFIED donation
            blood_rows = (
                BloodDonation.objects
                .filter(donor_user=u, status="VERIFIED")
                .values("units")
            )
            for row in blood_rows:
                units = int(row.get("units") or 0)
                total += 150 + (20 * units)

            # 3) Organ pledge VERIFIED: +150 per VERIFIED pledge
            organ_count = OrganPledge.objects.filter(donor=u, status="VERIFIED").count()
            total += 150 * organ_count

            # 4) Crowdfunding SUCCESS: +(amount // 100) per SUCCESS donation
            cf_amounts = Donation.objects.filter(donor_user=u, status="SUCCESS").values_list("amount", flat=True)
            for amt in cf_amounts:
                try:
                    total += max(0, int(amt) // 100)
                except Exception:
                    pass

            if dry:
                self.stdout.write(f"[DRY] user={u.id} {u.username} points={total}")
                continue

            if prof.points != total:
                prof.points = total
                prof.save(update_fields=["points"])
                updated += 1
                self.stdout.write(self.style.SUCCESS(f"Updated user={u.id} {u.username} points={total}"))

        self.stdout.write(self.style.SUCCESS(f"Done. Updated profiles: {updated}"))