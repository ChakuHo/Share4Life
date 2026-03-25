"""
Django settings for config project.
"""

from pathlib import Path
import os
import dj_database_url

# Build paths
BASE_DIR = Path(__file__).resolve().parent.parent

# Cloudinary config
CLOUDINARY_URL = os.environ.get("CLOUDINARY_URL", "")

# Security
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-secret-change-me")
DEBUG = os.environ.get("DEBUG", "1") == "1"

_default_hosts = ["127.0.0.1", "localhost", "bigyannemkul.com.np"]
render_host = (os.environ.get("RENDER_EXTERNAL_HOSTNAME", "") or "").strip()
if render_host:
    _default_hosts.append(render_host)

ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", ",".join(_default_hosts)).split(",")
ALLOWED_HOSTS = [h.strip() for h in ALLOWED_HOSTS if h.strip()]

# Static root for Render
STATIC_ROOT = BASE_DIR / "staticfiles"

# Application definition
INSTALLED_APPS = [
    "daphne",  # ASGI server
    "jazzmin",  # Admin UI

    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Third party
    "channels",
    "rest_framework",

    # Local apps
    "accounts.apps.AccountsConfig",
    "blood.apps.BloodConfig",
    "communication.apps.CommunicationConfig",
    "core.apps.CoreConfig",
    "crowdfunding.apps.CrowdfundingConfig",
    "hospitals.apps.HospitalsConfig",
    "organ.apps.OrganConfig",
]

JAZZMIN_SETTINGS = {
    "custom_js": "admin/js/admin_tabs_fix.js",
    "site_title": "Share4Life Admin",
    "site_header": "Share4Life",
    "welcome_sign": "Welcome to Share4Life Administration",
    "site_brand": "Share4Life",
}

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",

    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.site_settings",
                "hospitals.context_processors.org_context",
                "communication.context_processors.unread_notifications",
            ],
        },
    },
]

# Storage
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Database (Neon / Postgres in production, sqlite fallback only locally)
DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
        ssl_require=os.environ.get("DB_SSL_REQUIRE", "0") == "1",
    )
}
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True

# Site URL
SITE_BASE_URL = (
    os.environ.get("SITE_BASE_URL", "https://bigyannemkul.com.np") or ""
).strip().rstrip("/")

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kathmandu"
USE_I18N = True
USE_TZ = True

# Static files
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]

# Media
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

if CLOUDINARY_URL:
    INSTALLED_APPS += ["cloudinary", "cloudinary_storage"]

    STORAGES = {
        "default": {
            "BACKEND": "cloudinary_storage.storage.MediaCloudinaryStorage",
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
        },
    }

# Custom user model
AUTH_USER_MODEL = "accounts.CustomUser"

# Email
BREVO_API_KEY = (os.environ.get("BREVO_API_KEY", "") or "").strip()
EMAIL_TIMEOUT = int(os.environ.get("EMAIL_TIMEOUT", "10"))

EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")

DEFAULT_FROM_EMAIL = os.environ.get(
    "DEFAULT_FROM_EMAIL",
    f"Share4Life <{EMAIL_HOST_USER}>"
)
SERVER_EMAIL = DEFAULT_FROM_EMAIL
EMAIL_VERIFICATION_REQUIRED = True

if BREVO_API_KEY:
    EMAIL_BACKEND = "communication.email_backends.BrevoAPIEmailBackend"
else:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = "smtp.gmail.com"
    EMAIL_PORT = 587
    EMAIL_USE_TLS = True

# Notification / email queue settings
NOTIFICATION_RETENTION_DAYS = 7
EMAIL_QUEUE_BATCH_SIZE = 40
EMAIL_QUEUE_BATCH_DELAY = 10
EMAIL_QUEUE_MAX_ATTEMPTS = 3
EMAIL_DEDUPE_HOURS = 24

