import re
from django import forms
from .models import PublicBloodRequest, GuestResponse, DonorResponse, BloodDonation, DonationMedicalReport

PHONE_RE = re.compile(r"^[0-9+\-\s]{7,20}$")

class EmergencyRequestForm(forms.ModelForm):
    class Meta:
        model = PublicBloodRequest
        fields = ['patient_name', 'blood_group', 'contact_phone', 'location_city', 'hospital_name', 'units_needed', 'is_emergency', 'proof_document']
        widgets = {
            'patient_name': forms.TextInput(attrs={'class': 'form-control'}),
            'blood_group': forms.Select(attrs={'class': 'form-control'}),
            'contact_phone': forms.TextInput(attrs={'class': 'form-control'}),
            'location_city': forms.TextInput(attrs={'class': 'form-control'}),
            'hospital_name': forms.TextInput(attrs={'class': 'form-control'}),
            'units_needed': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'is_emergency': forms.CheckboxInput(attrs={'class': 'custom-control-input'}),
            'proof_document': forms.ClearableFileInput(attrs={'class': 'form-control-file', 'accept': '.pdf,.jpg,.jpeg,.png'}),
        }

    def clean_proof_document(self):
        f = self.cleaned_data.get("proof_document")
        if not f:
            raise forms.ValidationError("Hospital proof document is required.")
        if f.size > 5 * 1024 * 1024:
            raise forms.ValidationError("File too large. Max 5MB.")
        return f
    

    def clean_contact_phone(self):
        v = (self.cleaned_data.get("contact_phone") or "").strip()
        if not PHONE_RE.match(v):
            raise forms.ValidationError("Enter a valid phone number.")
        return v

    def clean_units_needed(self):
        u = self.cleaned_data.get("units_needed") or 1
        if u < 1:
            raise forms.ValidationError("Units must be at least 1.")
        return u


class RecipientRequestForm(forms.ModelForm):
    class Meta:
        model = PublicBloodRequest
        fields = ['patient_name', 'blood_group', 'contact_phone', 'location_city', 'hospital_name', 'units_needed', 'is_emergency', 'proof_document']
        widgets = {
            'patient_name': forms.TextInput(attrs={'class': 'form-control'}),
            'blood_group': forms.Select(attrs={'class': 'form-control'}),
            'contact_phone': forms.TextInput(attrs={'class': 'form-control'}),
            'location_city': forms.TextInput(attrs={'class': 'form-control'}),
            'hospital_name': forms.TextInput(attrs={'class': 'form-control'}),
            'units_needed': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'is_emergency': forms.CheckboxInput(attrs={'class': 'custom-control-input'}),
            'proof_document': forms.ClearableFileInput(attrs={'class': 'form-control-file', 'accept': '.pdf,.jpg,.jpeg,.png'}),
        }

    def __init__(self, *args, require_proof=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.require_proof = require_proof

    def clean_contact_phone(self):
        v = (self.cleaned_data.get("contact_phone") or "").strip()
        if not PHONE_RE.match(v):
            raise forms.ValidationError("Enter a valid phone number.")
        return v

    def clean_units_needed(self):
        u = self.cleaned_data.get("units_needed") or 1
        if u < 1:
            raise forms.ValidationError("Units must be at least 1.")
        return u

    def clean_proof_document(self):
        f = self.cleaned_data.get("proof_document")
        if self.require_proof and not f:
            raise forms.ValidationError("Proof document is required until your KYC is verified.")
        if f and f.size > 5 * 1024 * 1024:
            raise forms.ValidationError("File too large. Max 5MB.")
        return f


class GuestResponseForm(forms.ModelForm):
    class Meta:
        model = GuestResponse
        fields = ['donor_name', 'donor_phone']
        widgets = {
            'donor_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Your Name'}),
            'donor_phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Your Phone Number'}),
        }

    def clean_donor_phone(self):
        v = (self.cleaned_data.get("donor_phone") or "").strip()
        if not PHONE_RE.match(v):
            raise forms.ValidationError("Enter a valid phone number.")
        return v


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
            "hospital_name": forms.TextInput(attrs={"class": "form-control"}),
            "units": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
            "donated_at": forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
        }


class DonationReportForm(forms.ModelForm):
    class Meta:
        model = DonationMedicalReport
        fields = ["file", "note"]
        widgets = {
            "file": forms.ClearableFileInput(attrs={"class": "form-control-file", "accept": ".pdf,.jpg,.jpeg,.png"}),
            "note": forms.TextInput(attrs={"class": "form-control", "placeholder": "Optional note"}),
        }