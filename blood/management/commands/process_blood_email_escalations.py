from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.models import CustomUser
from communication.models import NotificationPreference, QueuedEmail
from communication.services import broadcast_inapp
from blood.models import (
    DonorResponse,
    BloodDonation,
    BloodEmailEscalationState,
    BloodRequestEmailedUser,
)
from blood.matching import canonical_city, nearby_city_canons, match_city, match_radius


class Command(BaseCommand):
    help = "Queue staged EMAIL notifications for blood requests (emergency and non-emergency)."

    def handle(self, *args, **options):
        if not getattr(settings, "ENABLE_SCHEDULED_EMAILS", True):
            self.stdout.write("Scheduled emails are disabled.")
            return

        now = timezone.now()
        site_base = (getattr(settings, "SITE_BASE_URL", "") or "").rstrip("/")

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
        total_queued = 0
        total_skipped_duplicates = 0

        for st in states:
            req = st.request

            # stop if request is closed
            if (not req.is_active) or req.status in ("FULFILLED", "CANCELLED"):
                st.stage = "DONE"
                st.is_done = True
                st.last_run_at = now
                st.next_run_at = None
                st.save(update_fields=["stage", "is_done", "last_run_at", "next_run_at", "updated_at"])
                continue

            # stop if someone accepted or donation exists
            if (
                DonorResponse.objects.filter(request=req, status="ACCEPTED").exists()
                or BloodDonation.objects.filter(request=req).exists()
            ):
                st.stage = "DONE"
                st.is_done = True
                st.last_run_at = now
                st.next_run_at = None
                st.save(update_fields=["stage", "is_done", "last_run_at", "next_run_at", "updated_at"])
                continue

            recipients = []

            if st.stage == "CITY":
                recipients = match_city(req)

            elif st.stage == "NEARBY":
                req_canon = canonical_city(req.location_city)
                near_canons = nearby_city_canons(req_canon)
                if near_canons:
                    qs = (
                        CustomUser.objects
                        .filter(is_active=True, is_donor=True)
                        .select_related("profile")
                        .filter(profile__city_canon__in=near_canons)
                    )
                    recipients = list(qs)
                else:
                    recipients = []

            elif st.stage == "RADIUS_10":
                recipients = match_radius(req, 10)

            ids = [u.id for u in recipients]
            users_qs = CustomUser.objects.filter(id__in=ids, is_active=True, is_donor=True)

            if req.created_by_id:
                users_qs = users_qs.exclude(id=req.created_by_id)

            responded_ids = DonorResponse.objects.filter(request=req).values_list("donor_id", flat=True)
            users_qs = users_qs.exclude(id__in=responded_ids)

            user_rows = list(users_qs.values("id", "email"))
            user_ids = [row["id"] for row in user_rows]

            if user_rows:
                title = "URGENT Blood Request" if req.is_emergency else "Blood Request"
                level = "DANGER" if req.is_emergency else "INFO"
                category = "EMERGENCY" if req.is_emergency else "BLOOD"
                url = req.get_absolute_url()

                body = (
                    f"Need {req.blood_group} in {req.location_city} at {req.hospital_name}. "
                    f"Units: {req.units_needed}. Contact: {req.contact_phone}"
                )

                open_url = f"{site_base}{url}" if site_base and url.startswith("/") else url
                email_body = body + f"\n\nOpen: {open_url}"

                # in-app notifications
                broadcast_inapp(
                    CustomUser.objects.filter(id__in=user_ids),
                    title=title,
                    body=body,
                    url=url,
                    level=level,
                    category=category
                )

                prefs_map = {
                    p.user_id: p
                    for p in NotificationPreference.objects.filter(user_id__in=user_ids)
                }

                queued_now = 0
                skipped_now = 0

                for row in user_rows:
                    uid = row["id"]
                    email = (row["email"] or "").strip()

                    if not email:
                        continue

                    pref = prefs_map.get(uid)
                    if pref and (not pref.email_enabled):
                        continue
                    if pref and pref.email_emergency_only and category != "EMERGENCY":
                        continue

                    try:
                        with transaction.atomic():
                            obj, created = BloodRequestEmailedUser.objects.get_or_create(
                                request=req,
                                user_id=uid,
                            )
                            if not created:
                                skipped_now += 1
                                continue

                            QueuedEmail.objects.create(
                                user_id=uid,
                                to_email=email,
                                subject=title,
                                body=email_body,
                                status="PENDING",
                            )
                            queued_now += 1

                    except IntegrityError:
                        skipped_now += 1
                        continue

                total_queued += queued_now
                total_skipped_duplicates += skipped_now

            st.last_run_at = now

            if req.is_emergency:
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

        self.stdout.write(
            self.style.SUCCESS(
                f"Processed states: {processed}, queued emails: {total_queued}, skipped duplicates: {total_skipped_duplicates}"
            )
        )