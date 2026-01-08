from .models import SiteSetting

def site_settings(request):
    
    obj, _ = SiteSetting.objects.get_or_create(pk=1)
    return {"site_settings": obj}