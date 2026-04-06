from django.urls import path
from . import views

urlpatterns = [
    # notifications
    path("inbox/", views.inbox, name="inbox"),
    path("read/<int:pk>/", views.mark_read, name="notification_read"),
    path("open/<int:pk>/", views.open_notification, name="notification_open"),
    path("read-all/", views.mark_all_read, name="notification_read_all"),
    path("clear-all/", views.clear_all, name="notification_clear_all"),
    path("settings/", views.notification_settings_view, name="notification_settings"),

    # chat
    path("chat/", views.chat_threads, name="chat_threads"),
    path("chat/thread/<int:thread_id>/", views.chat_thread_detail, name="chat_thread_detail"),
    path("chat/blood/<int:request_id>/with/<int:donor_id>/", views.start_blood_chat, name="chat_start_blood"),

    # NEW: directory donor ping
    path("pings/", views.donor_ping_inbox, name="donor_ping_inbox"),
    path("pings/to/<int:donor_id>/", views.donor_ping_create, name="donor_ping_create"),
    path("pings/<int:ping_id>/", views.donor_ping_detail, name="donor_ping_detail"),
    path("pings/<int:ping_id>/respond/", views.donor_ping_respond, name="donor_ping_respond"),
]