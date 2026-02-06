import json
from django.contrib import admin
from django.contrib import messages
from django.utils import timezone
from django.utils.html import format_html
from accounts.models import CustomUser

from .models import (
    Campaign,
    CampaignDocument,
    Donation,
    Disbursement,
    CampaignAuditLog,
    CampaignReport,
)
from .services import notify_user


@admin.register(Donation)
class DonationAdmin(admin.ModelAdmin):
    list_display = (
        "id", "campaign", "donor_user", "guest_name",
        "gateway", "status", "amount",
        "gateway_ref",
        "created_at", "verified_at",
    )
    list_filter = ("gateway", "status", "created_at")
    search_fields = (
        "campaign__title",
        "donor_user__username",
        "guest_name",
        "guest_phone",
        "gateway_ref",
        "pidx",
        "esewa_transaction_uuid",
        "esewa_transaction_code",
    )

    fieldsets = (
        ("Donation", {"fields": ("campaign", "amount", "gateway", "status")}),
        ("Donor", {"fields": ("donor_user", "guest_name", "guest_email", "guest_phone")}),
        ("Gateway refs", {"fields": ("gateway_ref", "pidx", "payment_url", "esewa_transaction_uuid", "esewa_transaction_code")}),
        ("Timestamps", {"fields": ("created_at", "verified_at")}),
        ("Raw response", {"fields": ("raw_response_pretty",)}),
    )

    def raw_response_pretty(self, obj: Donation):
        try:
            pretty = json.dumps(obj.raw_response or {}, indent=2, ensure_ascii=False)
        except Exception:
            pretty = str(obj.raw_response)
        return format_html("<pre style='white-space:pre-wrap'>{}</pre>", pretty)

    raw_response_pretty.short_description = "Raw response (pretty)"

    def get_readonly_fields(self, request, obj=None):
        """
        Always read-only:
          - created_at (auto_now_add, non-editable)
          - verified_at (timestamp)
          - raw_response_pretty (computed)

        After SUCCESS, lock gateway reference fields so they can't be altered.
        """
        base = ["raw_response_pretty", "created_at", "verified_at"]

        lock_after_success = [
            "gateway_ref",
            "pidx",
            "payment_url",
            "esewa_transaction_uuid",
            "esewa_transaction_code",
        ]

        if obj and obj.status == "SUCCESS":
            return tuple(base + lock_after_success)

        return tuple(base)


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "owner",
        "status",
        "is_featured",
        "target_amount",
        "raised_amount",
        "created_at",
    )
    list_filter = ("status", "is_featured")
    search_fields = (
        "title",
        "patient_name",
        "hospital_name",
        "hospital_city",
        "owner__username",
        "owner__email",
    )
    actions = ["approve_campaigns", "reject_campaigns"]

    readonly_fields = ("approved_by", "approved_at", "created_at", "raised_amount", "completed_at", "archived_at")

    fieldsets = (
        ("Campaign", {"fields": ("title", "patient_name", "description", "image")}),
        ("Hospital Details", {"fields": ("hospital_name", "hospital_city", "hospital_contact_phone")}),
        ("Funding", {"fields": ("target_amount", "raised_amount", "deadline")}),
        ("Workflow", {"fields": ("status", "owner", "rejection_reason", "approved_by", "approved_at", "completed_at", "archived_at")}),
        ("Meta", {"fields": ("is_featured", "created_at")}),
    )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        # show only staff users in approved_by selector
        if db_field.name == "approved_by":
            kwargs["queryset"] = CustomUser.objects.filter(is_staff=True)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def _notify_owner_missing(self, request, camp: Campaign):
        self.message_user(
            request,
            "Owner is empty, so no user can be notified. "
            "Set Owner on the campaign if it belongs to a user.",
            level=messages.WARNING,
        )

    def _after_status_change(self, request, camp: Campaign, old_status: str, new_status: str):
        if old_status == new_status:
            return

        # APPROVED workflow
        if new_status == "APPROVED":
            camp.approved_by = request.user
            camp.approved_at = timezone.now()
            camp.rejection_reason = ""
            camp.save(update_fields=["approved_by", "approved_at", "rejection_reason"])

            CampaignAuditLog.objects.create(
                campaign=camp, actor=request.user, action="APPROVED", message="Approved by admin"
            )

            if camp.owner_id:
                notify_user(
                    camp.owner,
                    "Campaign approved",
                    f"Your campaign '{camp.title}' is now public.",
                    url=camp.get_absolute_url(),
                    level="SUCCESS",
                    email_subject="Share4Life - Campaign Approved",
                    email_body=f"Your campaign '{camp.title}' has been approved and is now live.",
                )
            else:
                self._notify_owner_missing(request, camp)

        # REJECTED workflow (clear approved_by/approved_at)
        elif new_status == "REJECTED":
            if not camp.rejection_reason:
                camp.rejection_reason = "Rejected by admin."

            camp.approved_by = None
            camp.approved_at = None
            camp.save(update_fields=["rejection_reason", "approved_by", "approved_at"])

            CampaignAuditLog.objects.create(
                campaign=camp, actor=request.user, action="REJECTED", message=camp.rejection_reason
            )

            if camp.owner_id:
                notify_user(
                    camp.owner,
                    "Campaign rejected",
                    camp.rejection_reason,
                    url=camp.get_absolute_url(),
                    level="DANGER",
                    email_subject="Share4Life - Campaign Rejected",
                    email_body=f"Your campaign '{camp.title}' was rejected.\nReason: {camp.rejection_reason}",
                )
            else:
                self._notify_owner_missing(request, camp)

    def save_model(self, request, obj, form, change):
        old_status = None
        if change and obj.pk:
            old_status = Campaign.objects.filter(pk=obj.pk).values_list("status", flat=True).first()

        # If created via admin and owner is empty, set owner = admin (helps with notifications)
        if not change and not obj.owner_id:
            obj.owner = request.user

        super().save_model(request, obj, form, change)

        camp_db = Campaign.objects.select_related("owner").get(pk=obj.pk)
        if old_status is not None:
            self._after_status_change(request, camp_db, old_status, camp_db.status)

    # Bulk actions
    def approve_campaigns(self, request, queryset):
        for camp in queryset.select_related("owner"):
            old = camp.status
            camp.status = "APPROVED"
            camp.save(update_fields=["status"])
            self._after_status_change(request, camp, old, "APPROVED")
    approve_campaigns.short_description = "Approve selected campaigns"

    def reject_campaigns(self, request, queryset):
        for camp in queryset.select_related("owner"):
            old = camp.status
            camp.status = "REJECTED"
            if not camp.rejection_reason:
                camp.rejection_reason = "Rejected by admin."
            # clear approved fields on reject
            camp.approved_by = None
            camp.approved_at = None
            camp.save(update_fields=["status", "rejection_reason", "approved_by", "approved_at"])
            self._after_status_change(request, camp, old, "REJECTED")
    reject_campaigns.short_description = "Reject selected campaigns"


@admin.register(CampaignReport)
class CampaignReportAdmin(admin.ModelAdmin):
    list_display = ("id", "campaign", "reason", "status", "created_at")
    list_filter = ("status", "reason")
    search_fields = ("campaign__title", "guest_name", "guest_email", "message")


admin.site.register(CampaignDocument)
admin.site.register(Disbursement)
admin.site.register(CampaignAuditLog)