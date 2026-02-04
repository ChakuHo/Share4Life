from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.db import transaction
from django.http import HttpResponseBadRequest
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from blood.eligibility import (
    is_eligible,
    next_eligible_datetime,
    last_verified_donation,
    ELIGIBILITY_DAYS,
)

from .forms import (
    RegistrationForm,
    FamilyMemberForm,
    UserBasicsForm,
    UserProfileForm,
    UserRoleForm,
)
from .kyc_forms import KYCProfileForm, KYCUploadForm
from .models import CustomUser, UserProfile, FamilyMember, KYCProfile, KYCDocument
from .tokens import make_email_token, read_email_token

from blood.models import PublicBloodRequest
from crowdfunding.models import Campaign, Donation
from django.db.models import Sum
from crowdfunding.models import Donation


User = get_user_model()

# hiding rejected requests from home page
all_requests = (
    PublicBloodRequest.objects
    .filter(is_active=True)
    .exclude(verification_status="REJECTED")
    .order_by("-is_emergency", "-created_at")
)

def send_verification_email_to_user(request, user) -> bool:
    if not user.email:
        return False

    token = make_email_token(user)
    link = request.build_absolute_uri(reverse("verify_email", args=[token]))

    send_mail(
        "Share4Life - Verify your email",
        f"Verify your Share4Life email:\n\n{link}\n\nIf you didn’t request this, ignore this email.",
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=False,
    )
    return True


def home(request):
    """
    Dynamic Landing Page (Blood + Crowdfunding)
    """
    all_requests = PublicBloodRequest.objects.filter(is_active=True).order_by("-is_emergency", "-created_at")
    context = {
        "urgent_requests": all_requests[:5],
        "recent_requests": all_requests[:4],
        "featured_campaign": Campaign.objects.filter(is_featured=True, status__in=["APPROVED", "COMPLETED"]).first(),
    }
    return render(request, "core/home.html", context)


@login_required
def dashboard(request):
    return render(request, "users/dashboard.html", {"user": request.user})


def register(request):
    if request.method == "POST":
        form = RegistrationForm(request.POST)

        if form.is_valid():
            cd = form.cleaned_data
            username = cd["username"]
            email = cd["email"]
            password = cd["password"]
            first_name = cd["first_name"]
            last_name = cd["last_name"]
            phone = cd["phone"]
            city = cd["city"]

            try:
                user = CustomUser.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    first_name=first_name,
                    last_name=last_name,
                    phone_number=phone,
                )

                #  profile + set city
                profile, _ = UserProfile.objects.get_or_create(user=user)
                profile.city = city
                profile.save(update_fields=["city"])

                # Ensure KYC exists (safe)
                KYCProfile.objects.get_or_create(user=user)

                # Send email verification (don’t block registration if email fails)
                try:
                    send_verification_email_to_user(request, user)
                    messages.info(request, "We sent a verification link to your email.")
                except Exception:
                    pass

                messages.success(request, "Account created successfully! Please login.")
                return redirect("login")

            except Exception as e:
                messages.error(request, f"System Error: {e}")

        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")

    else:
        form = RegistrationForm()

    return render(request, "accounts/register.html", {"form": form})


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
            # Block login if verification required
            if require_verified_email and not user.email_verified:
                show_resend_verification = True
                resend_email = user.email or ""

                # Auto-send verification email so user isn’t stuck
                try:
                    send_verification_email_to_user(request, user)
                except Exception:
                    pass

                error = "Email not verified. We sent a verification link to your email. Please verify and log in again."
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


def logout_view(request):
    logout(request)
    messages.info(request, "You have been logged out.")
    return redirect("login")


