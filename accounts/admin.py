from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, UserProfile
from django.utils import timezone
from .models import KYCProfile, KYCDocument

class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = 'Medical Profile'

class CustomUserAdmin(UserAdmin):
    inlines = (UserProfileInline,)
    
    # What you see in the User List
    list_display = ('username', 'email', 'is_donor', 'is_recipient', 'is_verified', 'is_staff')
    
    # Filter sidebar
    list_filter = ('is_donor', 'is_recipient', 'is_verified', 'is_staff')
    
    # Add custom fields to the "Edit User" page
    fieldsets = UserAdmin.fieldsets + (
        ('Share4Life Roles', {'fields': ('is_donor', 'is_recipient', 'is_hospital_admin', 'is_verified', 'phone_number')}),
    )

admin.site.register(CustomUser, CustomUserAdmin)


@admin.register(KYCProfile)
class KYCProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "status", "submitted_at", "reviewed_at")
    list_filter = ("status",)
    search_fields = ("user__username", "user__email", "id_number")

    actions = ["approve_kyc", "reject_kyc"]

    def approve_kyc(self, request, queryset):
        for kyc in queryset:
            kyc.status = "APPROVED"
            kyc.reviewed_at = timezone.now()
            kyc.reviewed_by = request.user
            kyc.rejection_reason = ""
            kyc.save()

            kyc.user.is_verified = True
            kyc.user.save(update_fields=["is_verified"])
    approve_kyc.short_description = "Approve selected KYC"

    def reject_kyc(self, request, queryset):
        for kyc in queryset:
            kyc.status = "REJECTED"
            kyc.reviewed_at = timezone.now()
            kyc.reviewed_by = request.user
            kyc.save()
    reject_kyc.short_description = "Reject selected KYC"


@admin.register(KYCDocument)
class KYCDocumentAdmin(admin.ModelAdmin):
    list_display = ("kyc", "doc_type", "uploaded_at")
    list_filter = ("doc_type",)