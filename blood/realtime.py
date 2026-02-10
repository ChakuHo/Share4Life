from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import IntegrityError

from .matching import match_city, match_radius, haversine_km
from .models import BloodDonorPingLog


def _send_ping(req, donors, stage: str) -> int:
    """
    Send websocket ping to donors, skipping donors already pinged for this request.
    Logs pings to DB to prevent duplicates (even across escalation stages).
    """
    channel_layer = get_channel_layer()
    if not donors:
        return 0

    donor_ids = [u.id for u in donors]
    already = set(
        BloodDonorPingLog.objects
        .filter(request=req, donor_id__in=donor_ids)
        .values_list("donor_id", flat=True)
    )

    sent = 0
    for u in donors:
        if u.id in already:
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

        async_to_sync(channel_layer.group_send)(
            f"donor_{u.id}",
            {"type": "donor_ping", "data": payload}
        )

        # Log ping (avoid crash on race conditions)
        try:
            BloodDonorPingLog.objects.create(request=req, donor=u, stage=stage)
        except IntegrityError:
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


# Backward compatible (your old behavior still works)
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