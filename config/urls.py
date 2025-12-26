from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from accounts import views as account_views

# Import a simple view for the homepage temporarily
from django.shortcuts import render

# Simple temporary home view so login redirect doesn't crash
def home(request):
    return render(request, 'core/home.html') 

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', home, name='home'), # Root URL
    path('accounts/', include('accounts.urls')), # Connects your login/register
    path('', account_views.home, name='home'), # Home view
    path('blood/', include('blood.urls')), # Blood app URLs
]

# This allows images to load during development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)