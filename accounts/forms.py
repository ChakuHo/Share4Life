from django import forms
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm
from .models import CustomUser


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