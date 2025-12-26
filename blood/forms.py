from django import forms
from .models import PublicBloodRequest, GuestResponse

class EmergencyRequestForm(forms.ModelForm):
    class Meta:
        model = PublicBloodRequest
        fields = ['patient_name', 'blood_group', 'contact_phone', 'location_city', 'hospital_name', 'units_needed']
        widgets = {
            'patient_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Patient Name'}),
            'blood_group': forms.Select(attrs={'class': 'form-control'}),
            'contact_phone': forms.TextInput(attrs={'class': 'form-control'}),
            'location_city': forms.TextInput(attrs={'class': 'form-control'}),
            'hospital_name': forms.TextInput(attrs={'class': 'form-control'}),
            'units_needed': forms.NumberInput(attrs={'class': 'form-control'}),
        }

class GuestResponseForm(forms.ModelForm):
    class Meta:
        model = GuestResponse
        fields = ['donor_name', 'donor_phone']
        widgets = {
            'donor_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Your Name'}),
            'donor_phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Your Phone Number'}),
        }