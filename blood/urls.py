from django.urls import path
from . import views

urlpatterns = [
    path('emergency-request/', views.emergency_request_view, name='emergency_request'),
    path('feed/', views.public_dashboard_view, name='public_dashboard'),
    path('donate-now/<int:request_id>/', views.guest_donate_view, name='guest_donate'),
    path('request/<int:request_id>-<slug:slug>/', views.request_detail_view, name='blood_request_detail_slug'),
    path('request/<int:request_id>/', views.request_detail_view, name='blood_request_detail'),
    path('request/<int:request_id>/respond/', views.donor_respond_view, name='donor_respond'),
    path('request/<int:request_id>/donation/', views.donation_create_view, name='donation_create'),

    # donor history + reports
    path('donor/history/', views.donor_history_view, name='donor_history'),
    path('donation/<int:donation_id>/report/upload/', views.donation_report_upload_view, name='donation_report_upload'),
    path('report/<int:report_id>/download/', views.donation_report_download_view, name='donation_report_download'),
    path("donation/<int:donation_id>/verify/", views.verify_donation_view, name="org_verify_donation"),
    
    # donor verify request and manage
    path("request/new/", views.recipient_request_view, name="recipient_request"),
    path("my/requests/", views.my_blood_requests_view, name="my_blood_requests"),
    path("request/<int:request_id>/verify/", views.verify_request_view, name="verify_request"),
    path("request/<int:request_id>/proof/", views.request_proof_view, name="blood_request_proof"),
    path('report/<int:report_id>/view/', views.donation_report_view_inline, name='donation_report_view'),

    path("request/<int:request_id>/edit/", views.blood_request_edit_view, name="blood_request_edit"),
    path("request/<int:request_id>/cancel/", views.blood_request_cancel_view, name="blood_request_cancel"),
    path("campaigns/", views.blood_campaigns_view, name="blood_campaigns"),
    path("request/<int:request_id>/quick-respond/", views.quick_respond_view, name="quick_respond"),

    path("request/<int:request_id>/sos/", views.blood_sos_broadcast_view, name="blood_sos_broadcast"),
]