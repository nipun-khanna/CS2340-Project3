import os
import secrets
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", override=False)
ON_VERCEL = bool(os.environ.get("VERCEL"))
DEBUG = os.environ.get("DJANGO_DEBUG", "False").lower() == "true"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or ""
if not SECRET_KEY:
    if ON_VERCEL:
        # Each serverless instance would otherwise get its own key, breaking logins and CSRF across requests.
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set in the Vercel project environment")
    SECRET_KEY = secrets.token_urlsafe(50)
ALLOWED_HOSTS = [host.strip() for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if host.strip()]
CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if origin.strip()]
if ON_VERCEL:
    ALLOWED_HOSTS.append(".vercel.app")
    CSRF_TRUSTED_ORIGINS.append("https://*.vercel.app")
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

INSTALLED_APPS = [
    "django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
    "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles",
    "knowledge_base",
]
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
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [], "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.debug",
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
WSGI_APPLICATION = "config.wsgi.application"
DATABASES = {"default": dj_database_url.parse(os.environ.get("DATABASE_URL", "postgresql://localhost:5432/rag"))}
# Supabase's transaction pooler (port 6543), recommended for serverless hosting, does not support server-side cursors.
DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True
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
STATIC_URL = "static/"
# Serve admin and app static files straight from their packages, so no collectstatic build step is needed.
WHITENOISE_USE_FINDERS = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
DATA_DIR = BASE_DIR / "data"
RAG_CHUNK_TOKENS = 400
RAG_CHUNK_OVERLAP = 50
RAG_MIN_SIMILARITY = float(os.environ.get("RAG_MIN_SIMILARITY", "0.70"))
GEMINI_CHAT_MODEL = os.environ.get("GEMINI_CHAT_MODEL", "gemini-3.5-flash-lite")
RESPONSE_TIME_TARGET_SECONDS = float(os.environ.get("RESPONSE_TIME_TARGET_SECONDS", "10"))
MAX_FAILURE_RATE = float(os.environ.get("MAX_FAILURE_RATE", "0.05"))
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "ask"
LOGOUT_REDIRECT_URL = "login"

# Exact hosts only. Extend after reviewing a source; redirects must also stay on this list.
INGEST_ALLOWED_HOSTS = (
    "medlineplus.gov", "www.nia.nih.gov", "www.cdc.gov", "www.fda.gov",
    "www.niddk.nih.gov", "www.who.int",
)
