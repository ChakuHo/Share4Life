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
]