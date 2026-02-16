from django import forms
from .models import NotificationPreference

class NotificationPreferenceForm(forms.ModelForm):
    class Meta:
        model = NotificationPreference
        fields = [
            "mute_system", "mute_blood", "mute_emergency", "mute_donation",
            "mute_campaign", "mute_kyc", "mute_chat",
            "email_enabled", "email_emergency_only",
        ]