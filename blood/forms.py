from django import forms
import phonenumbers
from phonenumbers.phonenumberutil import NumberParseException

from .models import (
    PublicBloodRequest,
    GuestResponse,
    DonorResponse,
    BloodDonation,
    DonationMedicalReport,
)

MAX_UPLOAD_MB = 5
DEFAULT_PHONE_REGION = "NP"


def clean_phone(value: str, default_region: str = DEFAULT_PHONE_REGION) -> str:
    """
    Validates and normalizes phone numbers into E.164 (e.g. +9779812345678).
    Accepts inputs like:
      - 9812345678
      - +9779812345678
      - +977-9812345678
    """
    v = (value or "").strip()
    if not v:
        raise forms.ValidationError("Phone number is required.")

    try:
        num = phonenumbers.parse(v, default_region)
    except NumberParseException:
        raise forms.ValidationError("Enter a valid phone number.")

    if not phonenumbers.is_valid_number(num):
        raise forms.ValidationError("Enter a valid phone number.")

    return phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)


def clean_upload(f, label="File"):
    if not f:
        raise forms.ValidationError(f"{label} is required.")
    if f.size > MAX_UPLOAD_MB * 1024 * 1024:
        raise forms.ValidationError(f"File too large. Max {MAX_UPLOAD_MB}MB.")
    return f


class EmergencyRequestForm(forms.ModelForm):
    class Meta:
        model = PublicBloodRequest
        fields = [
            "patient_name",
            "blood_group",
            "contact_phone",
            "location_city",
            "hospital_name",
            "units_needed",
            "is_emergency",
            "proof_document",
        ]
        widgets = {
            "patient_name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Patient full name",
                "maxlength": "100",
            }),
            "blood_group": forms.Select(attrs={"class": "form-control"}),

            "contact_phone": forms.TextInput(attrs={
                "class": "form-control",
                "type": "tel",
                "inputmode": "numeric",
                "placeholder": "+97798XXXXXXXX or 98XXXXXXXX",
                "maxlength": "20",
            }),

            "location_city": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "City / Area",
                "maxlength": "100",
            }),
            "hospital_name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Hospital name",
                "maxlength": "150",
            }),
            "units_needed": forms.NumberInput(attrs={
                "class": "form-control",
                "min": 1,
                "max": 10,
                "step": 1,
            }),

            # You may keep it; your view forces emergency=True anyway
            "is_emergency": forms.CheckboxInput(attrs={"class": "custom-control-input"}),

            "proof_document": forms.ClearableFileInput(attrs={
                "class": "form-control-file",
                "accept": ".pdf,.jpg,.jpeg,.png",
            }),
        }

    def clean_contact_phone(self):
        return clean_phone(self.cleaned_data.get("contact_phone"))

    def clean_units_needed(self):
        u = self.cleaned_data.get("units_needed") or 1
        if u < 1:
            raise forms.ValidationError("Units must be at least 1.")
        return u

    def clean_proof_document(self):
        f = self.cleaned_data.get("proof_document")
        return clean_upload(f, label="Hospital proof document")


