from django.contrib import admin

from .models import (
    PublicBloodRequest,
    GuestResponse,
    DonorResponse,
    BloodDonation,
    DonationMedicalReport,
    BloodEscalationState,
    BloodDonorPingLog,
)


@admin.register(PublicBloodRequest)
class PublicBloodRequestAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "patient_name",
        "blood_group",
        "location_city",
        "hospital_name",
        "is_emergency",
        "status",
        "verification_status",
        "is_active",
        "created_at",
        "created_by",
        "target_organization",
    )
    list_filter = (
        "is_emergency",
        "status",
        "verification_status",
        "is_active",
        "created_at",
        "location_city",
    )
    search_fields = (
        "patient_name",
        "contact_phone",
        "hospital_name",
        "location_city",
        "created_by__username",
        "created_by__email",
    )
    ordering = ("-created_at",)
    autocomplete_fields = ("created_by", "verified_by", "target_organization")
    readonly_fields = ("created_at", "slug", "verified_at", "fulfilled_at")

    fieldsets = (
        ("Patient / Need", {
            "fields": ("patient_name", "blood_group", "units_needed")
        }),
        ("Location / Hospital", {
            "fields": ("location_city", "latitude", "longitude", "hospital_name")
        }),
        ("Contact", {
            "fields": ("contact_phone",)
        }),
        ("Request State", {
            "fields": ("is_emergency", "status", "is_active", "created_at", "fulfilled_at")
        }),
        ("Verification", {
            "fields": (
                "verification_status",
                "proof_document",
                "verified_by",
                "verified_at",
                "rejection_reason",
                "target_organization",
            )
        }),
        ("Meta", {
            "fields": ("created_by", "slug")
        }),
    )


@admin.register(GuestResponse)
class GuestResponseAdmin(admin.ModelAdmin):
    list_display = ("id", "request", "donor_name", "donor_phone", "status", "responded_at")
    list_filter = ("status", "responded_at")
    search_fields = ("donor_name", "donor_phone", "request__patient_name", "request__contact_phone")
    ordering = ("-responded_at",)
    autocomplete_fields = ("request",)


@admin.register(DonorResponse)
class DonorResponseAdmin(admin.ModelAdmin):
    list_display = ("id", "request", "donor", "status", "responded_at", "created_at")
    list_filter = ("status", "created_at", "responded_at")
    search_fields = (
        "donor__username",
        "donor__email",
        "request__patient_name",
        "request__hospital_name",
        "request__location_city",
    )
    ordering = ("-created_at",)
    autocomplete_fields = ("request", "donor")


@admin.register(BloodDonation)
class BloodDonationAdmin(admin.ModelAdmin):
    list_display = ("id", "donor_user", "status", "donated_at", "units", "hospital_name")
    list_filter = ("status",)
    search_fields = ("donor_user__username", "hospital_name")
    ordering = ("-donated_at",)
    autocomplete_fields = ("request", "donor_user", "verified_by", "verified_by_org")

    actions = ["mark_verified"]

    def mark_verified(self, request, queryset):
        for d in queryset:
            d.mark_verified(request.user)

    mark_verified.short_description = "Mark selected donations as VERIFIED"


@admin.register(DonationMedicalReport)
class DonationMedicalReportAdmin(admin.ModelAdmin):
    list_display = ("id", "donation", "uploaded_by", "uploaded_at", "note")
    list_filter = ("uploaded_at",)
    search_fields = ("donation__id", "uploaded_by__username", "note")
    ordering = ("-uploaded_at",)
    autocomplete_fields = ("donation", "uploaded_by")


@admin.register(BloodEscalationState)
class BloodEscalationStateAdmin(admin.ModelAdmin):
    list_display = ("id", "request", "stage", "next_run_at", "last_run_at", "is_done", "updated_at")
    list_filter = ("stage", "is_done", "updated_at")
    search_fields = ("request__id", "request__patient_name", "request__location_city")
    ordering = ("-updated_at",)
    autocomplete_fields = ("request",)


@admin.register(BloodDonorPingLog)
class BloodDonorPingLogAdmin(admin.ModelAdmin):
    list_display = ("id", "request", "donor", "stage", "pinged_at", "last_ping_at", "ping_count")
    list_filter = ("stage", "pinged_at", "last_ping_at")
    search_fields = (
        "donor__username",
        "donor__email",
        "request__id",
        "request__patient_name",
        "request__location_city",
    )
    ordering = ("-last_ping_at",)
    autocomplete_fields = ("request", "donor")