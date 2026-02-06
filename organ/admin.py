import json
from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html

from .models import (
    OrganPledge, OrganPledgeDocument,
    OrganRequest, OrganRequestDocument,
    OrganMatch
)


# -------------------------
# Inlines (Documents)
# -------------------------
class OrganPledgeDocumentInline(admin.TabularInline):
    model = OrganPledgeDocument
    extra = 0
    fields = ("doc_type", "file_link", "note", "uploaded_at")
    readonly_fields = ("file_link", "uploaded_at")

    def file_link(self, obj):
        if not obj or not obj.file:
            return "—"
        return format_html('<a href="{}" target="_blank">View</a>', obj.file.url)

    file_link.short_description = "File"


class OrganRequestDocumentInline(admin.TabularInline):
    model = OrganRequestDocument
    extra = 0
    fields = ("doc_type", "file_link", "note", "uploaded_at")
    readonly_fields = ("file_link", "uploaded_at")

    def file_link(self, obj):
        if not obj or not obj.file:
            return "—"
        return format_html('<a href="{}" target="_blank">View</a>', obj.file.url)

    file_link.short_description = "File"


# -------------------------
# Organ Pledge Admin
# -------------------------
@admin.register(OrganPledge)
class OrganPledgeAdmin(admin.ModelAdmin):
    inlines = [OrganPledgeDocumentInline]

    list_display = (
        "id",
        "donor",
        "pledge_type",
        "status",
        "organs_pretty",
        "submitted_at",
        "verified_at",
        "verified_by",
        "verified_by_org",
        "created_at",
    )
    list_filter = ("status", "pledge_type", "verified_by_org", "created_at")
    search_fields = ("donor__username", "donor__email", "rejection_reason")
    ordering = ("-created_at",)

    readonly_fields = (
        "created_at",
        "submitted_at",
        "revoked_at",
        "verified_at",
        "consent_at",
        "organs_pretty_readonly",
        "organs_json_readonly",
    )

    fieldsets = (
        ("Core", {"fields": ("donor", "pledge_type", "status")}),
        ("Organs", {"fields": ("organs_pretty_readonly", "organs_json_readonly")}),
        ("Consent", {"fields": ("consent_confirmed", "consent_at", "note")}),
        ("Verification", {"fields": ("verified_by", "verified_by_org", "verified_at", "rejection_reason")}),
        ("Timestamps", {"fields": ("submitted_at", "revoked_at", "created_at")}),
    )

    actions = ["mark_verified", "mark_rejected", "mark_revoked"]

    def organs_pretty(self, obj: OrganPledge):
        try:
            return ", ".join(obj.organ_names) if obj.organ_names else "—"
        except Exception:
            return "—"
    organs_pretty.short_description = "Organs"

    def organs_pretty_readonly(self, obj: OrganPledge):
        return self.organs_pretty(obj)
    organs_pretty_readonly.short_description = "Organs (names)"

    def organs_json_readonly(self, obj: OrganPledge):
        try:
            return json.dumps(obj.organs or [], ensure_ascii=False)
        except Exception:
            return str(obj.organs)
    organs_json_readonly.short_description = "Organs (raw JSON)"

    def mark_verified(self, request, queryset):
        updated = 0
        for p in queryset:
            if p.status == "VERIFIED":
                continue
            if p.status in ("REVOKED",):
                continue
            p.status = "VERIFIED"
            p.verified_by = request.user
            # verified_by_org stays as-is (portal sets it); admin can set manually if needed
            p.verified_at = timezone.now()
            p.rejection_reason = ""
            p.save(update_fields=["status", "verified_by", "verified_at", "rejection_reason"])
            updated += 1

        self.message_user(request, f"{updated} pledge(s) marked VERIFIED.", level=messages.SUCCESS)
    mark_verified.short_description = "Mark selected pledges as VERIFIED"

    def mark_rejected(self, request, queryset):
        updated = 0
        for p in queryset:
            if p.status == "REJECTED":
                continue
            p.status = "REJECTED"
            p.verified_by = request.user
            p.verified_at = timezone.now()
            if not p.rejection_reason:
                p.rejection_reason = "Rejected by admin."
            p.save(update_fields=["status", "verified_by", "verified_at", "rejection_reason"])
            updated += 1

        self.message_user(request, f"{updated} pledge(s) marked REJECTED.", level=messages.WARNING)
    mark_rejected.short_description = "Reject selected pledges"

    def mark_revoked(self, request, queryset):
        updated = 0
        for p in queryset:
            if p.status == "REVOKED":
                continue
            p.status = "REVOKED"
            p.revoked_at = timezone.now()
            p.save(update_fields=["status", "revoked_at"])
            updated += 1

        self.message_user(request, f"{updated} pledge(s) marked REVOKED.", level=messages.INFO)
    mark_revoked.short_description = "Mark selected pledges as REVOKED"


