from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from blood.models import (
    PublicBloodRequest,
    BloodEscalationState,
    DonorResponse,
    BloodDonation,
)
from blood.realtime import push_ping_stage

from communication.models import Notification


def _notify_user(user, title, body="", url="", level="INFO"):
    if not user:
        return
    Notification.objects.create(user=user, title=title, body=body, url=url, level=level)


def _notify_orgs_in_city(city: str, title: str, body: str, url: str = ""):
    """
    Notify all approved org members in same city (ADMIN/VERIFIER/STAFF).
    """
    try:
        from hospitals.models import Organization, OrganizationMembership
    except Exception:
        return

    city = (city or "").strip()
    if not city:
        return

    orgs = Organization.objects.filter(status="APPROVED", city__iexact=city)
    if not orgs.exists():
        return

    members = (
        OrganizationMembership.objects
        .filter(
            organization__in=orgs,
            is_active=True,
            role__in=["ADMIN", "VERIFIER", "STAFF"],
        )
        .select_related("user")
    )

    for m in members:
        Notification.objects.create(user=m.user, title=title, body=body, url=url, level="INFO")


class Command(BaseCommand):
    help = "Escalate emergency blood requests with reping loop: CITY -> 5km -> 10km -> ORG -> LOOP"

    def handle(self, *args, **options):
        now = timezone.now()

        # NEW: how long to keep repinging before stopping (does NOT close the request)
        max_minutes = int(getattr(settings, "S4L_EMERGENCY_ESCALATION_MAX_MINUTES", 60))
        loop_interval_minutes = int(getattr(settings, "S4L_EMERGENCY_REPING_INTERVAL_MINUTES", 1))
        too_old_cutoff = now - timedelta(minutes=max_minutes)

        reqs = (
            PublicBloodRequest.objects
            .filter(
                is_emergency=True,
                is_active=True,
                status__in=["OPEN", "IN_PROGRESS"],
            )
            .exclude(verification_status="REJECTED")
        )

        updated = 0

        for req in reqs.iterator():
            state, _ = BloodEscalationState.objects.get_or_create(
                request=req,
                defaults={"stage": "CITY", "next_run_at": now},
            )

            if state.is_done:
                continue

            if state.next_run_at and state.next_run_at > now:
                continue

            # Stop if someone accepted or donation started or request closed
            accepted_exists = DonorResponse.objects.filter(request=req, status="ACCEPTED").exists()
            donation_exists = BloodDonation.objects.filter(request=req).exists()
            if accepted_exists or donation_exists or (not req.is_active) or req.status in ("FULFILLED", "CANCELLED"):
                state.stage = "DONE"
                state.is_done = True
                state.last_run_at = now
                state.next_run_at = None
                state.save(update_fields=["stage", "is_done", "last_run_at", "next_run_at", "updated_at"])
                continue

            # NEW: stop escalation/reping if too old
            if req.created_at and req.created_at < too_old_cutoff:
                state.stage = "DONE"
                state.is_done = True
                state.last_run_at = now
                state.next_run_at = None
                state.save(update_fields=["stage", "is_done", "last_run_at", "next_run_at", "updated_at"])
                continue

            has_gps = (req.latitude is not None and req.longitude is not None)

            with transaction.atomic():
                state.last_run_at = now

                # CITY -> RADIUS_5
                if state.stage == "CITY":
                    if has_gps:
                        sent = push_ping_stage(req, "RADIUS_5")
                        state.stage = "RADIUS_5"
                        state.schedule_next(minutes=1)

                        if req.created_by_id:
                            if sent > 0:
                                _notify_user(
                                    req.created_by,
                                    "Emergency escalation started",
                                    "We are now alerting donors within 5km.",
                                    url=req.get_absolute_url(),
                                    level="INFO",
                                )
                            else:
                                _notify_user(
                                    req.created_by,
                                    "Emergency escalation update",
                                    "No nearby GPS donors found within 5km yet. We will expand further.",
                                    url=req.get_absolute_url(),
                                    level="WARNING",
                                )
                    else:
                        state.stage = "ORG"
                        state.schedule_next(minutes=1)
                        if req.created_by_id:
                            _notify_user(
                                req.created_by,
                                "Emergency escalation started",
                                "GPS not available. We will notify nearby institutions in your city.",
                                url=req.get_absolute_url(),
                                level="INFO",
                            )

                # RADIUS_5 -> RADIUS_10
                elif state.stage == "RADIUS_5":
                    if has_gps:
                        sent = push_ping_stage(req, "RADIUS_10")
                        state.stage = "RADIUS_10"
                        state.schedule_next(minutes=1)

                        if req.created_by_id:
                            if sent > 0:
                                _notify_user(
                                    req.created_by,
                                    "Emergency escalation update",
                                    "We are now alerting donors within 10km.",
                                    url=req.get_absolute_url(),
                                    level="INFO",
                                )
                            else:
                                _notify_user(
                                    req.created_by,
                                    "Emergency escalation update",
                                    "No GPS donors found within 10km yet. We will notify institutions next.",
                                    url=req.get_absolute_url(),
                                    level="WARNING",
                                )
                    else:
                        state.stage = "ORG"
                        state.schedule_next(minutes=1)

                # RADIUS_10 -> ORG  (FIX: actually ping 10km here too)
                elif state.stage == "RADIUS_10":
                    if has_gps:
                        push_ping_stage(req, "RADIUS_10")  # IMPORTANT FIX
                    state.stage = "ORG"
                    state.schedule_next(minutes=1)

                # ORG -> LOOP (do NOT finish here)
                elif state.stage == "ORG":
                    _notify_orgs_in_city(
                        req.location_city,
                        "Emergency blood request needs attention",
                        f"Emergency request #{req.id} needs verification/routing help.",
                        url=req.get_absolute_url(),
                    )
                    state.stage = "LOOP"
                    state.schedule_next(minutes=loop_interval_minutes)

                # LOOP: keep repinging until accepted/closed/expired
                elif state.stage == "LOOP":
                    # Reping city donors too (helps donors who were offline before)
                    push_ping_stage(req, "CITY")
                    if has_gps:
                        push_ping_stage(req, "RADIUS_10")
                    state.schedule_next(minutes=loop_interval_minutes)

                else:
                    state.stage = "DONE"
                    state.is_done = True
                    state.next_run_at = None

                state.save(update_fields=["stage", "next_run_at", "last_run_at", "is_done", "updated_at"])
                updated += 1

        self.stdout.write(self.style.SUCCESS(f"Escalation complete. Updated states: {updated}"))