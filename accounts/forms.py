from django import forms
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm
from .models import CustomUser, UserProfile
from .models import FamilyMember


class RegistrationForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput)
    confirm_password = forms.CharField(widget=forms.PasswordInput)
    phone = forms.CharField(max_length=15, required=True)
    city = forms.CharField(max_length=100, required=True)

    class Meta:
        model = CustomUser
        fields = ["first_name", "last_name", "username", "email", "password"]

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")

        if password and confirm_password and password != confirm_password:
            self.add_error("confirm_password", "Passwords do not match")

        return cleaned_data  

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if CustomUser.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Email is already registered")
        return email

    def clean_username(self):
        username = (self.cleaned_data.get("username") or "").strip()
        if CustomUser.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("Username is already taken")
        return username


class BootstrapPasswordResetForm(PasswordResetForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].widget.attrs.update({
            "class": "form-control",
            "placeholder": "Enter your email",
        })

class BootstrapSetPasswordForm(SetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["new_password1"].widget.attrs.update({"class": "form-control"})
        self.fields["new_password2"].widget.attrs.update({"class": "form-control"})

    def clean_new_password2(self):
        new_password2 = super().clean_new_password2()

        # Blocking reuse of the current password
        if self.user and self.user.check_password(new_password2):
            raise forms.ValidationError("New password must be different from your current password.")

        return new_password2
    

class FamilyMemberForm(forms.ModelForm):
    # give blood group a dropdown
    blood_group = forms.ChoiceField(
        choices=[("", "— Select —")] + list(UserProfile.BLOOD_GROUPS),
        required=False,
    )

    class Meta:
        model = FamilyMember
        fields = [
            "name",
            "relationship",
            "phone_number",

            "is_emergency_profile",

            "blood_group",
            "date_of_birth",
            "medical_history",

            "city",
            "latitude",
            "longitude",
        ]
        widgets = {
            "date_of_birth": forms.DateInput(attrs={"type": "date"}),
            "medical_history": forms.Textarea(attrs={"rows": 3}),
            "latitude": forms.NumberInput(attrs={"step": "0.000001"}),
            "longitude": forms.NumberInput(attrs={"step": "0.000001"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Bootstrap classes
        for k, f in self.fields.items():
            if isinstance(f.widget, forms.CheckboxInput):
                f.widget.attrs.setdefault("class", "custom-control-input")
            elif isinstance(f.widget, (forms.FileInput,)):
                f.widget.attrs.setdefault("class", "form-control-file")
            else:
                f.widget.attrs.setdefault("class", "form-control")

        self.fields["is_emergency_profile"].label = "Mark as Emergency Profile"
        self.fields["is_emergency_profile"].help_text = (
            "Emergency profiles can be used for one-click emergency blood requests."
        )

    def clean(self):
        cleaned = super().clean()
        is_em = bool(cleaned.get("is_emergency_profile"))

        # Only enforcing these fields when user wants emergency profile
        if is_em:
            bg = (cleaned.get("blood_group") or "").strip()
            city = (cleaned.get("city") or "").strip()

            if not bg:
                self.add_error("blood_group", "Blood group is required for an emergency profile.")
            if not city:
                self.add_error("city", "City is required for an emergency profile.")

        return cleaned
    

class UserBasicsForm(forms.ModelForm):
    class Meta:
        model = CustomUser
        fields = ["first_name", "last_name", "phone_number", "profile_image"]
        widgets = {
            "first_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "First name"}),
            "last_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Last name"}),
            "phone_number": forms.TextInput(attrs={"class": "form-control", "placeholder": "Phone number"}),
        }

class UserProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = [
            "blood_group",
            "medical_history",
            "city", "latitude", "longitude",
            "date_of_birth", "gender",
            "address_line", "state", "postal_code", "country",
            "emergency_contact_name", "emergency_contact_phone",
        ]
        widgets = {
            "blood_group": forms.Select(attrs={"class": "form-control"}),
            "medical_history": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Allergies, surgeries, etc."}),
            "city": forms.TextInput(attrs={"class": "form-control", "placeholder": "City"}),
            "latitude": forms.NumberInput(attrs={"class": "form-control", "placeholder": "Latitude (optional)"}),
            "longitude": forms.NumberInput(attrs={"class": "form-control", "placeholder": "Longitude (optional)"}),

            "date_of_birth": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "gender": forms.TextInput(attrs={"class": "form-control", "placeholder": "Gender (optional)"}),

            "address_line": forms.TextInput(attrs={"class": "form-control", "placeholder": "Address line"}),
            "state": forms.TextInput(attrs={"class": "form-control", "placeholder": "State/Province"}),
            "postal_code": forms.TextInput(attrs={"class": "form-control", "placeholder": "Postal code"}),
            "country": forms.TextInput(attrs={"class": "form-control", "placeholder": "Country"}),

            "emergency_contact_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Emergency contact name"}),
            "emergency_contact_phone": forms.TextInput(attrs={"class": "form-control", "placeholder": "Emergency contact phone"}),
        }

class UserRoleForm(forms.ModelForm):
    class Meta:
        model = CustomUser
        fields = ["is_donor", "is_recipient"]
        widgets = {
            "is_donor": forms.CheckboxInput(attrs={"class": "custom-control-input"}),
            "is_recipient": forms.CheckboxInput(attrs={"class": "custom-control-input"}),
        }