ENABLE_SCHEDULED_EMAILS = os.environ.get("ENABLE_SCHEDULED_EMAILS", "1") == "1"

# Channels / Redis
REDIS_URL = (os.environ.get("REDIS_URL", "") or "").strip().strip('"').strip("'")
USE_REDIS_CHANNEL_LAYER = os.environ.get("USE_REDIS_CHANNEL_LAYER", "0") == "1"

if USE_REDIS_CHANNEL_LAYER and REDIS_URL.startswith(("redis://", "rediss://", "unix://")):
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {
                "hosts": [REDIS_URL],
            },
        }
    }
else:
    # Stable for single Render instance / free tier
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer",
        }
    }

# Guest emergency anti-spam limits
S4L_GUEST_EMERGENCY_MIN_INTERVAL_SECONDS = 600
S4L_GUEST_EMERGENCY_MAX_PER_HOUR_IP = 5
S4L_GUEST_EMERGENCY_MAX_PER_HOUR_PHONE = 3

# reCAPTCHA
RECAPTCHA_SITE_KEY = os.environ.get("RECAPTCHA_SITE_KEY", "")
RECAPTCHA_SECRET_KEY = os.environ.get("RECAPTCHA_SECRET_KEY", "")

if DEBUG and (not RECAPTCHA_SITE_KEY or not RECAPTCHA_SECRET_KEY):
    RECAPTCHA_SITE_KEY = "6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI"
    RECAPTCHA_SECRET_KEY = "6LeIxAcTAAAAAGG-vFI1TnRWxMZNFuojJ4WifJWe"

RECAPTCHA_ENABLED = bool(RECAPTCHA_SITE_KEY and RECAPTCHA_SECRET_KEY)

# Khalti
KHALTI_PUBLIC_KEY = os.environ.get("KHALTI_PUBLIC_KEY", "")
KHALTI_SECRET_KEY = os.environ.get("KHALTI_SECRET_KEY", "")
KHALTI_BASE_URL = os.environ.get("KHALTI_BASE_URL", "https://a.khalti.com/api/v2")
KHALTI_WEBSITE_URL = os.environ.get("KHALTI_WEBSITE_URL", SITE_BASE_URL)

# eSewa
ESEWA_PRODUCT_CODE = os.environ.get("ESEWA_PRODUCT_CODE", "EPAYTEST")
ESEWA_SECRET_KEY = os.environ.get("ESEWA_SECRET_KEY", "8gBm/:&EnhH.1/q")
ESEWA_FORM_URL = os.environ.get(
    "ESEWA_FORM_URL",
    "https://rc-epay.esewa.com.np/api/epay/main/v2/form"
)

# Crowdfunding / campaign settings
CAMPAIGN_ARCHIVE_AFTER_DAYS = int(os.environ.get("CAMPAIGN_ARCHIVE_AFTER_DAYS", "1"))
DISBURSEMENT_PROOF_REMINDER_DAYS = 3
DISBURSEMENT_PROOF_REMINDER_COOLDOWN_HOURS = 24

# Blood / SOS / matching settings
S4L_PUBLIC_FEED_MAX_DAYS = 7
S4L_SOS_COOLDOWN_SECONDS = 600
S4L_DEFAULT_WHATSAPP_CC = "977"

S4L_EMERGENCY_ESCALATION_MAX_MINUTES = 60
S4L_EMERGENCY_REPING_INTERVAL_MINUTES = 1
S4L_DONOR_REPING_COOLDOWN_SECONDS = 10
S4L_DONOR_MAX_REPINGS_PER_REQUEST = 5

S4L_ELIGIBILITY_REMIND_DAYS_BEFORE = 0
S4L_ELIGIBILITY_REMIND_REPEAT_DAYS = 7

S4L_CAMPAIGN_REMIND_DAYS_BEFORE = 2
S4L_CAMPAIGN_REMIND_REPEAT_DAYS = 7

# Security / proxy
CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")
    if o.strip()
]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"