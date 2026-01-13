from django.urls import path
from . import views

urlpatterns = [
    path("", views.institutions_home, name="institutions_home"),
    path("register/", views.organization_register, name="org_register"),
    path("pending/", views.org_pending, name="org_pending"),
    path("portal/", views.org_portal, name="org_portal"),
    path("portal/members/", views.org_members, name="org_members"),
    path("portal/campaigns/", views.org_campaign_list, name="org_campaign_list"),
    path("portal/campaigns/new/", views.org_campaign_create, name="org_campaign_create"),
    path("portal/requests/<int:request_id>/verify/", views.org_verify_request, name="org_verify_request"),
    path("portal/donations/<int:donation_id>/verify/", views.org_verify_donation, name="org_verify_donation"),
]