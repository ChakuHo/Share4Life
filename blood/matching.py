import math
from accounts.models import CustomUser
from blood.eligibility import is_eligible


# -------- Blood compatibility (donor groups allowed for recipient) --------
COMPATIBLE_DONORS = {
    "O-": {"O-"},
    "O+": {"O-", "O+"},
    "A-": {"O-", "A-"},
    "A+": {"O-", "O+", "A-", "A+"},
    "B-": {"O-", "B-"},
    "B+": {"O-", "O+", "B-", "B+"},
    "AB-": {"O-", "A-", "B-", "AB-"},
    "AB+": {"O-", "O+", "A-", "A+", "B-", "B+", "AB-", "AB+"},
}


# -------- City normalization / synonyms --------
CITY_CANON = {
    "ktm": "kathmandu",
    "kathmandu": "kathmandu",
    "kathmandu city": "kathmandu",
    "kathmandu valley": "kathmandu",

    "lalitpur": "lalitpur",
    "patan": "lalitpur",
    "lalitpur city": "lalitpur",

    "bhaktapur": "bhaktapur",
    "bkt": "bhaktapur",
}

CANON_ALIASES = {
    "kathmandu": {"kathmandu", "ktm", "kathmandu city", "kathmandu valley"},
    "lalitpur": {"lalitpur", "patan", "lalitpur city"},
    "bhaktapur": {"bhaktapur", "bkt"},
}


def canonical_city(value: str) -> str:
    v = (value or "").strip().lower()
    v = " ".join(v.split())
    return CITY_CANON.get(v, v)


def city_aliases(value: str):
    canon = canonical_city(value)
    return CANON_ALIASES.get(canon, {canon})


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def eligible_donors_queryset():
    return (
        CustomUser.objects
        .filter(is_active=True, is_donor=True)
        .select_related("profile")
    )


def blood_group_allowed(req_blood_group: str, donor_blood_group: str) -> bool:
    allowed = COMPATIBLE_DONORS.get((req_blood_group or "").strip().upper())
    if not allowed:
        return False
    return (donor_blood_group or "").strip().upper() in allowed


def match_city(req):
    req_city = (req.location_city or "").strip()
    if not req_city:
        return []

    aliases = city_aliases(req_city)

    # pull a reasonable donor set by city aliases (DB filter), then validate in python
    qs = eligible_donors_queryset().filter(profile__city__isnull=False)
    qs = qs.filter(profile__city__iregex=r".*")  # keeps qs chain safe

    # we can’t easily OR iexact many times without Q-building; simplest: python filter
    donors = []
    for u in qs:
        u_city = canonical_city(getattr(u.profile, "city", "") or "")
        if u_city in {canonical_city(a) for a in aliases}:
            # eligibility + blood compatibility
            if is_eligible(u) and blood_group_allowed(req.blood_group, getattr(u.profile, "blood_group", "")):
                donors.append(u)

    return donors


def match_radius(req, radius_km: float):
    # require request coords
    if getattr(req, "latitude", None) is None or getattr(req, "longitude", None) is None:
        return []

    qs = eligible_donors_queryset()
    donors = []
    for u in qs:
        if not is_eligible(u):
            continue

        # blood compatibility
        if not blood_group_allowed(req.blood_group, getattr(u.profile, "blood_group", "")):
            continue

        lat = getattr(u.profile, "latitude", None)
        lon = getattr(u.profile, "longitude", None)
        if lat is None or lon is None:
            continue

        if haversine_km(req.latitude, req.longitude, lat, lon) <= radius_km:
            donors.append(u)

    return donors


def match_city_then_radius(req):
    # 1) City first
    donors = match_city(req)
    if donors:
        return donors

    # 2) fallback radius: 5km then 10km
    donors_5 = match_radius(req, 5)
    if donors_5:
        return donors_5

    donors_10 = match_radius(req, 10)
    return donors_10