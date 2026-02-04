from django import forms
from django.utils import timezone
from .models import Campaign, CampaignDocument, Donation, Disbursement, CampaignReport


class CampaignCreateForm(forms.ModelForm):
    proof_type = forms.ChoiceField(choices=CampaignDocument.DOC_TYPE, required=True)
    proof_file = forms.FileField(required=True)

    class Meta:
        model = Campaign
        fields = [
            "title", "patient_name", "description", "image",
            "target_amount", "deadline",
            "hospital_name", "hospital_city", "hospital_contact_phone",
        ]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "patient_name": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 5}),
            "image": forms.ClearableFileInput(attrs={"class": "form-control-file", "accept": "image/*"}),
            "target_amount": forms.NumberInput(attrs={"class": "form-control", "min": "1"}),
            "deadline": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "hospital_name": forms.TextInput(attrs={"class": "form-control"}),
            "hospital_city": forms.TextInput(attrs={"class": "form-control"}),
            "hospital_contact_phone": forms.TextInput(attrs={"class": "form-control"}),
        }

    def clean_deadline(self):
        d = self.cleaned_data.get("deadline")
        if not d:
            raise forms.ValidationError("Deadline is required.")
        if d < timezone.localdate():
            raise forms.ValidationError("Deadline cannot be in the past.")
        return d

    def clean(self):
        cleaned = super().clean()
        for f in ("hospital_name", "hospital_city", "hospital_contact_phone"):
            if not (cleaned.get(f) or "").strip():
                self.add_error(f, "This field is required.")
        if not cleaned.get("proof_file"):
            self.add_error("proof_file", "Proof document is required.")
        return cleaned


class DonationForm(forms.ModelForm):
    class Meta:
        model = Donation
        fields = ["amount", "gateway", "guest_name", "guest_email", "guest_phone"]
        widgets = {
            "amount": forms.NumberInput(attrs={"class": "form-control", "min": "10"}),
            "gateway": forms.Select(attrs={"class": "form-control"}),
            "guest_name": forms.TextInput(attrs={"class": "form-control"}),
            "guest_email": forms.EmailInput(attrs={"class": "form-control"}),
            "guest_phone": forms.TextInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if user and user.is_authenticated:
            self.fields["guest_name"].required = False
            self.fields["guest_email"].required = False
            self.fields["guest_phone"].required = False
        else:
            self.fields["guest_name"].required = True
            self.fields["guest_phone"].required = True

    def clean_amount(self):
        amt = self.cleaned_data.get("amount")
        if amt is None or amt <= 0:
            raise forms.ValidationError("Amount must be greater than 0.")
        return amt


class DisbursementForm(forms.ModelForm):
    class Meta:
        model = Disbursement
        fields = ["amount", "proof_file", "note"]
        widgets = {
            "amount": forms.NumberInput(attrs={"class": "form-control", "min": "1"}),
            "proof_file": forms.ClearableFileInput(attrs={"class": "form-control-file", "accept": ".pdf,.jpg,.jpeg,.png"}),
            "note": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }


class CampaignReportForm(forms.ModelForm):
    class Meta:
        model = CampaignReport
        fields = ["reason", "message", "guest_name", "guest_email"]
        widgets = {
            "reason": forms.TextInput(attrs={"class": "form-control"}),
            "message": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "guest_name": forms.TextInput(attrs={"class": "form-control"}),
            "guest_email": forms.EmailInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user and user.is_authenticated:
            self.fields["guest_name"].required = False
            self.fields["guest_email"].required = False
        else:
            self.fields["guest_name"].required = True