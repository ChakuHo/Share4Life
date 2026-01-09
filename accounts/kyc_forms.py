# accounts/kyc_forms.py
import os
from django import forms
from django.core.exceptions import ValidationError
from PIL import Image  # Pillow is already needed for your ImageField

from .models import KYCProfile

MAX_UPLOAD_MB = 5
ALLOWED_ID_TYPES = {"Citizenship", "Passport", "Driving License", "National ID"}

def _ext(name: str) -> str:
    return os.path.splitext(name)[1].lower().lstrip(".")

def validate_size(f):
    if f.size > MAX_UPLOAD_MB * 1024 * 1024:
        raise ValidationError(f"File too large. Max {MAX_UPLOAD_MB}MB.")

def validate_image_file(f):
    # Verify it is really an image (not just renamed file)
    try:
        img = Image.open(f)
        img.verify()
    except Exception:
        raise ValidationError("Invalid image file. Upload a clear JPG/PNG image.")

def validate_pdf_file(f):
    # Basic check (content_type can vary by browser)
    ext = _ext(f.name)
    if ext != "pdf":
        raise ValidationError("Only PDF allowed for this document.")

class KYCProfileForm(forms.ModelForm):
    class Meta:
        model = KYCProfile
        fields = ["full_name", "id_type", "id_number"]
        widgets = {
            "full_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Full name as on ID"}),
            "id_type": forms.Select(attrs={"class": "form-control"}),
            "id_number": forms.TextInput(attrs={"class": "form-control", "placeholder": "ID number"}),
        }

    id_type = forms.ChoiceField(
        choices=[(x, x) for x in sorted(ALLOWED_ID_TYPES)],
        widget=forms.Select(attrs={"class": "form-control"}),
        required=True
    )

    def clean_full_name(self):
        name = (self.cleaned_data.get("full_name") or "").strip()
        if len(name) < 3:
            raise ValidationError("Full name is required.")
        return name

    def clean_id_number(self):
        num = (self.cleaned_data.get("id_number") or "").strip()
        if len(num) < 4:
            raise ValidationError("ID number is required.")
        return num

class KYCUploadForm(forms.Form):
    id_front = forms.FileField(required=True)
    id_back = forms.FileField(required=False)
    selfie = forms.FileField(required=True)
    address_proof = forms.FileField(required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Better UX: restrict file picker
        self.fields["id_front"].widget.attrs.update({"class": "form-control-file", "accept": "image/jpeg,image/png"})
        self.fields["id_back"].widget.attrs.update({"class": "form-control-file", "accept": "image/jpeg,image/png"})
        self.fields["selfie"].widget.attrs.update({"class": "form-control-file", "accept": "image/jpeg,image/png"})
        self.fields["address_proof"].widget.attrs.update({"class": "form-control-file", "accept": "image/jpeg,image/png,application/pdf"})

    def clean(self):
        cleaned = super().clean()

        id_front = cleaned.get("id_front")
        selfie = cleaned.get("selfie")
        id_back = cleaned.get("id_back")
        address_proof = cleaned.get("address_proof")

        # Required files
        if not id_front:
            self.add_error("id_front", "ID front is required.")
        if not selfie:
            self.add_error("selfie", "Selfie is required.")

        # Validate required image files
        for field_name in ["id_front", "selfie"]:
            f = cleaned.get(field_name)
            if not f:
                continue
            validate_size(f)
            ext = _ext(f.name)
            if ext not in {"jpg", "jpeg", "png"}:
                self.add_error(field_name, "Only JPG/PNG allowed.")
                continue
            validate_image_file(f)

        # Optional: id_back must be image if provided
        if id_back:
            validate_size(id_back)
            ext = _ext(id_back.name)
            if ext not in {"jpg", "jpeg", "png"}:
                self.add_error("id_back", "Only JPG/PNG allowed.")
            else:
                validate_image_file(id_back)

        # Optional: address proof can be image OR pdf
        if address_proof:
            validate_size(address_proof)
            ext = _ext(address_proof.name)
            if ext in {"jpg", "jpeg", "png"}:
                validate_image_file(address_proof)
            elif ext == "pdf":
                validate_pdf_file(address_proof)
            else:
                self.add_error("address_proof", "Only JPG/PNG/PDF allowed.")

        return cleaned