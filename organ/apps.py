from django.apps import AppConfig

class OrganConfig(AppConfig):
    name = "organ"

    def ready(self):
        import organ.signals  # noqa