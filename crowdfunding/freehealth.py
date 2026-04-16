# crowdfunding/freehealth.py
from __future__ import annotations

import requests

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.http import require_GET


def _get_setting(name: str, default):
    return getattr(settings, name, default)


def _extract_items(raw):
    """
    API response can be:
      - list[dict]
      - dict with keys like: results / data / items / organizations
    """
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for k in ("results", "data", "items", "organizations"):
            if k in raw and isinstance(raw[k], list):
                return raw[k]
    return []


def _norm_str(v) -> str:
    return " ".join(str(v or "").strip().split())


def _to_int_safe(v):
    try:
        if v is None or v == "":
            return None
        return int(v)
    except Exception:
        return None


def _pick_first(d: dict, keys):
    if not isinstance(d, dict):
        return ""
    for k in keys:
        if k in d:
            v = d.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
            if v not in (None, "") and not isinstance(v, (dict, list)):
                return str(v)
    return ""


def _guess_by_key_contains(d: dict, contains_any):
    if not isinstance(d, dict):
        return ""
    contains_any = [c.lower() for c in contains_any]
    for k, v in d.items():
        lk = str(k).lower()
        if any(c in lk for c in contains_any):
            if isinstance(v, str) and v.strip():
                return v.strip()
            if v not in (None, "") and not isinstance(v, (dict, list)):
                return str(v)
    return ""


def _normalize_org(o: dict) -> dict:
    """
    Precise mapping for MoHP FreeHealth organizations API
    (based on observed keys: health_facility_name, contact_person, contact_number, ...)

    Also contains a fallback heuristic mapping so it doesn't break if API changes.
    """
    if not isinstance(o, dict):
        return {}

    # ---- Precise known keys (best) ----
    if "health_facility_name" in o or "hf_uid" in o:
        return {
            "id": _pick_first(o, ["hf_uid", "id"]),
            "name": _pick_first(o, ["health_facility_name"]),
            "province": _pick_first(o, ["province_name"]),
            "district": _pick_first(o, ["district_name"]),
            "municipality": _pick_first(o, ["palika_name"]),
            "ward": _pick_first(o, ["ward_name"]),
            "address": _pick_first(o, ["hospital_address"]),
            "contact_person": _pick_first(o, ["contact_person"]),
            "phone": _pick_first(o, ["contact_number"]),  # THIS is the actual phone number
            "ownership_type": _pick_first(o, ["ownership_type"]),
            "public_nonpublic": _pick_first(o, ["public_nonpublic"]),
            "sanction_beds": _to_int_safe(o.get("sanction_beds")),
            "free_beds": _to_int_safe(o.get("free_beds")),
            "active_beds": _to_int_safe(o.get("active_beds")),
            "available_beds": _to_int_safe(o.get("available_beds")),
            "_raw_keys": list(o.keys()),
        }

    # ---- Fallback mapping (if API changes) ----
    org_id = _pick_first(o, ["id", "organization_id", "orgId", "org_id"])
    name = _pick_first(o, ["name", "organization_name", "hospital_name", "title"])
    if not name:
        name = _guess_by_key_contains(o, ["name", "hospital", "facility", "org"])

    phone = _pick_first(o, ["phone", "phone_number", "contact_number", "contact_phone", "mobile"])
    contact_person = _pick_first(o, ["contact_person", "person", "contact_name"])

    province = _pick_first(o, ["province", "province_name", "state"])
    district = _pick_first(o, ["district", "district_name"])
    municipality = _pick_first(o, ["municipality", "municipality_name", "palika_name", "local_level"])
    ward = _pick_first(o, ["ward", "ward_name", "ward_no"])
    address = _pick_first(o, ["address", "hospital_address", "full_address"])

    return {
        "id": org_id,
        "name": name,
        "province": province,
        "district": district,
        "municipality": municipality,
        "ward": ward,
        "address": address,
        "contact_person": contact_person,
        "phone": phone,
        "ownership_type": _pick_first(o, ["ownership_type"]),
        "public_nonpublic": _pick_first(o, ["public_nonpublic"]),
        "sanction_beds": _to_int_safe(o.get("sanction_beds")),
        "free_beds": _to_int_safe(o.get("free_beds")),
        "active_beds": _to_int_safe(o.get("active_beds")),
        "available_beds": _to_int_safe(o.get("available_beds")),
        "_raw_keys": list(o.keys()),
    }


def _matches_q(item: dict, q: str) -> bool:
    if not q:
        return True
    q = q.lower().strip()
    hay = " | ".join([
        _norm_str(item.get("name")),
        _norm_str(item.get("province")),
        _norm_str(item.get("district")),
        _norm_str(item.get("municipality")),
        _norm_str(item.get("ward")),
        _norm_str(item.get("address")),
        _norm_str(item.get("phone")),
        _norm_str(item.get("contact_person")),
        _norm_str(item.get("ownership_type")),
        _norm_str(item.get("public_nonpublic")),
        _norm_str(item.get("available_beds")),
        _norm_str(item.get("free_beds")),
    ]).lower()
    return q in hay


@require_GET
def freehealth_organizations(request):
    enabled = bool(_get_setting("S4L_FREEHEALTH_ENABLED", True))
    if not enabled:
        return JsonResponse({"ok": False, "error": "FreeHealth integration disabled."}, status=404)

    api_url = _get_setting("S4L_FREEHEALTH_ORGS_API_URL", "https://freehealth.mohp.gov.np/api/organizations")
    cache_seconds = int(_get_setting("S4L_FREEHEALTH_CACHE_SECONDS", 60 * 60))
    timeout = float(_get_setting("S4L_FREEHEALTH_TIMEOUT_SECONDS", 8))

    q = _norm_str(request.GET.get("q", ""))
    debug = (request.GET.get("debug") or "").strip() in ("1", "true", "yes", "on")

    try:
        limit = int(request.GET.get("limit") or 30)
    except Exception:
        limit = 30
    limit = max(1, min(limit, 200))

    cache_key = "s4l:freehealth:orgs:v3"
    cached_payload = cache.get(cache_key)

    from_cache = True
    if cached_payload is None:
        from_cache = False
        try:
            resp = requests.get(
                api_url,
                headers={
                    "User-Agent": "Share4Life-LocalDemo/1.0",
                    "Accept": "application/json,text/plain,*/*",
                },
                timeout=timeout,
            )
            resp.raise_for_status()
            cached_payload = resp.json()
            cache.set(cache_key, cached_payload, timeout=cache_seconds)
        except Exception as e:
            return JsonResponse({
                "ok": False,
                "error": f"Failed to fetch FreeHealth data: {e}",
                "api_url": api_url,
            }, status=502)

    raw_items = _extract_items(cached_payload)

    normalized = []
    for o in raw_items:
        item = _normalize_org(o)
        if item:
            normalized.append(item)

    filtered = [it for it in normalized if _matches_q(it, q)]
    total = len(filtered)
    filtered = filtered[:limit]

    if not debug:
        for it in filtered:
            it.pop("_raw_keys", None)

    out = {
        "ok": True,
        "api_url": api_url,
        "from_cache": from_cache,
        "q": q,
        "count": total,
        "limit": limit,
        "items": filtered,
    }

    if debug and filtered:
        out["sample_keys"] = filtered[0].get("_raw_keys", [])

    return JsonResponse(out)