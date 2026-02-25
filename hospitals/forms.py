from datetime import date
import re
from django import forms
from .models import Organization, OrganizationMembership, BloodCampaign
from django.utils import timezone

PHONE_RE = re.compile(r"^[0-9+\-\s]{7,20}$")


class OrganizationRegisterForm(forms.ModelForm):
    class Meta:
        model = Organization
        fields = ["name", "org_type", "email", "phone", "city", "address", "proof_document"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "org_type": forms.Select(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "city": forms.TextInput(attrs={"class": "form-control"}),
            "address": forms.TextInput(attrs={"class": "form-control"}),
            "proof_document": forms.ClearableFileInput(
                attrs={"class": "form-control-file", "accept": ".pdf,.jpg,.jpeg,.png"}
            ),
        }

    def clean_name(self):
        n = (self.cleaned_data["name"] or "").strip()
        if Organization.objects.filter(name__iexact=n).exists():
            raise forms.ValidationError("Organization with this name already exists.")
        return n

    def clean_phone(self):
        p = (self.cleaned_data.get("phone") or "").strip()
        if p and not PHONE_RE.match(p):
            raise forms.ValidationError("Enter a valid phone number.")
        return p

    def clean_proof_document(self):
        f = self.cleaned_data.get("proof_document")
        if not f:
            raise forms.ValidationError("Proof document is required.")
        if f.size > 5 * 1024 * 1024:
            raise forms.ValidationError("File too large. Max 5MB.")
        return f


class AddOrgMemberForm(forms.Form):
    identifier = forms.CharField(
        help_text="Enter username or email of an existing user",
        widget=forms.TextInput(attrs={"class": "form-control"})
    )
    role = forms.ChoiceField(
        choices=OrganizationMembership.ROLE,
        widget=forms.Select(attrs={"class": "form-control"})
    )


class BloodCampaignForm(forms.ModelForm):
    class Meta:
        model = BloodCampaign
        fields = [
            "title", "description",
            "date", "start_time", "end_time",
            "venue_name", "address", "city",
            "target_units", "blood_groups_needed",
            "status",

            # impact/proof
            "cover_image",
            "actual_units_collected",
            "actual_donors_count",
            "impact_highlights",
            "completion_report",
        ]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "start_time": forms.TimeInput(attrs={"class": "form-control", "type": "time"}),
            "end_time": forms.TimeInput(attrs={"class": "form-control", "type": "time"}),
            "venue_name": forms.TextInput(attrs={"class": "form-control"}),
            "address": forms.TextInput(attrs={"class": "form-control"}),
            "city": forms.TextInput(attrs={"class": "form-control"}),
            "target_units": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "blood_groups_needed": forms.TextInput(attrs={"class": "form-control"}),
            "status": forms.Select(attrs={"class": "form-control"}),

            "cover_image": forms.ClearableFileInput(attrs={"class": "form-control-file", "accept": "image/*"}),
            "actual_units_collected": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "actual_donors_count": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "impact_highlights": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "completion_report": forms.ClearableFileInput(
                attrs={"class": "form-control-file", "accept": ".pdf,.jpg,.jpeg,.png"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Recommended required fields
        self.fields["city"].required = True
        self.fields["venue_name"].required = True
        self.fields["date"].required = True
        self.fields["title"].required = True
        self.fields["status"].required = True

        # Keep cover optional always
        self.fields["cover_image"].required = False

        # These become required only when COMPLETED (enforced in clean())
        self.fields["actual_units_collected"].required = False
        self.fields["actual_donors_count"].required = False
        self.fields["impact_highlights"].required = False
        self.fields["completion_report"].required = False

        # UX: prevent selecting past date for new/upcoming/ongoing in the browser
        try:
            today_str = timezone.localdate().strftime("%Y-%m-%d")
            current_status = (getattr(self.instance, "status", "") or "").upper()
            if (not getattr(self.instance, "pk", None)) or (current_status in ("UPCOMING", "ONGOING")):
                self.fields["date"].widget.attrs["min"] = today_str
        except Exception:
            pass

    def clean(self):
        cleaned = super().clean()

        status = (cleaned.get("status") or "").upper()
        date = cleaned.get("date")
        start_time = cleaned.get("start_time")
        end_time = cleaned.get("end_time")
        city = (cleaned.get("city") or "").strip()
        target_units = cleaned.get("target_units")

        today = timezone.localdate()

        # City required (custom message)
        if not city:
            self.add_error("city", "City is required.")

        # Time validation if both provided
        if start_time and end_time and start_time >= end_time:
            self.add_error("end_time", "End time must be after start time.")

        # Target units validation (for active camps)
        if status in ("UPCOMING", "ONGOING"):
            if target_units is None or int(target_units) <= 0:
                self.add_error("target_units", "Target units must be greater than 0 for upcoming/ongoing campaigns.")

        # -------------------------
        # Date/status consistency
        # -------------------------
        if date:
            # No backdate for UPCOMING/ONGOING
            if status in ("UPCOMING", "ONGOING") and date < today:
                self.add_error("date", "You cannot create an upcoming/ongoing campaign in the past.")

            # Ongoing must be today (single-day event)
            if status == "ONGOING" and date != today:
                self.add_error("date", "Ongoing campaigns must be set for today. Use UPCOMING for future dates.")

            # Completed/Cancelled cannot be future
            if status in ("COMPLETED", "CANCELLED") and date > today:
                self.add_error("date", "Completed/Cancelled campaigns cannot be set in the future.")

        # -------------------------
        # COMPLETED requirements
        # -------------------------
        if status == "COMPLETED":
            if cleaned.get("actual_units_collected") in (None, ""):
                self.add_error("actual_units_collected", "Actual units collected is required for completed campaigns.")
            if cleaned.get("actual_donors_count") in (None, ""):
                self.add_error("actual_donors_count", "Donors count is required for completed campaigns.")
            if not (cleaned.get("impact_highlights") or "").strip():
                self.add_error("impact_highlights", "Impact highlights are required for completed campaigns.")

            # proof mandatory (if already uploaded previously, instance has it)
            has_existing = bool(getattr(self.instance, "completion_report", None))
            has_new = bool(cleaned.get("completion_report"))
            if not (has_existing or has_new):
                self.add_error("completion_report", "Completion proof/report is required for completed campaigns.")

        return cleaned