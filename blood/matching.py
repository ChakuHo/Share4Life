import math
from datetime import timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from accounts.models import CustomUser
from blood.eligibility import is_eligible
from .models import BloodDonation


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


def strict_exact_match_enabled() -> bool:
    return bool(getattr(settings, "S4L_BLOOD_STRICT_MATCH", True))


def strict_allow_o_negative() -> bool:
    return bool(getattr(settings, "S4L_BLOOD_STRICT_ALLOW_O_NEG", True))


def allowed_donor_groups_for_request(req_blood_group: str) -> set:
    """
    Returns allowed donor blood groups for a request.

    Modes:
      - Strict mode (S4L_BLOOD_STRICT_MATCH=True):
          allow ONLY exact match, plus OPTIONAL universal donor exception for O-
      - Compatibility mode (S4L_BLOOD_STRICT_MATCH=False):
          allow COMPATIBLE_DONORS matrix (original behavior)
    """
    bg = (req_blood_group or "").strip().upper()
    if not bg:
        return set()

    if strict_exact_match_enabled():
        allowed = {bg}
        # Universal donor exception (production-friendly)
        if strict_allow_o_negative():
            allowed.add("O-")
        return allowed

    return COMPATIBLE_DONORS.get(bg, set())


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

NEIGHBOR_GROUPS = [
    {"kathmandu", "lalitpur", "bhaktapur"},
]


def nearby_city_canons(canon: str):
    canon = (canon or "").strip().lower()
    if not canon:
        return []

    for grp in NEIGHBOR_GROUPS:
        if canon in grp:
            return sorted(list(grp - {canon}))
    return []


def canonical_city(value: str) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return ""

    raw = " ".join(raw.split())
    raw = raw.replace("|", ",").replace("/", ",").replace(";", ",")

    if raw in CITY_CANON:
        return CITY_CANON[raw]

    parts = [p.strip() for p in raw.split(",") if p.strip()]

    for p in reversed(parts):
        if p in CITY_CANON:
            return CITY_CANON[p]
        toks = p.split()
        if toks:
            last = toks[-1]
            if last in CITY_CANON:
                return CITY_CANON[last]

    toks = raw.split()
    if toks:
        last = toks[-1]
        if last in CITY_CANON:
            return CITY_CANON[last]

    return CITY_CANON.get(raw, raw)


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
    allowed = allowed_donor_groups_for_request(req_blood_group)
    if not allowed:
        return False
    return (donor_blood_group or "").strip().upper() in allowed


def match_city(req):
    req_city = (req.location_city or "").strip()
    if not req_city:
        return []

    aliases = city_aliases(req_city)
    canon_targets = {canonical_city(a) for a in aliases if a}
    now = timezone.now()

    allowed_groups = allowed_donor_groups_for_request(req.blood_group)
    if not allowed_groups:
        return []

    qs = (
        eligible_donors_queryset()
        .filter(profile__blood_group__in=list(allowed_groups))
        .exclude(profile__city__exact="")
    )

    q_city = Q(profile__city_canon__in=list(canon_targets))
    for a in aliases:
        if a:
            q_city |= Q(profile__city__iexact=a)

    qs = qs.filter(q_city)

    # eligibility using cached next_eligible_at (fast)
    qs = qs.filter(Q(profile__next_eligible_at__isnull=True) | Q(profile__next_eligible_at__lte=now))

    return list(qs)


def match_radius(req, radius_km: float):
    if getattr(req, "latitude", None) is None or getattr(req, "longitude", None) is None:
        return []

    donors = []
    qs = eligible_donors_queryset()

    for u in qs:
        if not is_eligible(u):
            continue

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
    donors = match_city(req)
    if donors:
        return donors

    donors_5 = match_radius(req, 5)
    if donors_5:
        return donors_5

    donors_10 = match_radius(req, 10)
    return donors_10