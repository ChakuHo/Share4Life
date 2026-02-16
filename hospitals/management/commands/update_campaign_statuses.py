from datetime import datetime, time

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone
from django.core.cache import cache

from accounts.models import CustomUser
from communication.services import broadcast_after_commit
from hospitals.models import BloodCampaign
from blood.matching import city_aliases


def _campaign_city(camp: BloodCampaign) -> str:
    return (camp.city or getattr(camp.organization, "city", "") or "").strip()


def _audience_for_campaign(camp: BloodCampaign):
    """
    Same-city matching using aliases (Patan->Lalitpur, KTM->Kathmandu etc)
    PLUS your existing fallback: include users with blank city.
    """
    city = _campaign_city(camp)
    qs = CustomUser.objects.filter(is_active=True).select_related("profile")

    if city:
        aliases = city_aliases(city)
        q = Q()
        for a in aliases:
            a = (a or "").strip()
            if a:
                q |= Q(profile__city__iexact=a) | Q(profile__city__icontains=a)

        qs = qs.filter(q | Q(profile__city__isnull=True) | Q(profile__city__exact=""))
    else:
        qs = qs.filter(Q(profile__city__isnull=True) | Q(profile__city__exact=""))

    return qs


def _as_dt(date_obj, time_obj):
    tz = timezone.get_current_timezone()
    return timezone.make_aware(datetime.combine(date_obj, time_obj), tz)


class Command(BaseCommand):
    help = "Auto-update blood campaign statuses and send notifications (in-app + queued email)."

    def handle(self, *args, **options):
        # Prevent overlapping executions (important with Task Scheduler)
        lock_key = "s4l:update_campaign_statuses:lock"
        if not cache.add(lock_key, 1, timeout=55):
            self.stdout.write("Another update_campaign_statuses run is active. Exiting.")
            return

        try:
            now = timezone.localtime(timezone.now())
            today = now.date()

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

                # Past date -> complete
                if camp.date < today and camp.status != "COMPLETED":
                    camp.status = "COMPLETED"
                    camp.save(update_fields=["status"])
                    completed += 1

                    users_qs = _audience_for_campaign(camp)
                    title = "Blood Donation Camp Completed"
                    body = f"{camp.organization.name} camp '{camp.title}' has been completed."
                    url = "/blood/campaigns/"
                    broadcast_after_commit(
                        users_qs,
                        title=title,
                        body=body,
                        url=url,
                        level="INFO",
                        email_subject=title,
                        email_body=body + "\n\nOpen: " + url,
                        category="CAMPAIGN",
                    )
                    continue

                # Same-day transitions
                if now >= end_dt:
                    if camp.status != "COMPLETED":
                        camp.status = "COMPLETED"
                        camp.save(update_fields=["status"])
                        completed += 1

                        users_qs = _audience_for_campaign(camp)
                        title = "Blood Donation Camp Completed"
                        body = f"{camp.organization.name} camp '{camp.title}' has been completed."
                        url = "/blood/campaigns/"
                        broadcast_after_commit(
                            users_qs,
                            title=title,
                            body=body,
                            url=url,
                            level="INFO",
                            email_subject=title,
                            email_body=body + "\n\nOpen: " + url,
                            category="CAMPAIGN",
                        )

                elif now >= start_dt:
                    if camp.status != "ONGOING":
                        camp.status = "ONGOING"
                        camp.save(update_fields=["status"])
                        started += 1

                        users_qs = _audience_for_campaign(camp)
                        title = "Blood Donation Camp Started"
                        body = (
                            f"{camp.organization.name} camp '{camp.title}' is now ONGOING "
                            f"at {camp.venue_name} ({_campaign_city(camp) or '—'})."
                        )
                        url = "/blood/campaigns/"
                        broadcast_after_commit(
                            users_qs,
                            title=title,
                            body=body,
                            url=url,
                            level="SUCCESS",
                            email_subject=title,
                            email_body=body + "\n\nOpen: " + url,
                            category="CAMPAIGN",
                        )

            self.stdout.write(self.style.SUCCESS(f"Campaigns started: {started}, completed: {completed}"))

        finally:
            cache.delete(lock_key)