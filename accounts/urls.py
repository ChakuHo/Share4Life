# accounts/urls.py
from django.urls import path
from django.contrib.auth import views as auth_views
from django.urls import reverse_lazy

from . import views
from .forms import BootstrapPasswordResetForm, BootstrapSetPasswordForm

urlpatterns = [
    path("register/", views.register, name="register"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("dashboard/", views.dashboard, name="dashboard"),

    # Forgot password
    path(
        "password-reset/",
        auth_views.PasswordResetView.as_view(
            template_name="accounts/password_reset_form.html",
            email_template_name="accounts/emails/password_reset_email.txt",
            subject_template_name="accounts/emails/password_reset_subject.txt",
            success_url=reverse_lazy("password_reset_done"),
            form_class=BootstrapPasswordResetForm,
        ),
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="accounts/password_reset_done.html",
        ),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="accounts/password_reset_confirm.html",
            success_url=reverse_lazy("password_reset_complete"),
            form_class=BootstrapSetPasswordForm,
        ),
        name="password_reset_confirm",
    ),
    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="accounts/password_reset_complete.html",
        ),
        name="password_reset_complete",
    ),

    # Email verification
    path("verify-email/", views.verify_email_prompt, name="verify_email_prompt"),
    path("verify-email/send/", views.send_verification_email, name="send_verification_email"),
    path("verify-email/<str:token>/", views.verify_email, name="verify_email"),
    path("verify-email/resend/", views.resend_verification_email_public, name="resend_verification_email_public"),

    # URLs for profile, KYC, and family members
    path("profile/", views.profile_view, name="profile"),
    path("kyc/submit/", views.kyc_submit, name="kyc_submit"),
    path("profile/edit/", views.profile_edit, name="profile_edit"),
    path("family/add/", views.family_add, name="family_add"),
    path("family/<int:pk>/edit/", views.family_edit, name="family_edit"),
    path("family/<int:pk>/delete/", views.family_delete, name="family_delete"),
    path("family/emergency/", views.emergency_profiles_list, name="emergency_profiles_list"),
    

    path("profile/certificate/pdf/", views.download_certificate_pdf, name="download_certificate_pdf"),
    path("donors/", views.public_donor_directory, name="public_donor_directory"),
]


