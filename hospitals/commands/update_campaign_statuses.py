from datetime import datetime, time, timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from accounts.models import CustomUser
from communication.services import broadcast_inapp
from hospitals.models import BloodCampaign


def _campaign_city(camp: BloodCampaign) -> str:
    # prefer campaign city, fallback to org city
    city = (camp.city or getattr(camp.organization, "city", "") or "").strip()
    return city


def _audience_for_campaign(camp: BloodCampaign):
    """
    Same city matching, but include users with blank city as fallback (your existing pattern).
    """
    city = _campaign_city(camp)
    qs = CustomUser.objects.filter(is_active=True).select_related("profile")

    if city:
        qs = qs.filter(
            Q(profile__city__iexact=city) | Q(profile__city__isnull=True) | Q(profile__city__exact="")
        )
    else:
        qs = qs.filter(Q(profile__city__isnull=True) | Q(profile__city__exact=""))

    return qs


def _as_dt(date_obj, time_obj):
    # Build timezone-aware datetime in current timezone
    tz = timezone.get_current_timezone()
    return timezone.make_aware(datetime.combine(date_obj, time_obj), tz)


class Command(BaseCommand):
    help = "Auto-update blood campaign statuses and send in-app notifications."

    def handle(self, *args, **options):
        now = timezone.localtime(timezone.now())
        today = now.date()

        # Only process relevant campaigns
        qs = (
            BloodCampaign.objects
            .select_related("organization")
            .filter(organization__status="APPROVED")
            .exclude(status="CANCELLED")
            .filter(status__in=["UPCOMING", "ONGOING"])
        )

        started = 0
        completed = 0

        for camp in qs:
            start_t = camp.start_time or time(0, 0)
            end_t = camp.end_time or time(23, 59, 59)

            start_dt = _as_dt(camp.date, start_t)
            end_dt = _as_dt(camp.date, end_t)

            # If campaign date is in the past -> complete it
            if camp.date < today and camp.status != "COMPLETED":
                camp.status = "COMPLETED"
                camp.save(update_fields=["status"])
                completed += 1

                users_qs = _audience_for_campaign(camp)
                title = "Blood Donation Camp Completed"
                body = f"{camp.organization.name} camp '{camp.title}' has been completed."
                url = "/blood/campaigns/"
                broadcast_inapp(users_qs, title=title, body=body, url=url, level="INFO")
                continue

            # same-day transitions
            if now >= end_dt:
                if camp.status != "COMPLETED":
                    camp.status = "COMPLETED"
                    camp.save(update_fields=["status"])
                    completed += 1

                    users_qs = _audience_for_campaign(camp)
                    title = "Blood Donation Camp Completed"
                    body = f"{camp.organization.name} camp '{camp.title}' has been completed."
                    url = "/blood/campaigns/"
                    broadcast_inapp(users_qs, title=title, body=body, url=url, level="INFO")

            elif now >= start_dt:
                if camp.status != "ONGOING":
                    camp.status = "ONGOING"
                    camp.save(update_fields=["status"])
                    started += 1

                    users_qs = _audience_for_campaign(camp)
                    title = "Blood Donation Camp Started"
                    body = f"{camp.organization.name} camp '{camp.title}' is now ONGOING at {camp.venue_name} ({_campaign_city(camp) or '—'})."
                    url = "/blood/campaigns/"
                    broadcast_inapp(users_qs, title=title, body=body, url=url, level="SUCCESS")

        self.stdout.write(f"Campaigns started: {started}, completed: {completed}")