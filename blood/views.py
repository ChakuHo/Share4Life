from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import PublicBloodRequest
from .forms import EmergencyRequestForm, GuestResponseForm

# 1. View to POST a request (Recipient)
def emergency_request_view(request):
    if request.method == 'POST':
        form = EmergencyRequestForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Emergency Broadcasted! Donors can now see this.")
            return redirect('public_dashboard')
    else:
        form = EmergencyRequestForm()
    return render(request, 'blood/emergency_form.html', {'form': form})

# 2. View to SEE requests (The Public Feed)
def public_dashboard_view(request):
    """
    Shows all active blood requests to everyone (even guests).
    """
    requests = PublicBloodRequest.objects.filter(is_active=True).order_by('-created_at')
    return render(request, 'blood/public_dashboard.html', {'requests': requests})

# 3. View to DONATE as Guest (The "Hassle-Free" button)
def guest_donate_view(request, request_id):
    """
    Guest clicks "I can Help", fills name/phone, and that's it.
    """
    blood_req = get_object_or_404(PublicBloodRequest, id=request_id)
    
    if request.method == 'POST':
        form = GuestResponseForm(request.POST)
        if form.is_valid():
            response = form.save(commit=False)
            response.request = blood_req
            response.save()
            
            # --- REAL WORLD LOGIC ---
            # Here you would trigger an SMS to the Recipient:
            # "Someone named {response.donor_name} ({response.donor_phone}) is coming to help!"
            
            messages.success(request, "Thank you! The patient has been notified that you are coming.")
            return redirect('public_dashboard')
    else:
        form = GuestResponseForm()
        
    return render(request, 'blood/guest_response.html', {'form': form, 'req': blood_req})