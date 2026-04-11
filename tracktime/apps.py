from django.apps import AppConfig

class TracktimeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "tracktime"
    verbose_name = "Track Time"

    def ready(self):
        # registra signals de pub/sub (Phase 3)
        from . import signals  # noqa: F401
