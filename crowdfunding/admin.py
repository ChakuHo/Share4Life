import json
from django.contrib import admin, messages
from django.urls import reverse
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

    raw_response_pretty.short_description = "Raw response"

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
    list_display = (
        "id",
        "campaign_link",
        "reporter_display",
        "reason_badge",
        "status_badge",
        "message_preview",
        "created_at",
    )
    list_filter = ("status", "reason", "created_at")
    search_fields = (
        "campaign__title",
        "campaign__patient_name",
        "guest_name",
        "guest_email",
        "message",
        "reason",
        "reporter_user__username",
        "reporter_user__email",
    )
    ordering = ("-created_at",)

    readonly_fields = ("created_at",)

    fieldsets = (
        ("Report", {"fields": ("campaign", "status", "reason", "message")}),
        ("Reporter", {"fields": ("reporter_user", "guest_name", "guest_email")}),
        ("Timestamp", {"fields": ("created_at",)}),
    )

    actions = ["mark_reviewed", "mark_dismissed", "reopen_reports"]

    @admin.display(description="Campaign")
    def campaign_link(self, obj: CampaignReport):
        if not obj.campaign_id:
            return "—"
        url = reverse("admin:crowdfunding_campaign_change", args=[obj.campaign_id])
        return format_html('<a href="{}">#{}</a> {}', url, obj.campaign_id, obj.campaign.title)

    @admin.display(description="Reporter")
    def reporter_display(self, obj: CampaignReport):
        if obj.reporter_user_id:
            u = obj.reporter_user
            return f"{u.username} ({u.email or 'no-email'})"
        return f"{obj.guest_name or 'Guest'} ({obj.guest_email or 'no-email'})"

    @admin.display(description="Reason")
    def reason_badge(self, obj: CampaignReport):
        reason = (obj.reason or "OTHER").upper()
        color = {
            "FAKE_DOCS": "#dc3545",
            "SCAM": "#b30000",
            "MISLEADING": "#fd7e14",
            "DUPLICATE": "#6f42c1",
            "ABUSE": "#343a40",
            "OTHER": "#6c757d",
        }.get(reason, "#6c757d")

        return format_html(
            '<span style="display:inline-block;padding:2px 8px;border-radius:999px;'
            'background:{};color:#fff;font-weight:700;font-size:12px;">{}</span>',
            color, reason
        )

    @admin.display(description="Status")
    def status_badge(self, obj: CampaignReport):
        s = (obj.status or "OPEN").upper()
        color = {
            "OPEN": "#ffc107",
            "REVIEWED": "#198754",
            "DISMISSED": "#6c757d",
        }.get(s, "#6c757d")
        text_color = "#000" if s == "OPEN" else "#fff"

        return format_html(
            '<span style="display:inline-block;padding:2px 8px;border-radius:999px;'
            'background:{};color:{};font-weight:700;font-size:12px;">{}</span>',
            color, text_color, s
        )

    @admin.display(description="Message")
    def message_preview(self, obj: CampaignReport):
        txt = (obj.message or "").strip()
        if not txt:
            return "—"
        return (txt[:80] + "…") if len(txt) > 80 else txt

    # -------- Admin Actions --------
    def mark_reviewed(self, request, queryset):
        updated = 0
        for rep in queryset.select_related("campaign"):
            if rep.status == "REVIEWED":
                continue
            rep.status = "REVIEWED"
            rep.save(update_fields=["status"])
            updated += 1

            CampaignAuditLog.objects.create(
                campaign=rep.campaign,
                actor=request.user,
                action="UPDATED",
                message=f"Report #{rep.id} marked REVIEWED ({rep.reason})",
            )

        self.message_user(request, f"{updated} report(s) marked REVIEWED.", level=messages.SUCCESS)

    mark_reviewed.short_description = "Mark selected reports as REVIEWED"

    def mark_dismissed(self, request, queryset):
        updated = 0
        for rep in queryset.select_related("campaign"):
            if rep.status == "DISMISSED":
                continue
            rep.status = "DISMISSED"
            rep.save(update_fields=["status"])
            updated += 1

            CampaignAuditLog.objects.create(
                campaign=rep.campaign,
                actor=request.user,
                action="UPDATED",
                message=f"Report #{rep.id} marked DISMISSED ({rep.reason})",
            )

        self.message_user(request, f"{updated} report(s) marked DISMISSED.", level=messages.WARNING)

    mark_dismissed.short_description = "Mark selected reports as DISMISSED"

    def reopen_reports(self, request, queryset):
        updated = 0
        for rep in queryset.select_related("campaign"):
            if rep.status == "OPEN":
                continue
            rep.status = "OPEN"
            rep.save(update_fields=["status"])
            updated += 1

            CampaignAuditLog.objects.create(
                campaign=rep.campaign,
                actor=request.user,
                action="UPDATED",
                message=f"Report #{rep.id} reopened ({rep.reason})",
            )

        self.message_user(request, f"{updated} report(s) reopened.", level=messages.INFO)

    reopen_reports.short_description = "Reopen selected reports (set to OPEN)"

admin.site.register(CampaignDocument)
admin.site.register(Disbursement)
admin.site.register(CampaignAuditLog)