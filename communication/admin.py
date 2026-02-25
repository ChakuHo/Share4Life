from django.contrib import admin
from .models import (
    Notification, NotificationPreference, QueuedEmail,
    ChatThread, ChatMessage
)

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "category", "level", "title", "created_at", "read_at")
    list_filter = ("category", "level", "created_at", "read_at")
    search_fields = ("user__username", "user__email", "title", "body", "url")
    readonly_fields = ("created_at",)

@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ("user", "email_enabled", "email_emergency_only", "updated_at")
    search_fields = ("user__username", "user__email")
    readonly_fields = ("updated_at",)

@admin.register(QueuedEmail)
class QueuedEmailAdmin(admin.ModelAdmin):
    list_display = ("id", "to_email", "subject", "status", "attempts", "created_at", "sent_at")
    list_filter = ("status", "created_at", "sent_at")
    search_fields = ("to_email", "subject", "body")
    readonly_fields = ("created_at", "sent_at")

class ChatMessageInline(admin.TabularInline):
    model = ChatMessage
    extra = 0
    readonly_fields = ("sender", "body", "created_at")
    can_delete = False

@admin.register(ChatThread)
class ChatThreadAdmin(admin.ModelAdmin):
    list_display = ("id", "request", "requester", "donor", "last_message_at", "created_at", "updated_at")
    list_filter = ("created_at", "updated_at", "last_message_at")
    search_fields = (
        "requester__username", "requester__email",
        "donor__username", "donor__email",
        "request__patient_name", "request__hospital_name", "request__location_city"
    )
    readonly_fields = ("created_at", "updated_at")
    inlines = [ChatMessageInline]

@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "thread", "sender", "created_at")
    list_filter = ("created_at",)
    search_fields = ("sender__username", "body")
    readonly_fields = ("created_at",)