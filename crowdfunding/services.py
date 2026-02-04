import requests
from django.conf import settings
from django.utils import timezone
from communication.models import Notification, QueuedEmail


def notify_user(user, title, body="", url="", level="INFO", email_subject=None, email_body=None):
    if not user:
        return
    Notification.objects.create(user=user, title=title, body=body, url=url, level=level)
    if email_subject and email_body and user.email:
        QueuedEmail.objects.create(user=user, to_email=user.email, subject=email_subject, body=email_body)


def _safe_json(resp):
    try:
        return resp.json()
    except Exception:
        txt = (resp.text or "")[:600]
        raise RuntimeError(f"Non-JSON response. HTTP {resp.status_code}. Body: {txt}")


def khalti_initiate(amount_npr, purchase_order_id, purchase_order_name, return_url, customer_info=None):
    if not settings.KHALTI_SECRET_KEY:
        raise RuntimeError("KHALTI_SECRET_KEY missing")

    url = settings.KHALTI_BASE_URL.rstrip("/") + "/epayment/initiate/"
    payload = {
        "return_url": return_url,
        "website_url": settings.KHALTI_WEBSITE_URL,
        "amount": int(float(amount_npr) * 100),
        "purchase_order_id": str(purchase_order_id),
        "purchase_order_name": purchase_order_name[:150],
    }
    if customer_info:
        payload["customer_info"] = customer_info

    resp = requests.post(
        url,
        json=payload,
        headers={"Authorization": f"Key {settings.KHALTI_SECRET_KEY}"},
        timeout=25,
    )
    data = _safe_json(resp)
    if resp.status_code >= 400:
        raise RuntimeError(f"Khalti initiate failed. HTTP {resp.status_code}. {data}")
    return data


def khalti_lookup(pidx):
    if not settings.KHALTI_SECRET_KEY:
        raise RuntimeError("KHALTI_SECRET_KEY missing")

    url = settings.KHALTI_BASE_URL.rstrip("/") + "/epayment/lookup/"
    resp = requests.post(
        url,
        json={"pidx": pidx},
        headers={"Authorization": f"Key {settings.KHALTI_SECRET_KEY}"},
        timeout=25,
    )
    data = _safe_json(resp)
    if resp.status_code >= 400:
        raise RuntimeError(f"Khalti lookup failed. HTTP {resp.status_code}. {data}")
    return data


def esewa_verify(amount, pid, rid, scd):
    """
    eSewa UAT verification. Returns raw text; we treat 'Success' as ok.
    """
    payload = {
        "amt": str(amount),
        "rid": rid,
        "pid": pid,
        "scd": scd,
    }
    resp = requests.post(settings.ESEWA_VERIFY_URL, data=payload, timeout=25)
    return resp.text or ""