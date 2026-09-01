"""Test settings — uses local PostgreSQL + locmem cache for test runs."""

from .settings import *  # noqa: F401,F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "ecobin_test_db",
        "USER": "postgres",
        "PASSWORD": "123",
        "HOST": "localhost",
        "PORT": "5432",
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