@login_required
def verify_email_prompt(request):
    return render(request, "accounts/verify_email_prompt.html", {
        "email_verified": bool(request.user.email_verified),
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

    messages.success(request, "Email verified successfully. You can log in now.")
    return redirect("login")


def resend_verification_email_public(request):
    next_url = request.GET.get("next") or request.POST.get("next") or "/accounts/login/"
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = "/accounts/login/"

    if request.method == "POST":
        # Support both field names to avoid “field empty” issues
        identifier = (request.POST.get("email") or request.POST.get("identifier") or "").strip()

        if identifier:
            user = (
                CustomUser.objects.filter(email__iexact=identifier).first()
                or CustomUser.objects.filter(username__iexact=identifier).first()
            )
            if user and (not user.email_verified) and user.email:
                try:
                    send_verification_email_to_user(request, user)
                except Exception:
                    pass

        messages.success(request, "If an account exists, a verification link has been sent.")
        return redirect(next_url)

    return render(request, "accounts/resend_verification_public.html", {"next": next_url})


def _points_level(points: int):
    levels = [
        (0, "New", "badge-secondary"),
        (100, "Bronze", "badge-warning"),
        (300, "Silver", "badge-info"),
        (700, "Gold", "badge-warning"),
        (1500, "Platinum", "badge-primary"),
    ]
    current = levels[0]
    next_level = None

    for i, (threshold, name, css) in enumerate(levels):
        if points >= threshold:
            current = (threshold, name, css)
            next_level = levels[i + 1] if i + 1 < len(levels) else None

    return current, next_level


def _profile_completion(profile):
    checks = {
        "blood_group": bool(profile.blood_group),
        "city": bool(profile.city),
        "date_of_birth": bool(profile.date_of_birth),
        "emergency_contact_name": bool(profile.emergency_contact_name),
        "emergency_contact_phone": bool(profile.emergency_contact_phone),
        "address_line": bool(profile.address_line),
        "country": bool(profile.country),
    }
    total = len(checks)
    done = sum(1 for v in checks.values() if v)
    percent = int((done / total) * 100) if total else 0
    missing = [k for k, v in checks.items() if not v]
    return percent, missing


@login_required
def profile_view(request):
    profile = request.user.profile
    kyc = getattr(request.user, "kyc", None)

    family_members = request.user.family_members.order_by("-id")
    emergency_family_count = family_members.filter(is_emergency_profile=True).count()

    points = int(getattr(profile, "points", 0) or 0)
    (cur_threshold, cur_level, cur_css), next_level = _points_level(points)

    if next_level:
        next_threshold, next_name, _ = next_level
        span = max(next_threshold - cur_threshold, 1)
        within = min(max(points - cur_threshold, 0), span)
        level_progress = int((within / span) * 100)
        points_to_next = max(next_threshold - points, 0)
    else:
        next_name = None
        level_progress = 100
        points_to_next = 0

    completion_percent, missing_fields = _profile_completion(profile)

    roles = []
    if request.user.is_donor:
        roles.append("Donor")
    if request.user.is_recipient:
        roles.append("Recipient")
    if request.user.is_hospital_admin:
        roles.append("Hospital Admin")
    if not roles:
        roles = ["User"]
    donor_eligibility = None
    if request.user.is_donor:
        last = last_verified_donation(request.user)
        nxt = next_eligible_datetime(request.user)
        eligible = is_eligible(request.user)

        days_remaining = 0
        progress_percent = 100
        if nxt:
            delta = nxt - timezone.now()
            days_remaining = max(delta.days, 0)
            progressed = max(ELIGIBILITY_DAYS - days_remaining, 0)
            progress_percent = int((progressed / ELIGIBILITY_DAYS) * 100) if ELIGIBILITY_DAYS else 100

        donor_eligibility = {
            "eligible": eligible,
            "last_donation": last.donated_at if last else None,
            "next_eligible": nxt,
            "days_remaining": days_remaining,
            "progress_percent": progress_percent,
            "eligibility_days": ELIGIBILITY_DAYS,
        }
    don_total = (
        Donation.objects
        .filter(donor_user=request.user, status="SUCCESS")
        .aggregate(s=Sum("amount"))["s"] or 0
    )
    don_count = Donation.objects.filter(donor_user=request.user, status="SUCCESS").count()
    don_campaigns = (
        Donation.objects
        .filter(donor_user=request.user, status="SUCCESS")
        .values("campaign_id").distinct().count()
    )

    crowdfunding_stats = {
        "total_amount": don_total,
        "count": don_count,
        "campaigns_supported": don_campaigns,
    }

    return render(request, "accounts/profile.html", {
        "profile": profile,
        "kyc": kyc,
        "family_members": family_members,
        "emergency_family_count": emergency_family_count,
        "roles": roles,
        "points": points,
        "cur_level": cur_level,
        "cur_level_css": cur_css,
        "next_level_name": next_name,
        "level_progress": level_progress,
        "points_to_next": points_to_next,
        "completion_percent": completion_percent,
        "missing_fields": missing_fields,
        "donor_eligibility": donor_eligibility,
        "crowdfunding_stats": crowdfunding_stats,
    })


@login_required
def profile_edit(request):
    profile = request.user.profile

    if request.method == "POST":
        basics_form = UserBasicsForm(request.POST, request.FILES, instance=request.user)
        role_form = UserRoleForm(request.POST, instance=request.user)
        profile_form = UserProfileForm(request.POST, instance=profile)

        if basics_form.is_valid() and role_form.is_valid() and profile_form.is_valid():
            basics_form.save()
            role_form.save()
            profile_form.save()
            messages.success(request, "Profile updated successfully.")
            return redirect("profile")

        messages.error(request, "Please fix the errors and try again.")
    else:
        basics_form = UserBasicsForm(instance=request.user)
        role_form = UserRoleForm(instance=request.user)
        profile_form = UserProfileForm(instance=profile)

    return render(request, "accounts/profile_edit.html", {
        "basics_form": basics_form,
        "role_form": role_form,
        "profile_form": profile_form,
    })


@login_required
def family_add(request):
    if request.method == "POST":
        form = FamilyMemberForm(request.POST)
        if form.is_valid():
            fm = form.save(commit=False)
            fm.primary_user = request.user
            fm.save()
            messages.success(request, "Family member added successfully.")
            return redirect("profile")
        messages.error(request, "Please fix the errors and try again.")
    else:
        form = FamilyMemberForm()

    return render(request, "accounts/family_add.html", {"form": form})


@login_required
@transaction.atomic
def kyc_submit(request):
    kyc, _ = KYCProfile.objects.get_or_create(user=request.user)

    if request.method == "POST":
        profile_form = KYCProfileForm(request.POST, instance=kyc)
        upload_form = KYCUploadForm(request.POST, request.FILES)

        if profile_form.is_valid() and upload_form.is_valid():
            profile_form.save()

            def save_doc(doc_type, f):
                if not f:
                    return
                KYCDocument.objects.update_or_create(
                    kyc=kyc,
                    doc_type=doc_type,
                    defaults={"file": f},
                )

            save_doc("ID_FRONT", upload_form.cleaned_data["id_front"])
            save_doc("ID_BACK", upload_form.cleaned_data.get("id_back"))
            save_doc("SELFIE", upload_form.cleaned_data["selfie"])
            save_doc("ADDRESS_PROOF", upload_form.cleaned_data.get("address_proof"))

            kyc.mark_submitted()
            messages.success(request, "KYC submitted successfully. Pending admin review.")
            return redirect("profile")

        messages.error(request, "Please fix the errors and try again.")
    else:
        profile_form = KYCProfileForm(instance=kyc)
        upload_form = KYCUploadForm()

    return render(request, "accounts/kyc_submit.html", {
        "kyc": kyc,
        "profile_form": profile_form,
        "upload_form": upload_form,
    })