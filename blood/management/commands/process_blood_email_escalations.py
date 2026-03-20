from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import CustomUser
from communication.services import broadcast_inapp, queue_email_broadcast
from blood.models import (
    PublicBloodRequest,
    DonorResponse,
    BloodDonation,
    BloodEmailEscalationState,
    BloodRequestEmailedUser,
)
from blood.matching import canonical_city, nearby_city_canons, match_city, match_radius


class Command(BaseCommand):
    help = "Queue staged EMAIL notifications for blood requests (emergency and non-emergency)."

    def handle(self, *args, **options):
        now = timezone.now()

        states = (
            BloodEmailEscalationState.objects
            .select_related("request")
            .filter(is_done=False)
            .filter(next_run_at__isnull=False, next_run_at__lte=now)
            .order_by("next_run_at")[:200]
        )

        if not states:
            self.stdout.write("No email escalations due.")
            return

        processed = 0

        for st in states:
            req = st.request

            # stop if request closed
            if (not req.is_active) or req.status in ("FULFILLED", "CANCELLED"):
                st.stage = "DONE"
                st.is_done = True
                st.last_run_at = now
                st.next_run_at = None
                st.save(update_fields=["stage", "is_done", "last_run_at", "next_run_at", "updated_at"])
                continue

            # stop if someone already accepted OR donation already recorded
            if DonorResponse.objects.filter(request=req, status="ACCEPTED").exists() or BloodDonation.objects.filter(request=req).exists():
                st.stage = "DONE"
                st.is_done = True
                st.last_run_at = now
                st.next_run_at = None
                st.save(update_fields=["stage", "is_done", "last_run_at", "next_run_at", "updated_at"])
                continue

            # build recipient user list by stage
            recipients = []

            if st.stage == "CITY":
                recipients = match_city(req)

            elif st.stage == "NEARBY":
                req_canon = canonical_city(req.location_city)
                near_canons = nearby_city_canons(req_canon)
                if near_canons:
                    qs = CustomUser.objects.filter(is_active=True, is_donor=True).select_related("profile")
                    qs = qs.filter(profile__city_canon__in=near_canons)
                    recipients = list(qs)
                else:
                    recipients = []

            elif st.stage == "RADIUS_10":
                recipients = match_radius(req, 10)

            # turn list -> queryset
            ids = [u.id for u in recipients]
            users_qs = CustomUser.objects.filter(id__in=ids, is_active=True, is_donor=True)

            # exclude request owner
            if req.created_by_id:
                users_qs = users_qs.exclude(id=req.created_by_id)

            # exclude donors who already responded (any status)
            responded_ids = DonorResponse.objects.filter(request=req).values_list("donor_id", flat=True)
            users_qs = users_qs.exclude(id__in=responded_ids)

            # exclude already emailed users
            emailed_ids = BloodRequestEmailedUser.objects.filter(request=req).values_list("user_id", flat=True)
            users_qs = users_qs.exclude(id__in=emailed_ids)

            count = users_qs.count()

            if count:
                title = "URGENT Blood Request" if req.is_emergency else "Blood Request"
                level = "DANGER" if req.is_emergency else "INFO"
                category = "EMERGENCY" if req.is_emergency else "BLOOD"
                url = req.get_absolute_url()

                body = (
                    f"Need {req.blood_group} in {req.location_city} at {req.hospital_name}. "
                    f"Units: {req.units_needed}. Contact: {req.contact_phone}"
                )
                email_body = body + f"\n\nOpen: {url}"

                broadcast_inapp(users_qs, title=title, body=body, url=url, level=level, category=category)
                queue_email_broadcast(users_qs, subject=title, body=email_body, category=category)

                # dedupe store
                rows = [
                    BloodRequestEmailedUser(request=req, user_id=uid)
                    for uid in users_qs.values_list("id", flat=True)
                ]
                BloodRequestEmailedUser.objects.bulk_create(rows, ignore_conflicts=True)

            # schedule next stage
            st.last_run_at = now

            if req.is_emergency:
                # emergency escalates every 5 minutes
                if st.stage == "CITY":
                    st.stage = "NEARBY"
                    st.next_run_at = now + timedelta(minutes=5)
                elif st.stage == "NEARBY":
                    st.stage = "RADIUS_10"
                    st.next_run_at = now + timedelta(minutes=5)
                else:
                    st.stage = "DONE"
                    st.is_done = True
                    st.next_run_at = None
            else:
                # non-emergency escalates slowly (6h/12h/24h)
                if st.stage == "CITY":
                    st.stage = "NEARBY"
                    st.next_run_at = now + timedelta(hours=6)
                elif st.stage == "NEARBY":
                    st.stage = "RADIUS_10"
                    st.next_run_at = now + timedelta(hours=12)
                else:
                    st.stage = "DONE"
                    st.is_done = True
                    st.next_run_at = None

            st.save(update_fields=["stage", "next_run_at", "last_run_at", "is_done", "updated_at"])
            processed += 1

        self.stdout.write(self.style.SUCCESS(f"Processed email escalation states: {processed}"))