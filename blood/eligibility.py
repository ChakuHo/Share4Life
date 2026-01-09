from datetime import timedelta
from django.utils import timezone
from .models import BloodDonation

ELIGIBILITY_DAYS = 90

def last_verified_donation(user):
    return (
        BloodDonation.objects
        .filter(donor_user=user, status="VERIFIED")
        .order_by("-donated_at")
        .first()
    )

def next_eligible_datetime(user):
    last = last_verified_donation(user)
    if not last:
        return None
    return last.donated_at + timedelta(days=ELIGIBILITY_DAYS)

def is_eligible(user):
    nxt = next_eligible_datetime(user)
    return nxt is None or timezone.now() >= nxt