from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, UserProfile

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