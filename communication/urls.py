from django.urls import path
from . import views

urlpatterns = [
    path("inbox/", views.inbox, name="inbox"),
    path("read/<int:pk>/", views.mark_read, name="notification_read"),
]