from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from .forms import RegistrationForm
from .models import CustomUser

from blood.models import PublicBloodRequest
from crowdfunding.models import Campaign

def home(request):
    """
    The Dynamic Landing Page.
    Fetches data from Blood and Crowdfunding apps.
    """
    context = {}

    # 1. Fetch Blood Requests
    # Get all active requests sorted by newest first
    all_requests = PublicBloodRequest.objects.filter(is_active=True).order_by('-created_at')
    
    context['urgent_requests'] = all_requests[:5]  # Pass top 5 to the Ticker
    context['recent_requests'] = all_requests[:4]  # Pass top 4 to the Cards Grid

    # 2. Fetch Featured Campaign
    # Get the first campaign marked as featured
    context['featured_campaign'] = Campaign.objects.filter(is_featured=True).first()
    
    return render(request, 'home.html', context)

@login_required
def dashboard(request):
    return render(request, 'users/dashboard.html', {'user': request.user})

def register(request):
    if request.method == 'POST':
        form = RegistrationForm(request.POST)
        
        if form.is_valid():
            username = form.cleaned_data['username']
            email = form.cleaned_data['email']
            password = form.cleaned_data['password']
            first_name = form.cleaned_data['first_name']
            last_name = form.cleaned_data['last_name']
            phone = form.cleaned_data['phone']
            city = form.cleaned_data['city']

            try:
                # Create the User (Handles password hashing)
                user = CustomUser.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    first_name=first_name,
                    last_name=last_name,
                    phone_number=phone
                )
                
                # Update the Profile (Created automatically by signal)
                user.profile.city = city
                user.profile.save()

                messages.success(request, "Account created successfully! Please login.")
                return redirect('login')
            
            except Exception as e:
                messages.error(request, f"System Error: {e}")
        else:
            # Show form errors
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")
                    
    else:
        form = RegistrationForm()

    return render(request, 'accounts/register.html', {'form': form})

def login_view(request):
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            messages.success(request, f"Welcome back, {user.first_name}!")
            return redirect('home')
        else:
            messages.error(request, "Invalid username or password")
    
    return render(request, 'accounts/login.html')

def logout_view(request):
    logout(request)
    messages.info(request, "You have been logged out.")
    return redirect('login')