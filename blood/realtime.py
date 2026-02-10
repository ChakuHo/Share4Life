from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .matching import match_city_then_radius, haversine_km


def push_ping_to_donors(req):
    channel_layer = get_channel_layer()
    donors = match_city_then_radius(req)

    for u in donors:
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

            # slug URL (canonical)
            "detail_url": req.get_absolute_url(),

            "distance_km": dist,
        }

        async_to_sync(channel_layer.group_send)(
            f"donor_{u.id}",
            {"type": "donor_ping", "data": payload}
        )

    return len(donors)


def push_request_event(request_id: int, data: dict):
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"blood_request_{request_id}",
        {"type": "request_event", "data": data}
    )