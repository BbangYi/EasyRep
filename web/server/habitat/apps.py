from django.apps import AppConfig


class HabitatConfig(AppConfig):
    name = "habitat"

    def ready(self):
        from . import signals  # noqa: F401
