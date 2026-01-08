from django import forms
from .models import KYCProfile

MAX_UPLOAD_MB = 5

def validate_size(f):
    if f.size > MAX_UPLOAD_MB * 1024 * 1024:
        raise forms.ValidationError(f"File too large. Max {MAX_UPLOAD_MB}MB.")

class KYCProfileForm(forms.ModelForm):
    class Meta:
        model = KYCProfile
        fields = ["full_name", "id_type", "id_number"]
        widgets = {
            "full_name": forms.TextInput(attrs={"class": "form-control"}),
            "id_type": forms.TextInput(attrs={"class": "form-control"}),
            "id_number": forms.TextInput(attrs={"class": "form-control"}),
        }

class KYCUploadForm(forms.Form):
    id_front = forms.FileField(required=True)
    id_back = forms.FileField(required=False)
    selfie = forms.FileField(required=True)
    address_proof = forms.FileField(required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            f.widget.attrs.update({"class": "form-control-file"})

    def clean(self):
        cleaned = super().clean()
        for key in ["id_front", "id_back", "selfie", "address_proof"]:
            f = cleaned.get(key)
            if f:
                validate_size(f)
        return cleaned