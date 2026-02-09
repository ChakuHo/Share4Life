from django.apps import AppConfig

class BloodConfig(AppConfig):
    name = "blood"

    def ready(self):
        import blood.signals  # noqa