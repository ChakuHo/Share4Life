from django.urls import path
from . import views

urlpatterns = [
    path("inbox/", views.inbox, name="inbox"),
    path("read/<int:pk>/", views.mark_read, name="notification_read"),

    # open + mark read
    path("open/<int:pk>/", views.open_notification, name="notification_open"),

    # bulk actions
    path("read-all/", views.mark_all_read, name="notification_read_all"),
    path("clear-all/", views.clear_all, name="notification_clear_all"),
]