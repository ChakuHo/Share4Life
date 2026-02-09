from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, UserProfile
from django.utils import timezone
from .models import KYCProfile, KYCDocument
from django.db.models import F

class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = 'Medical Profile'

class CustomUserAdmin(UserAdmin):
    inlines = (UserProfileInline,)

    list_display = ('username', 'email', 'is_donor', 'is_recipient', 'is_verified', 'is_staff')
    list_filter = ('is_donor', 'is_recipient', 'is_verified', 'is_staff')

    fieldsets = UserAdmin.fieldsets + (
        ('Share4Life Roles', {'fields': ('is_donor', 'is_recipient', 'is_hospital_admin', 'is_verified', 'phone_number')}),
    )

admin.site.register(CustomUser, CustomUserAdmin)


@admin.register(KYCProfile)
class KYCProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "status", "submitted_at", "reviewed_at", "reviewed_by")
    list_filter = ("status",)
    search_fields = ("user__username", "user__email", "id_number")

    actions = ["approve_kyc", "reject_kyc"]

    def _sync_user_verified(self, kyc: KYCProfile):
        u = kyc.user
        u.is_verified = (kyc.status == "APPROVED")
        u.save(update_fields=["is_verified"])

    def _award_kyc_points_if_needed(self, user, old_verified: bool):
        """
        Award +200 points when user becomes verified via KYC (only once per transition).
        """
        if old_verified:
            return
        try:
            UserProfile.objects.filter(user=user).update(points=F("points") + 200)
        except Exception:
            pass

    def save_model(self, request, obj, form, change):
        old_verified = False
        old_status = None

        if change and obj.pk:
            old_status = KYCProfile.objects.filter(pk=obj.pk).values_list("status", flat=True).first()
            # "old verified" means old_status was APPROVED
            old_verified = (old_status == "APPROVED")

        if change:
            obj.reviewed_at = timezone.now()
            obj.reviewed_by = request.user

        super().save_model(request, obj, form, change)
        self._sync_user_verified(obj)

        # Award points only if transitioned into APPROVED
        if (old_status != "APPROVED") and (obj.status == "APPROVED"):
            self._award_kyc_points_if_needed(obj.user, old_verified=False)

    def approve_kyc(self, request, queryset):
        for kyc in queryset:
            old_status = kyc.status
            was_verified = (old_status == "APPROVED")

            kyc.status = "APPROVED"
            kyc.reviewed_at = timezone.now()
            kyc.reviewed_by = request.user
            kyc.rejection_reason = ""
            kyc.save(update_fields=["status", "reviewed_at", "reviewed_by", "rejection_reason"])
            self._sync_user_verified(kyc)

            if (not was_verified) and old_status != "APPROVED":
                self._award_kyc_points_if_needed(kyc.user, old_verified=False)

    approve_kyc.short_description = "Approve selected KYC (marks user verified)"

    def reject_kyc(self, request, queryset):
        for kyc in queryset:
            kyc.status = "REJECTED"
            kyc.reviewed_at = timezone.now()
            kyc.reviewed_by = request.user
            if not kyc.rejection_reason:
                kyc.rejection_reason = "Rejected by admin."
            kyc.save(update_fields=["status", "reviewed_at", "reviewed_by", "rejection_reason"])
            self._sync_user_verified(kyc)

    reject_kyc.short_description = "Reject selected KYC (marks user not verified)"


@admin.register(KYCDocument)
class KYCDocumentAdmin(admin.ModelAdmin):
    list_display = ("kyc", "doc_type", "uploaded_at")
    list_filter = ("doc_type",)
    search_fields = ("kyc__user__username", "kyc__user__email")