from django.urls import path
from . import views

urlpatterns = [
    path("", views.campaign_list, name="campaign_list"),
    path("campaign/new/", views.campaign_create, name="campaign_create"),
    path("campaign/<int:pk>/", views.campaign_detail, name="campaign_detail"),

    path("campaign/<int:pk>/donate/", views.donate_start, name="donate_start"),

    path("khalti/return/<int:donation_id>/", views.khalti_return, name="khalti_return"),

    path("esewa/success/<int:donation_id>/", views.esewa_success, name="esewa_success"),
    path("esewa/failure/<int:donation_id>/", views.esewa_failure, name="esewa_failure"),

    path("campaign/<int:pk>/disburse/", views.disburse_create, name="disburse_create"),

    path("campaign/<int:pk>/report/", views.report_campaign, name="campaign_report"),

    path("my/", views.my_campaigns, name="my_campaigns"),

    path("esewa/return/<int:donation_id>/", views.esewa_return, name="esewa_return"),

    path("my/donations/", views.my_donations, name="my_donations"),
]