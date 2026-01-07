from urllib import request
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from .forms import RegistrationForm
from .models import CustomUser

from blood.models import PublicBloodRequest
from crowdfunding.models import Campaign

from django.conf import settings
from django.core.mail import send_mail
from django.http import HttpResponseBadRequest
from django.urls import reverse

from .tokens import make_email_token, read_email_token
from django.utils.http import url_has_allowed_host_and_scheme
from django.contrib.auth import get_user_model
User = get_user_model()

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
    
    return render(request, 'core/home.html', context)

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
                try:
                    send_verification_email_to_user(request, user)
                    messages.info(request, "We sent a verification link to your email.")
                except Exception:
                    pass
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
        return redirect("home")

    error = None
    identifier_value = ""
    show_resend_verification = False
    resend_email = ""
    require_verified_email = getattr(settings, "EMAIL_VERIFICATION_REQUIRED", True)

    if request.method == "POST":
        identifier = (request.POST.get("username") or "").strip()
        password = request.POST.get("password") or ""
        identifier_value = identifier

        user = authenticate(request, username=identifier, password=password)

        # Allow login via email too
        if user is None and identifier:
            try:
                u = CustomUser.objects.get(email__iexact=identifier)
                user = authenticate(request, username=u.username, password=password)
            except CustomUser.DoesNotExist:
                user = None

        if user is not None:
            # If verification required and user not verified -> do NOT log them in
            if require_verified_email and hasattr(user, "email_verified") and not user.email_verified:
                error = "Your email is not verified. Please verify your email to log in."
                show_resend_verification = True
                resend_email = user.email or ""
                messages.warning(request, error)

                return render(request, "accounts/login.html", {
                    "error": error,
                    "identifier_value": identifier_value,
                    "show_resend_verification": show_resend_verification,
                    "resend_email": resend_email,
                })

            # Normal login
            login(request, user)

            remember = request.POST.get("remember_me") == "on"
            request.session.set_expiry(60 * 60 * 24 * 14 if remember else 0)

            # If verification NOT required, just warn but allow login
            if (not require_verified_email) and hasattr(user, "email_verified") and not user.email_verified:
                messages.warning(request, "Your email is not verified. Please verify to unlock full access.")

            messages.success(request, f"Welcome back, {user.first_name}!")
            return redirect("home")

        error = "Invalid username/email or password"
        messages.error(request, error)

    return render(request, "accounts/login.html", {
        "error": error,
        "identifier_value": identifier_value,
        "show_resend_verification": show_resend_verification,
        "resend_email": resend_email,
    })

def send_verification_email_to_user(request, user):

    if not user.email:
        return False

    token = make_email_token(user)
    link = request.build_absolute_uri(reverse("verify_email", args=[token]))

    subject = "Share4Life - Verify your email"
    body = (
        f"Verify your Share4Life email by clicking the link below:\n\n"
        f"{link}\n\n"
        f"If you didn’t request this, ignore this email."
    )

    send_mail(
        subject,
        body,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=False,
    )
    return True


@login_required
def verify_email_prompt(request):
    return render(request, "accounts/verify_email_prompt.html", {
        "email_verified": bool(getattr(request.user, "email_verified", False)),
    })


@login_required
def send_verification_email(request):
    if request.user.email_verified:
        messages.info(request, "Your email is already verified.")
        return redirect("verify_email_prompt")

    ok = send_verification_email_to_user(request, request.user)
    if ok:
        messages.success(request, "Verification link sent to your email.")
    else:
        messages.error(request, "No email found on your account.")
    return redirect("verify_email_prompt")


def verify_email(request, token: str):
    try:
        data = read_email_token(token)
    except Exception:
        return HttpResponseBadRequest("Invalid or expired verification link.")

    uid = data.get("uid")
    email = (data.get("email") or "").strip().lower()

    try:
        user = User.objects.get(pk=uid)
    except User.DoesNotExist:
        return HttpResponseBadRequest("Invalid verification link.")

    if not user.email or user.email.strip().lower() != email:
        return HttpResponseBadRequest("Invalid verification link.")

    user.email_verified = True
    user.save(update_fields=["email_verified"])

    messages.success(request, "Email verified successfully. You can continue using Share4Life.")
    return redirect("login")


def resend_verification_email_public(request):
    # where to go after sending
    next_url = request.GET.get("next") or request.POST.get("next") or "/accounts/login/"

    # prevent open redirects
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = "/accounts/login/"

    if request.method == "POST":
        email = (request.POST.get("email") or "").strip().lower()

        if email:
            try:
                user = CustomUser.objects.get(email__iexact=email)

                if hasattr(user, "email_verified") and not user.email_verified and user.email:
                    # send verification link
                    token = make_email_token(user)
                    link = request.build_absolute_uri(reverse("verify_email", args=[token]))

                    send_mail(
                        "Share4Life - Verify your email",
                        f"Verify your email:\n\n{link}\n\nIf you didn’t request this, ignore this email.",
                        settings.DEFAULT_FROM_EMAIL,
                        [user.email],
                        fail_silently=False,
                    )
            except CustomUser.DoesNotExist:
                pass

        # generic success message (prevents email enumeration)
        messages.success(request, "If an account exists with that email, a verification link has been sent.")
        return redirect(next_url)

    return render(request, "accounts/resend_verification_public.html", {"next": next_url})

def logout_view(request):
    logout(request)
    messages.info(request, "You have been logged out.")
    return redirect('login')