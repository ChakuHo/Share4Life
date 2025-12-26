from django.urls import path
from . import views

urlpatterns = [
    path('emergency-request/', views.emergency_request_view, name='emergency_request'),
    path('feed/', views.public_dashboard_view, name='public_dashboard'),
    path('donate-now/<int:request_id>/', views.guest_donate_view, name='guest_donate'),
]