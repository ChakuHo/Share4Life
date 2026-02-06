from django.urls import path
from . import views

urlpatterns = [
    # Donor pledge
    path("pledge/new/", views.pledge_create, name="organ_pledge_create"),
    path("pledges/", views.pledge_list, name="organ_pledge_list"),
    path("pledge/<int:pledge_id>/", views.pledge_detail, name="organ_pledge_detail"),
    path("pledge/<int:pledge_id>/submit/", views.pledge_submit, name="organ_pledge_submit"),
    path("pledge/<int:pledge_id>/revoke/", views.pledge_revoke, name="organ_pledge_revoke"),
    path("pledge/<int:pledge_id>/document/upload/", views.pledge_doc_upload, name="organ_pledge_doc_upload"),

    # Recipient requests
    path("request/new/", views.organ_request_create, name="organ_request_create"),
    path("my/requests/", views.organ_request_list, name="organ_request_list"),
    path("request/<int:request_id>/", views.organ_request_detail, name="organ_request_detail"),
    path("request/<int:request_id>/document/upload/", views.organ_request_doc_upload, name="organ_request_doc_upload"),

    # Organization portal
    path("portal/", views.organ_portal, name="organ_portal"),

    # org-side pledge review page (fixes 404 "donor side" view)
    path("portal/pledges/<int:pledge_id>/", views.org_pledge_detail, name="org_pledge_detail"),

    path("portal/pledges/<int:pledge_id>/verify/", views.org_verify_pledge, name="org_verify_pledge"),
    path("portal/requests/<int:request_id>/verify/", views.org_verify_organ_request, name="org_verify_organ_request"),
    path("portal/requests/<int:request_id>/match/new/", views.org_match_create, name="organ_match_create"),
    path("portal/matches/<int:match_id>/update/", views.org_match_update, name="org_match_update"),
]