import re
from django import forms
from .models import Organization, OrganizationMembership, BloodCampaign

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
            "blood_groups_needed": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "e.g. O+, O-, A+"}
            ),
            "status": forms.Select(attrs={"class": "form-control"}),
        }
