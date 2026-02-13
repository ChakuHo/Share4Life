from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.db import IntegrityError
from django.db.models import F
from django.utils import timezone

from .matching import match_city, match_radius, haversine_km
from .models import BloodDonorPingLog, DonorResponse


def _send_ping(req, donors, stage: str) -> int:
    """
    Send websocket ping to donors.

    Behavior:
      - If donor already responded to this request (any status), never ping again.
      - If donor ignored previous pings, we can reping after cooldown (limited by max repings).
      - PingLog row is updated (last_ping_at + ping_count).
      - Optional: create a persistent in-app Notification on FIRST ping
        so offline donors still see the request after login.
    """
    channel_layer = get_channel_layer()
    if not donors:
        return 0

    donor_ids = [u.id for u in donors]
    now = timezone.now()

    cooldown = int(getattr(settings, "S4L_DONOR_REPING_COOLDOWN_SECONDS", 180))
    max_repings = int(getattr(settings, "S4L_DONOR_MAX_REPINGS_PER_REQUEST", 3))

    # Donors who already responded -> never ping again
    responded_ids = set(
        DonorResponse.objects
        .filter(request=req, donor_id__in=donor_ids)
        .values_list("donor_id", flat=True)
    )

    # ping logs (for cooldown + count)
    logs = {
        row["donor_id"]: row
        for row in (
            BloodDonorPingLog.objects
            .filter(request=req, donor_id__in=donor_ids)
            .values("id", "donor_id", "last_ping_at", "ping_count")
        )
    }

    sent = 0

    for u in donors:
        if u.id in responded_ids:
            continue

        log = logs.get(u.id)
        if log:
            last_ping_at = log.get("last_ping_at")
            ping_count = int(log.get("ping_count") or 0)

            # cooldown check
            if last_ping_at and (now - last_ping_at).total_seconds() < cooldown:
                continue

            # max repings check
            if ping_count >= max_repings:
                continue

        dist = None
        try:
            if req.latitude is not None and req.longitude is not None:
                lat = getattr(u.profile, "latitude", None)
                lon = getattr(u.profile, "longitude", None)
                if lat is not None and lon is not None:
                    dist = round(haversine_km(req.latitude, req.longitude, lat, lon), 2)
        except Exception:
            dist = None

        payload = {
            "type": "DONOR_PING",
            "request_id": req.id,
            "blood_group": req.blood_group,
            "units_needed": req.units_needed,
            "city": req.location_city,
            "hospital": req.hospital_name,
            "is_emergency": bool(req.is_emergency),
            "detail_url": req.get_absolute_url(),
            "distance_km": dist,
            "stage": stage,  # CITY / RADIUS_5 / RADIUS_10
        }

        # Fire-and-forget websocket ping (if donor offline, WS message won't be queued)
        async_to_sync(channel_layer.group_send)(
            f"donor_{u.id}",
            {"type": "donor_ping", "data": payload}
        )

        # Log ping + persistent notification on FIRST ping
        try:
            obj, created = BloodDonorPingLog.objects.get_or_create(
                request=req,
                donor=u,
                defaults={
                    "stage": stage,
                    "last_ping_at": now,
                    "ping_count": 1,
                }
            )

            if not created:
                BloodDonorPingLog.objects.filter(pk=obj.pk).update(
                    stage=stage,
                    last_ping_at=now,
                    ping_count=F("ping_count") + 1,
                )


            # Create 1 in-app notification per request per donor (only on first ping),
            # so donors who were offline still see it in Notifications after login.
            if created:
                try:
                    from communication.models import Notification
                    Notification.objects.create(
                        user=u,
                        title="Emergency blood request match" if req.is_emergency else "Blood request match",
                        body=(
                            f"Need {req.blood_group} in {req.location_city} at {req.hospital_name}. "
                            f"Units: {req.units_needed}."
                        ),
                        url=req.get_absolute_url(),
                        level="DANGER" if req.is_emergency else "INFO",
                    )
                except Exception:
                    # don't break pings if communication app changes
                    pass

        except IntegrityError:
            # race condition safety
            pass

        sent += 1

    return sent


def push_ping_stage(req, stage: str) -> int:
    """
    stage: CITY / RADIUS_5 / RADIUS_10
    """
    if stage == "CITY":
        donors = match_city(req)
        return _send_ping(req, donors, stage="CITY")

    if stage == "RADIUS_5":
        donors = match_radius(req, 5)
        return _send_ping(req, donors, stage="RADIUS_5")

    if stage == "RADIUS_10":
        donors = match_radius(req, 10)
        return _send_ping(req, donors, stage="RADIUS_10")

    return 0


def push_ping_to_donors(req):
    """
    Old behavior: city then immediate radius fallback.
    Kept for compatibility.
    """
    n = push_ping_stage(req, "CITY")
    if n:
        return n

    n = push_ping_stage(req, "RADIUS_5")
    if n:
        return n

    return push_ping_stage(req, "RADIUS_10")


def push_request_event(request_id: int, data: dict):
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"blood_request_{request_id}",
        {"type": "request_event", "data": data}
    )