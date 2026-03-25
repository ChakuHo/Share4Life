from email.utils import parseaddr

import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend


class BrevoAPIEmailBackend(BaseEmailBackend):
    """
    Django email backend using Brevo HTTP API.
    Works for:
      - send_mail(...)
      - EmailMessage.send()
      - Django password reset emails
      - queued emails sent through send_mail(...)
    """

    api_url = "https://api.brevo.com/v3/smtp/email"

    def send_messages(self, email_messages):
        if not email_messages:
            return 0

        api_key = (getattr(settings, "BREVO_API_KEY", "") or "").strip()
        if not api_key:
            if self.fail_silently:
                return 0
            raise ValueError("BREVO_API_KEY is missing.")

        headers = {
            "accept": "application/json",
            "api-key": api_key,
            "content-type": "application/json",
        }

        timeout = int(getattr(settings, "EMAIL_TIMEOUT", 10))
        sent_count = 0

        for message in email_messages:
            try:
                from_name, from_email = parseaddr(message.from_email or settings.DEFAULT_FROM_EMAIL)
                if not from_email:
                    from_email = (getattr(settings, "EMAIL_HOST_USER", "") or "").strip()
                if not from_name:
                    from_name = "Share4Life"

                to_items = []
                for addr in (message.to or []):
                    nm, em = parseaddr(addr)
                    if em:
                        row = {"email": em}
                        if nm:
                            row["name"] = nm
                        to_items.append(row)

                if not to_items:
                    continue

                payload = {
                    "sender": {
                        "name": from_name,
                        "email": from_email,
                    },
                    "to": to_items,
                    "subject": message.subject or "",
                    "textContent": message.body or "",
                }

                # optional HTML alternative support
                for alt in getattr(message, "alternatives", []) or []:
                    if len(alt) >= 2 and alt[1] == "text/html":
                        payload["htmlContent"] = alt[0]
                        break

                # optional cc/bcc
                cc_items = []
                for addr in (message.cc or []):
                    nm, em = parseaddr(addr)
                    if em:
                        row = {"email": em}
                        if nm:
                            row["name"] = nm
                        cc_items.append(row)
                if cc_items:
                    payload["cc"] = cc_items

                bcc_items = []
                for addr in (message.bcc or []):
                    nm, em = parseaddr(addr)
                    if em:
                        row = {"email": em}
                        if nm:
                            row["name"] = nm
                        bcc_items.append(row)
                if bcc_items:
                    payload["bcc"] = bcc_items

                resp = requests.post(
                    self.api_url,
                    headers=headers,
                    json=payload,
                    timeout=timeout,
                )

                if 200 <= resp.status_code < 300:
                    sent_count += 1
                else:
                    if not self.fail_silently:
                        raise Exception(f"Brevo send failed: {resp.status_code} {resp.text[:500]}")

            except Exception:
                if not self.fail_silently:
                    raise

        return sent_count