class RecipientRequestForm(forms.ModelForm):
    class Meta:
        model = PublicBloodRequest
        fields = [
            "patient_name",
            "blood_group",
            "contact_phone",
            "location_city",
            "hospital_name",
            "units_needed",
            "is_emergency",
            "proof_document",
        ]
        widgets = {
            "patient_name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Patient full name",
                "maxlength": "100",
            }),
            "blood_group": forms.Select(attrs={"class": "form-control"}),

            "contact_phone": forms.TextInput(attrs={
                "class": "form-control",
                "type": "tel",
                "inputmode": "numeric",
                "placeholder": "+97798XXXXXXXX or 98XXXXXXXX",
                "maxlength": "20",
            }),

            "location_city": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "City / Area",
                "maxlength": "100",
            }),
            "hospital_name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Hospital name",
                "maxlength": "150",
            }),
            "units_needed": forms.NumberInput(attrs={
                "class": "form-control",
                "min": 1,
                "max": 10,
                "step": 1,
            }),

            "is_emergency": forms.CheckboxInput(attrs={"class": "custom-control-input"}),

            "proof_document": forms.ClearableFileInput(attrs={
                "class": "form-control-file",
                "accept": ".pdf,.jpg,.jpeg,.png",
            }),
        }

    def __init__(self, *args, require_proof=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.require_proof = require_proof

    def clean_contact_phone(self):
        return clean_phone(self.cleaned_data.get("contact_phone"))

    def clean_units_needed(self):
        u = self.cleaned_data.get("units_needed") or 1
        if u < 1:
            raise forms.ValidationError("Units must be at least 1.")
        return u

    def clean_proof_document(self):
        f = self.cleaned_data.get("proof_document")
        if self.require_proof and not f:
            raise forms.ValidationError("Proof document is required until your KYC is verified.")
        if f:
            clean_upload(f, label="Proof document")
        return f


class GuestResponseForm(forms.ModelForm):
    class Meta:
        model = GuestResponse
        fields = ["donor_name", "donor_phone"]
        widgets = {
            "donor_name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Your name",
                "maxlength": "100",
            }),
            "donor_phone": forms.TextInput(attrs={
                "class": "form-control",
                "type": "tel",
                "inputmode": "numeric",
                "placeholder": "+97798XXXXXXXX or 98XXXXXXXX",
                "maxlength": "20",
            }),
        }

    def clean_donor_phone(self):
        return clean_phone(self.cleaned_data.get("donor_phone"))


class DonorResponseForm(forms.ModelForm):
    class Meta:
        model = DonorResponse
        fields = ["status", "message"]
        widgets = {
            "status": forms.Select(attrs={"class": "form-control"}),
            "message": forms.TextInput(attrs={"class": "form-control", "placeholder": "Optional note"}),
        }


class DonationCreateForm(forms.ModelForm):
    class Meta:
        model = BloodDonation
        fields = ["hospital_name", "units", "donated_at"]
        widgets = {
            "hospital_name": forms.TextInput(attrs={"class": "form-control", "maxlength": "150"}),
            "units": forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 4, "step": 1}),
            "donated_at": forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
        }


class DonationReportForm(forms.ModelForm):
    class Meta:
        model = DonationMedicalReport
        fields = ["file", "note"]
        widgets = {
            "file": forms.ClearableFileInput(attrs={
                "class": "form-control-file",
                "accept": ".pdf,.jpg,.jpeg,.png",
            }),
            "note": forms.TextInput(attrs={"class": "form-control", "placeholder": "Optional note"}),
        }

    def clean_file(self):
        f = self.cleaned_data.get("file")
        return clean_upload(f, label="Medical report file")


class BloodRequestEditForm(forms.ModelForm):
    class Meta:
        model = PublicBloodRequest
        fields = [
            "patient_name",
            "blood_group",
            "contact_phone",
            "location_city",
            "hospital_name",
            "units_needed",
            "is_emergency",
            "proof_document",
        ]
        widgets = {
            "patient_name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Patient full name",
                "maxlength": "100",
            }),
            "blood_group": forms.Select(attrs={"class": "form-control"}),

            "contact_phone": forms.TextInput(attrs={
                "class": "form-control",
                "type": "tel",
                "inputmode": "numeric",
                "placeholder": "+97798XXXXXXXX or 98XXXXXXXX",
                "maxlength": "20",
            }),

            "location_city": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "City / Area",
                "maxlength": "100",
            }),
            "hospital_name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Hospital name",
                "maxlength": "150",
            }),
            "units_needed": forms.NumberInput(attrs={
                "class": "form-control",
                "min": 1,
                "max": 10,
                "step": 1,
            }),

            "is_emergency": forms.CheckboxInput(attrs={"class": "custom-control-input"}),

            "proof_document": forms.ClearableFileInput(attrs={
                "class": "form-control-file",
                "accept": ".pdf,.jpg,.jpeg,.png",
            }),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_contact_phone(self):
        return clean_phone(self.cleaned_data.get("contact_phone"))

    def clean_units_needed(self):
        u = self.cleaned_data.get("units_needed") or 1
        if u < 1:
            raise forms.ValidationError("Units must be at least 1.")
        return u

    def clean_proof_document(self):
        f = self.cleaned_data.get("proof_document")

        # If already has proof, don’t force re-upload
        if (not f) and self.instance and self.instance.proof_document:
            return self.instance.proof_document

        return clean_upload(f, label="Proof document")