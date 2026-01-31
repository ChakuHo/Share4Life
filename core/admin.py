from django.contrib import admin
from .models import SiteSetting, TeamMember, GalleryImage


@admin.register(SiteSetting)
class SiteSettingAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not SiteSetting.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TeamMember)
class TeamMemberAdmin(admin.ModelAdmin):
    list_display = ("name", "role", "order", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "role")
    ordering = ("order", "name")


@admin.register(GalleryImage)
class GalleryImageAdmin(admin.ModelAdmin):
    list_display = (
        "title", "event_date", "city",
        "blood_units_collected", "funds_raised", "people_helped",
        "order", "is_active",
    )
    list_filter = ("is_active", "city")
    search_fields = ("title", "city", "venue", "description")
    ordering = ("order", "-event_date", "-created_at")