# -------------------------
# Organ Request Admin
# -------------------------
@admin.register(OrganRequest)
class OrganRequestAdmin(admin.ModelAdmin):
    inlines = [OrganRequestDocumentInline]

    list_display = (
        "id",
        "patient_name",
        "organ_needed",
        "urgency",
        "status",
        "hospital_name",
        "city",
        "target_organization",
        "created_by",
        "created_at",
        "verified_at",
    )
    list_filter = ("status", "urgency", "organ_needed", "city", "created_at", "target_organization")
    search_fields = ("patient_name", "hospital_name", "city", "contact_phone", "created_by__username", "created_by__email")
    ordering = ("-created_at",)

    readonly_fields = ("created_at", "verified_at")

    fieldsets = (
        ("Request", {"fields": ("patient_name", "organ_needed", "urgency", "status")}),
        ("Hospital & Contact", {"fields": ("hospital_name", "city", "contact_phone", "note")}),
        ("Ownership", {"fields": ("created_by", "target_organization")}),
        ("Verification", {"fields": ("verified_by", "verified_by_org", "verified_at", "rejection_reason")}),
        ("Timestamps", {"fields": ("created_at",)}),
    )

    actions = ["mark_active", "mark_rejected", "mark_closed", "mark_match_in_progress"]

    def mark_active(self, request, queryset):
        updated = 0
        for r in queryset:
            if r.status == "ACTIVE":
                continue
            r.status = "ACTIVE"
            r.verified_by = request.user
            r.verified_at = timezone.now()
            r.rejection_reason = ""
            r.save(update_fields=["status", "verified_by", "verified_at", "rejection_reason"])
            updated += 1
        self.message_user(request, f"{updated} request(s) marked ACTIVE.", level=messages.SUCCESS)
    mark_active.short_description = "Mark selected requests as ACTIVE"

    def mark_match_in_progress(self, request, queryset):
        updated = 0
        for r in queryset:
            if r.status == "MATCH_IN_PROGRESS":
                continue
            r.status = "MATCH_IN_PROGRESS"
            r.save(update_fields=["status"])
            updated += 1
        self.message_user(request, f"{updated} request(s) marked MATCH_IN_PROGRESS.", level=messages.INFO)
    mark_match_in_progress.short_description = "Mark selected requests as MATCH_IN_PROGRESS"

    def mark_closed(self, request, queryset):
        updated = 0
        for r in queryset:
            if r.status == "CLOSED":
                continue
            r.status = "CLOSED"
            r.save(update_fields=["status"])
            updated += 1
        self.message_user(request, f"{updated} request(s) marked CLOSED.", level=messages.INFO)
    mark_closed.short_description = "Mark selected requests as CLOSED"

    def mark_rejected(self, request, queryset):
        updated = 0
        for r in queryset:
            if r.status == "REJECTED":
                continue
            r.status = "REJECTED"
            r.verified_by = request.user
            r.verified_at = timezone.now()
            if not r.rejection_reason:
                r.rejection_reason = "Rejected by admin."
            r.save(update_fields=["status", "verified_by", "verified_at", "rejection_reason"])
            updated += 1
        self.message_user(request, f"{updated} request(s) marked REJECTED.", level=messages.WARNING)
    mark_rejected.short_description = "Reject selected requests"


# -------------------------
# Organ Match Admin
# -------------------------
@admin.register(OrganMatch)
class OrganMatchAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "organization",
        "request",
        "pledge",
        "status",
        "updated_by",
        "updated_at",
        "created_at",
    )
    list_filter = ("status", "organization", "updated_at")
    search_fields = (
        "request__patient_name",
        "pledge__donor__username",
        "organization__name",
        "notes",
    )
    ordering = ("-updated_at",)

    readonly_fields = ("created_at", "updated_at")

    fieldsets = (
        ("Match", {"fields": ("organization", "request", "pledge", "status")}),
        ("Notes", {"fields": ("notes",)}),
        ("Audit", {"fields": ("updated_by", "created_at", "updated_at")}),
    )

    actions = ["set_status_contacted", "set_status_screening", "set_status_completed", "set_status_failed"]

    def _set_status(self, request, queryset, status):
        updated = 0
        for m in queryset:
            if m.status == status:
                continue
            m.status = status
            m.updated_by = request.user
            m.save(update_fields=["status", "updated_by", "updated_at"])
            updated += 1
        self.message_user(request, f"{updated} match(es) updated to {status}.", level=messages.SUCCESS)

    def set_status_contacted(self, request, queryset):
        self._set_status(request, queryset, "CONTACTED")
    set_status_contacted.short_description = "Set selected matches to CONTACTED"

    def set_status_screening(self, request, queryset):
        self._set_status(request, queryset, "SCREENING")
    set_status_screening.short_description = "Set selected matches to SCREENING"

    def set_status_completed(self, request, queryset):
        self._set_status(request, queryset, "COMPLETED")
    set_status_completed.short_description = "Set selected matches to COMPLETED"

    def set_status_failed(self, request, queryset):
        self._set_status(request, queryset, "FAILED")
    set_status_failed.short_description = "Set selected matches to FAILED"


# documents as standalone models in admin too
@admin.register(OrganPledgeDocument)
class OrganPledgeDocumentAdmin(admin.ModelAdmin):
    list_display = ("id", "pledge", "doc_type", "uploaded_at")
    list_filter = ("doc_type", "uploaded_at")
    search_fields = ("pledge__donor__username", "note")


@admin.register(OrganRequestDocument)
class OrganRequestDocumentAdmin(admin.ModelAdmin):
    list_display = ("id", "request", "doc_type", "uploaded_at")
    list_filter = ("doc_type", "uploaded_at")
    search_fields = ("request__patient_name", "note")