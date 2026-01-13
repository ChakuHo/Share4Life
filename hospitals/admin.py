from django.contrib import admin, messages
from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from .models import Organization, OrganizationMembership


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "org_type", "status", "city", "created_at")
    list_filter = ("status", "org_type", "city")
    search_fields = ("name", "email", "phone")
    actions = ["approve_org", "reject_org"]

    def _notify_inapp(self, user, title, body="", url="", level="INFO"):
        try:
            from communication.models import Notification
            if user:
                Notification.objects.create(user=user, title=title, body=body, url=url, level=level)
        except Exception:
            pass

    def _send_email_safe(self, request, subject, body, to_email):
        if not to_email:
            return
        try:
            send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [to_email], fail_silently=False)
        except Exception as e:
            self.message_user(request, f"Email failed to {to_email}: {e}", level=messages.WARNING)

    def _activate_memberships(self, org):
        # activate members when org is approved
        for m in org.memberships.select_related("user").all():
            if not m.is_active:
                m.is_active = True
                m.save(update_fields=["is_active"])
            if m.role == "ADMIN" and not m.user.is_hospital_admin:
                m.user.is_hospital_admin = True
                m.user.save(update_fields=["is_hospital_admin"])

    def _deactivate_memberships(self, org):
        for m in org.memberships.all():
            if m.is_active:
                m.is_active = False
                m.save(update_fields=["is_active"])

    def _after_commit_approved(self, request, org_id):
        org = Organization.objects.get(pk=org_id)
        for m in org.memberships.select_related("user").filter(role="ADMIN"):
            u = m.user
            subject = "Share4Life - Organization Approved"
            body = (
                f"Dear {u.first_name or u.username},\n\n"
                f"Your organization '{org.name}' has been approved.\n"
                f"You can now access the Institution Portal.\n\n"
                f"Thank you,\nShare4Life Team"
            )
            self._send_email_safe(request, subject, body, u.email)
            self._notify_inapp(u, "Organization Approved",
                               f"Your organization '{org.name}' has been approved.",
                               url="/institutions/portal/", level="SUCCESS")

        if org.email:
            self._send_email_safe(
                request,
                "Share4Life - Organization Approved",
                f"Your organization '{org.name}' has been approved.\n\nShare4Life Team",
                org.email,
            )

    def _after_commit_rejected(self, request, org_id):
        org = Organization.objects.get(pk=org_id)
        for m in org.memberships.select_related("user").filter(role="ADMIN"):
            u = m.user
            subject = "Share4Life - Organization Rejected"
            body = (
                f"Dear {u.first_name or u.username},\n\n"
                f"Your organization '{org.name}' was rejected.\n"
                f"Reason: {org.rejection_reason}\n\n"
                f"Thank you,\nShare4Life Team"
            )
            self._send_email_safe(request, subject, body, u.email)
            self._notify_inapp(u, "Organization Rejected",
                               f"{org.name} rejected: {org.rejection_reason}",
                               url="/institutions/pending/", level="DANGER")

        if org.email:
            self._send_email_safe(
                request,
                "Share4Life - Organization Rejected",
                f"Your organization '{org.name}' was rejected.\nReason: {org.rejection_reason}\n\nShare4Life Team",
                org.email,
            )

    @transaction.atomic
    def _apply_approved(self, request, org: Organization):
        org.status = "APPROVED"
        org.approved_at = timezone.now()
        org.approved_by = request.user
        org.rejection_reason = ""
        org.save(update_fields=["status", "approved_at", "approved_by", "rejection_reason"])

        self._activate_memberships(org)

        transaction.on_commit(lambda: self._after_commit_approved(request, org.id))

    @transaction.atomic
    def _apply_rejected(self, request, org: Organization):
        org.status = "REJECTED"
        org.approved_at = timezone.now()
        org.approved_by = request.user
        if not org.rejection_reason:
            org.rejection_reason = "Rejected by admin."
        org.save(update_fields=["status", "approved_at", "approved_by", "rejection_reason"])

        self._deactivate_memberships(org)

        transaction.on_commit(lambda: self._after_commit_rejected(request, org.id))

    # --- Actions (still work) ---
    def approve_org(self, request, queryset):
        for org in queryset:
            self._apply_approved(request, org)
    approve_org.short_description = "Approve selected organizations"

    def reject_org(self, request, queryset):
        for org in queryset:
            self._apply_rejected(request, org)
    reject_org.short_description = "Reject selected organizations"

    # --- Manual change page (new behavior) ---
    def save_model(self, request, obj, form, change):
        old_status = None
        if change and obj.pk:
            old_status = Organization.objects.filter(pk=obj.pk).values_list("status", flat=True).first()

        super().save_model(request, obj, form, change)

        # If status changed in the form page, run workflow
        if old_status != obj.status:
            if obj.status == "APPROVED":
                self._apply_approved(request, obj)
                self.message_user(request, "Approved workflow executed (email + portal unlock).", level=messages.SUCCESS)
            elif obj.status == "REJECTED":
                self._apply_rejected(request, obj)
                self.message_user(request, "Rejected workflow executed (email sent).", level=messages.WARNING)


@admin.register(OrganizationMembership)
class OrganizationMembershipAdmin(admin.ModelAdmin):
    list_display = ("organization", "user", "role", "is_active", "added_at")
    list_filter = ("role", "is_active")
    search_fields = ("organization__name", "user__username", "user__email")