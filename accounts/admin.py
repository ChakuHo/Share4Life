from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.db.models import F
from django.utils import timezone

from .models import (
    CustomUser,
    UserProfile,
    FamilyMember,
    KYCProfile,
    KYCDocument,
)


# -----------------------------
# Inlines
# -----------------------------
class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    extra = 0
    verbose_name_plural = "Profile (Medical/Location)"
    fk_name = "user"


# -----------------------------
# Custom User
# -----------------------------
@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    inlines = (UserProfileInline,)

    list_display = (
        "username",
        "email",
        "phone_number",
        "is_donor",
        "is_recipient",
        "is_hospital_admin",
        "is_verified",
        "email_verified",
        "points",
        "is_staff",
        "is_active",
        "date_joined",
    )
    list_filter = (
        "is_donor",
        "is_recipient",
        "is_hospital_admin",
        "is_verified",
        "email_verified",
        "is_staff",
        "is_active",
    )
    search_fields = ("username", "email", "phone_number", "first_name", "last_name")
    ordering = ("-date_joined",)

    # show points from related profile (safe if missing)
    @admin.display(description="Points")
    def points(self, obj):
        prof = getattr(obj, "profile", None)
        return getattr(prof, "points", 0) if prof else 0

    fieldsets = UserAdmin.fieldsets + (
        ("Share4Life Roles / Flags", {
            "fields": (
                "is_donor",
                "is_recipient",
                "is_hospital_admin",
                "is_verified",
                "email_verified",
            )
        }),
        ("Contact / Media", {
            "fields": ("phone_number", "profile_image")
        }),
    )

    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Share4Life Roles / Flags", {
            "fields": (
                "is_donor",
                "is_recipient",
                "is_hospital_admin",
                "is_verified",
                "email_verified",
                "phone_number",
            )
        }),
    )


# Optional: register profile separately too (helpful for quick edits/search)
@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "blood_group", "city", "points", "latitude", "longitude")
    list_filter = ("blood_group", "city")
    search_fields = ("user__username", "user__email", "city")
    autocomplete_fields = ("user",)


@admin.register(FamilyMember)
class FamilyMemberAdmin(admin.ModelAdmin):
    list_display = ("id", "primary_user", "name", "relationship", "blood_group", "city", "is_emergency_profile")
    list_filter = ("is_emergency_profile", "city", "blood_group")
    search_fields = ("name", "relationship", "primary_user__username", "primary_user__email", "city")
    autocomplete_fields = ("primary_user",)


# -----------------------------
# KYC
# -----------------------------
@admin.register(KYCProfile)
class KYCProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "status", "submitted_at", "reviewed_at", "reviewed_by")
    list_filter = ("status",)
    search_fields = ("user__username", "user__email", "id_number")
    autocomplete_fields = ("user", "reviewed_by")
    readonly_fields = ("submitted_at",)

    actions = ["approve_kyc", "reject_kyc"]

    def _sync_user_verified(self, kyc: KYCProfile):
        u = kyc.user
        u.is_verified = (kyc.status == "APPROVED")
        u.save(update_fields=["is_verified"])

    def _award_kyc_points_once(self, user):
        # +200 points on KYC approval (safe)
        try:
            UserProfile.objects.filter(user=user).update(points=F("points") + 200)
        except Exception:
            pass

    def save_model(self, request, obj, form, change):
        old_status = None
        if change and obj.pk:
            old_status = KYCProfile.objects.filter(pk=obj.pk).values_list("status", flat=True).first()

        # mark review info when changed in admin
        if change:
            obj.reviewed_at = timezone.now()
            obj.reviewed_by = request.user

        super().save_model(request, obj, form, change)

        # sync user verified flag
        self._sync_user_verified(obj)

        # award points only if transitioned into APPROVED
        if old_status != "APPROVED" and obj.status == "APPROVED":
            self._award_kyc_points_once(obj.user)

    @admin.action(description="Approve selected KYC (marks user verified)")
    def approve_kyc(self, request, queryset):
        for kyc in queryset.select_related("user"):
            old_status = kyc.status

            kyc.status = "APPROVED"
            kyc.reviewed_at = timezone.now()
            kyc.reviewed_by = request.user
            kyc.rejection_reason = ""
            kyc.save(update_fields=["status", "reviewed_at", "reviewed_by", "rejection_reason"])

            self._sync_user_verified(kyc)

            if old_status != "APPROVED":
                self._award_kyc_points_once(kyc.user)

    @admin.action(description="Reject selected KYC (marks user not verified)")
    def reject_kyc(self, request, queryset):
        for kyc in queryset.select_related("user"):
            kyc.status = "REJECTED"
            kyc.reviewed_at = timezone.now()
            kyc.reviewed_by = request.user
            if not kyc.rejection_reason:
                kyc.rejection_reason = "Rejected by admin."
            kyc.save(update_fields=["status", "reviewed_at", "reviewed_by", "rejection_reason"])
            self._sync_user_verified(kyc)


@admin.register(KYCDocument)
class KYCDocumentAdmin(admin.ModelAdmin):
    list_display = ("kyc", "doc_type", "uploaded_at")
    list_filter = ("doc_type",)
    search_fields = ("kyc__user__username", "kyc__user__email")
    autocomplete_fields = ("kyc",)