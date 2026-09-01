"""Test settings — uses SQLite + locmem cache for local test runs."""

from .settings import *  # noqa: F401,F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

CELERY_TASK_ALWAYS_EAGER = True

DEFAULT_FILE_STORAGE = "django.core.files.storage.InMemoryStorage"

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
