"""Django settings for quizbank-ai.

Every secret and environment-specific value is read from environment
variables. Nothing sensitive lives in this file, so it is safe to commit.
See .env.example for the full list.
"""

import os
import sys
import tempfile
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(int(default))).lower() in {"1", "true", "yes", "on"}


DEBUG = env_bool("DJANGO_DEBUG", default=False)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if DEBUG:
        # Local development only. A real deployment must set DJANGO_SECRET_KEY.
        SECRET_KEY = "dev-only-insecure-key-do-not-use-in-production"
    else:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY is not set. Set it, or set DJANGO_DEBUG=1 for local development."
        )

ALLOWED_HOSTS = [
    h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()
]

# Full origins (https://example.com) allowed to post forms. Needed when the app
# is served over HTTPS under a public domain.
CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()
]

# Behind a proxy that terminates HTTPS (like Hugging Face Spaces): trust its
# X-Forwarded-Proto header and send cookies over HTTPS only.
if env_bool("DJANGO_BEHIND_HTTPS_PROXY"):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "bank",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Serves static files when DEBUG is off (after `collectstatic`).
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Every page needs a signed-in user, except the login page.
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "quizbank.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "bank.context_processors.navigation",
            ],
        },
    },
]

WSGI_APPLICATION = "quizbank.wsgi.application"

# SQLite by default: zero setup, and plenty for a single-user question bank.
# Point DATABASE_PATH somewhere else to keep the database outside the repo.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("DATABASE_PATH", BASE_DIR / "db.sqlite3"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Machine learning: where downloaded datasets and trained models live, and which
# text embedder to use ("minilm" for the real model; "hashing" is a fast,
# offline stand-in the tests use).
QUIZBANK_DATA_DIR = Path(os.environ.get("QUIZBANK_DATA_DIR", BASE_DIR / "data"))
QUIZBANK_EMBEDDER = os.environ.get("QUIZBANK_EMBEDDER", "minilm")

# Tests never touch local datasets or trained models, and never download anything.
if len(sys.argv) > 1 and sys.argv[1] == "test":
    QUIZBANK_DATA_DIR = Path(tempfile.mkdtemp(prefix="quizbank-test-data-"))
    QUIZBANK_EMBEDDER = "hashing"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "bank:dashboard"
LOGOUT_REDIRECT_URL = "login"

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

# Images extracted from imported Canvas quizzes.
MEDIA_URL = "media/"
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", BASE_DIR / "media"))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Public demo: a shared account whose username and password are shown on the
# sign-in page. Leave unset for a real deployment.
QUIZBANK_DEMO_USERNAME = os.environ.get("QUIZBANK_DEMO_USERNAME", "")
QUIZBANK_DEMO_PASSWORD = os.environ.get("QUIZBANK_DEMO_PASSWORD", "")
