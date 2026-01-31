from django import forms
from .models import (
    OrganPledge, OrganPledgeDocument,
    OrganRequest, OrganRequestDocument,
    OrganMatch
)

class OrganPledgeForm(forms.ModelForm):
    organs = forms.MultipleChoiceField(
        choices=OrganPledge.ORGANS,
        widget=forms.CheckboxSelectMultiple,
        required=True,
    )

    class Meta:
        model = OrganPledge
        fields = ["pledge_type", "organs", "consent_confirmed", "note"]
        widgets = {
            "pledge_type": forms.Select(attrs={"class": "form-control"}),
            "note": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "consent_confirmed": forms.CheckboxInput(attrs={"class": "custom-control-input"}),
        }

    def clean_organs(self):
        v = self.cleaned_data.get("organs") or []
        if not v:
            raise forms.ValidationError("Select at least one organ.")
        return v

    def clean_consent_confirmed(self):
        ok = bool(self.cleaned_data.get("consent_confirmed"))
        if not ok:
            raise forms.ValidationError("You must confirm consent to submit a pledge.")
        return ok


class OrganPledgeDocumentForm(forms.ModelForm):
    class Meta:
        model = OrganPledgeDocument
        fields = ["doc_type", "file", "note"]
        widgets = {
            "doc_type": forms.Select(attrs={"class": "form-control"}),
            "file": forms.ClearableFileInput(attrs={"class": "form-control-file", "accept": ".pdf,.jpg,.jpeg,.png"}),
            "note": forms.TextInput(attrs={"class": "form-control", "placeholder": "Optional note"}),
        }


class OrganRequestForm(forms.ModelForm):
    class Meta:
        model = OrganRequest
        fields = ["patient_name", "organ_needed", "urgency", "hospital_name", "city", "contact_phone", "note"]
        widgets = {
            "patient_name": forms.TextInput(attrs={"class": "form-control"}),
            "organ_needed": forms.Select(attrs={"class": "form-control"}),
            "urgency": forms.Select(attrs={"class": "form-control"}),
            "hospital_name": forms.TextInput(attrs={"class": "form-control"}),
            "city": forms.TextInput(attrs={"class": "form-control"}),
            "contact_phone": forms.TextInput(attrs={"class": "form-control", "type": "tel"}),
            "note": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }


class OrganRequestDocumentForm(forms.ModelForm):
    class Meta:
        model = OrganRequestDocument
        fields = ["doc_type", "file", "note"]
        widgets = {
            "doc_type": forms.Select(attrs={"class": "form-control"}),
            "file": forms.ClearableFileInput(attrs={"class": "form-control-file", "accept": ".pdf,.jpg,.jpeg,.png"}),
            "note": forms.TextInput(attrs={"class": "form-control", "placeholder": "Optional note"}),
        }


class OrganMatchCreateForm(forms.ModelForm):
    class Meta:
        model = OrganMatch
        fields = ["pledge", "notes"]
        widgets = {
            "pledge": forms.Select(attrs={"class": "form-control"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Optional notes"}),
        }


class OrganMatchStatusForm(forms.ModelForm):
    class Meta:
        model = OrganMatch
        fields = ["status", "notes"]
        widgets = {
            "status": forms.Select(attrs={"class": "form-control"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }