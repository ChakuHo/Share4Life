from django.contrib import admin
from .models import BloodDonation

@admin.register(BloodDonation)
class BloodDonationAdmin(admin.ModelAdmin):
    list_display = ("id", "donor_user", "status", "donated_at", "units", "hospital_name")
    list_filter = ("status",)
    search_fields = ("donor_user__username", "hospital_name")

    actions = ["mark_verified"]

    def mark_verified(self, request, queryset):
        for d in queryset:
            d.mark_verified(request.user)
    mark_verified.short_description = "Mark selected donations as VERIFIED"