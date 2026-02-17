from django.contrib import admin
from .models import SiteSetting, TeamMember, GalleryImage


@admin.register(SiteSetting)
class SiteSettingAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not SiteSetting.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    fieldsets = (
        ("Branding", {"fields": ("site_name", "site_logo", "favicon")}),
        ("Homepage Hero", {"fields": ("hero_title", "hero_subtitle", "hero_background")}),
        ("Contact Info", {"fields": ("contact_email", "contact_phone", "address")}),
        ("Social Media", {"fields": ("facebook_url", "twitter_url", "instagram_url")}),
        ("Footer", {"fields": ("footer_text",)}),
        ("About Page", {"fields": ("about_title", "about_intro", "about_trust_safety", "about_how_it_works")}),
        ("Legal / Footer Modals", {"fields": ("privacy_policy", "terms_of_service", "footer_faq")}),
    )


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