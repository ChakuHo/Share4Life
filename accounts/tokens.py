from django.core import signing

EMAIL_VERIFY_SALT = "accounts.EmailVerify.v1"

def make_email_token(user) -> str:
    return signing.dumps({"uid": user.pk, "email": user.email}, salt=EMAIL_VERIFY_SALT)

def read_email_token(token: str, max_age_seconds: int = 60 * 60 * 24):
    # default: 24 hours
    return signing.loads(token, salt=EMAIL_VERIFY_SALT, max_age=max_age_seconds)