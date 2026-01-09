# config/urls.py
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from accounts import views as account_views
from django.shortcuts import render

def core_home(request):
    return render(request, "core/home.html")

urlpatterns = [
    path("admin/", admin.site.urls),

    # Dynamic landing page (accounts.views.home)
    path("", account_views.home, name="home"),

    path("core-home/", core_home, name="core_home"),

    path("accounts/", include("accounts.urls")),
    
    path("blood/", include("blood.urls")),

    path("communication/", include("communication.urls")),

]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)