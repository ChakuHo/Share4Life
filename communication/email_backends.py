from email.utils import parseaddr

import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend


class BrevoAPIEmailBackend(BaseEmailBackend):
    """
    Django email backend using Brevo HTTP API.
    This lets built-in Django emails (password reset, send_mail, etc.) work
    without SMTP.
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

        session = requests.Session()
        headers = {
            "accept": "application/json",
            "api-key": api_key,
            "content-type": "application/json",
        }

        sent_count = 0

        for message in email_messages:
            try:
                sender_name, sender_email = parseaddr(message.from_email or settings.DEFAULT_FROM_EMAIL)
                if not sender_email:
                    sender_email = getattr(settings, "EMAIL_HOST_USER", "") or ""
                if not sender_name:
                    sender_name = "Share4Life"

                to_list = []
                for addr in (message.to or []):
                    name, email = parseaddr(addr)
                    if email:
                        item = {"email": email}
                        if name:
                            item["name"] = name
                        to_list.append(item)

                if not to_list:
                    continue

                cc_list = []
                for addr in (message.cc or []):
                    name, email = parseaddr(addr)
                    if email:
                        item = {"email": email}
                        if name:
                            item["name"] = name
                        cc_list.append(item)

                bcc_list = []
                for addr in (message.bcc or []):
                    name, email = parseaddr(addr)
                    if email:
                        item = {"email": email}
                        if name:
                            item["name"] = name
                        bcc_list.append(item)

                reply_to = None
                if getattr(message, "reply_to", None):
                    rt_name, rt_email = parseaddr(message.reply_to[0])
                    if rt_email:
                        reply_to = {"email": rt_email}
                        if rt_name:
                            reply_to["name"] = rt_name

                html_content = None
                for alt in getattr(message, "alternatives", []) or []:
                    if len(alt) >= 2 and alt[1] == "text/html":
                        html_content = alt[0]
                        break

                payload = {
                    "sender": {
                        "name": sender_name,
                        "email": sender_email,
                    },
                    "to": to_list,
                    "subject": message.subject or "",
                }

                if message.body:
                    payload["textContent"] = message.body

                if html_content:
                    payload["htmlContent"] = html_content

                if cc_list:
                    payload["cc"] = cc_list

                if bcc_list:
                    payload["bcc"] = bcc_list

                if reply_to:
                    payload["replyTo"] = reply_to

                response = session.post(
                    self.api_url,
                    json=payload,
                    headers=headers,
                    timeout=int(getattr(settings, "EMAIL_TIMEOUT", 10)),
                )

                if 200 <= response.status_code < 300:
                    sent_count += 1
                else:
                    if not self.fail_silently:
                        raise Exception(
                            f"Brevo send failed: {response.status_code} {response.text[:500]}"
                        )

            except Exception:
                if not self.fail_silently:
                    raise

        return sent_count