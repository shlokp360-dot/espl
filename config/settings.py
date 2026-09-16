"""
Django settings. Real values live in the .env file, which is never committed.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-change-me")
DEBUG = os.getenv("DJANGO_DEBUG", "True") == "True"
ALLOWED_HOSTS = [h.strip() for h in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "masters",
    "projects",
    "tasks",
    "analytics",
    "compliance",
    "sales",
    "finance",
    "drawings",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # ⚠ DEFAULT DENY. Every view needs a signed-in user unless it is explicitly
    #   marked `@login_not_required` — which, today, only the login page is.
    #   The opposite arrangement (decorate the screens that need protecting)
    #   fails silently the first time somebody adds a screen and forgets, and
    #   the failure is an open door rather than a broken page.
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    # ⚠ AFTER MessageMiddleware, NOT BEFORE IT. This one explains itself with
    #   messages.info(), and the message store does not exist until the
    #   middleware above has run — putting it earlier raises MessageFailure on
    #   the first forced password change, which is exactly when a new user is
    #   least able to work out what went wrong.
    "accounts.middleware.ForcePasswordChangeMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# ⚠ OURS COMES FIRST AND DJANGO'S STAYS BEHIND IT. Ours handles the capital
#   letters — and, as a courtesy, an email address for accounts that predate the
#   username rule. The standard one still authenticates management commands.
AUTHENTICATION_BACKENDS = [
    "accounts.backends.LoginBackend",
    "django.contrib.auth.backends.ModelBackend",
]

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"          # the launchpad
LOGOUT_REDIRECT_URL = "/login/"

# 12 hours: a working day, so nobody re-types at lunch, but a laptop left at the
# site office does not stay signed in all week.
SESSION_COOKIE_AGE = 12 * 60 * 60
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "projects.context_processors.modules",
    ]},
}]

# SQLite while developing; PostgreSQL once DB_NAME is filled in .env
if os.getenv("DB_NAME"):
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME"),
        "USER": os.getenv("DB_USER"),
        "PASSWORD": os.getenv("DB_PASSWORD"),
        "HOST": os.getenv("DB_HOST", "localhost"),
        "PORT": os.getenv("DB_PORT", "5432"),
    }}
else:
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-in"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# ⚠⚠ MEDIA_ROOT WITHOUT A MEDIA_URL, AND THAT IS DELIBERATE.
#   Compliance documents are the only thing in this system that does not live in
#   the database. They are read back through a permission-checked view
#   (compliance.views.download) and there is NO address that reaches this folder
#   directly — a signed municipal approval must not be readable by anybody
#   holding a link.
#
# ⚠ AND THE BACKUP MUST COVER IT. `pg_dump` alone would silently miss every
#   document in here. See OPEN-BEFORE-GO-LIVE.md.
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Admin branding
ADMIN_SITE_HEADER = "Elegance Skyz — Construction Automation"

# ⚠ ON IN DEV TOO, not just production. These two have no downside on http and
#   they are what protect the ONE place the app renders an uploaded file in the
#   browser (compliance.views.view_inline): nosniff stops a browser MIME-sniffing
#   a whitelisted .pdf/.png that isn't really one, and DENY stops the app being
#   framed. SecurityMiddleware and XFrameOptionsMiddleware apply them to every
#   response, the file downloads included.
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# ⚠ PRODUCTION HARDENING, ON ONLY WHEN DEBUG IS OFF. In dev these would break
#   http://127.0.0.1 (endless HTTPS redirects, cookies the browser drops). In
#   production DJANGO_DEBUG is unset, so every one of these turns on. Behind a
#   TLS-terminating proxy, so trust its X-Forwarded-Proto for the redirect.
#   ⚠ GATED ON THE ENV VAR, NOT `DEBUG`: the test runner forces DEBUG=False in
#     process, which would 301 every test request to https. The env var it does
#     not touch, so this stays off in dev and under test, on only in production.
if os.getenv("DJANGO_DEBUG", "True") != "True":
    SECURE_SSL_REDIRECT = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000  # one year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    # nosniff and X_FRAME_OPTIONS are set unconditionally above.
