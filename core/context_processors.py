from django.conf import settings
from .models import SiteSetting

def site_settings(request):
    obj, _ = SiteSetting.objects.get_or_create(pk=1)

    default_bg = settings.STATIC_URL + "images/hospital-bg.jpg"
    hero_bg_url = obj.hero_background.url if obj.hero_background else default_bg

    return {
        "site_settings": obj,
        "hero_bg_url": hero_bg_url,
    }