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
from datetime import timedelta
from django.utils.http import url_has_allowed_host_and_scheme
from blood.eligibility import (
    is_eligible,
    next_eligible_datetime,
    last_verified_donation,
    ELIGIBILITY_DAYS,
)
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator
from django.db.models import Max
from blood.matching import city_aliases
import io
from django.http import HttpResponse
from django.db.models import Sum
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from django.shortcuts import redirect
from accounts.models import UserProfile
from core.models import SiteSetting

from blood.models import BloodDonation
from organ.models import OrganPledge

from .forms import (
    RegistrationForm,
    FamilyMemberForm,
    UserBasicsForm,
    UserProfileForm,
    UserRoleForm,
)

from django.db.models import Q
from django.core.exceptions import FieldError
from .kyc_forms import KYCProfileForm, KYCUploadForm
from .models import CustomUser, UserProfile, FamilyMember, KYCProfile, KYCDocument
from .tokens import make_email_token, read_email_token

from blood.models import PublicBloodRequest
from crowdfunding.models import Campaign, Donation



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
    Dynamic Landing Page (Blood + Crowdfunding) + Home Popup (session-only)

    Popup behavior (JS sessionStorage):
      - Not shown again on refresh
      - Shown again if tab/browser is closed

    Popup priority:
      1) Crowdfunding (APPROVED + not expired)
      2) Blood campaign (if BloodCampaign model exists and has recognizable status fields)
    """
    all_requests = (
        PublicBloodRequest.objects
        .filter(is_active=True)
        .order_by("-is_emergency", "-created_at")
    )

    featured_campaign = Campaign.objects.filter(
        is_featured=True,
        status__in=["APPROVED", "COMPLETED"]
    ).first()

    home_popup = None
    today = timezone.localdate()

    # ---------- 1) Crowdfunding popup ----------
    ongoing_cf = (
        Campaign.objects
        .filter(status="APPROVED")
        .filter(Q(deadline__isnull=True) | Q(deadline__gte=today))
        .order_by("-is_featured", "-created_at")
        .first()
    )

    if ongoing_cf:
        # Use raised_total() for accurate amount 
        raised = ongoing_cf.raised_total()
        target = ongoing_cf.target_amount
        pct = ongoing_cf.get_percentage()

        home_popup = {
            "kind": "crowdfunding",
            "id": ongoing_cf.id,
            "title": ongoing_cf.title,
            "subtitle": f"Help {ongoing_cf.patient_name} — verified medical fundraising is ongoing.",
            "image_url": ongoing_cf.image.url if ongoing_cf.image else "",
            "cta_text": "Donate Now",
            "cta_url": reverse("campaign_detail", args=[ongoing_cf.id]),
            "pct": pct,
            "raised": raised,
            "target": target,
            "deadline": ongoing_cf.deadline.strftime("%Y-%m-%d") if ongoing_cf.deadline else "",
        }

    # ---------- 2) Blood campaign popup fallback ----------
    if not home_popup:
        BloodCampaign = None
        try:
            from hospitals.models import BloodCampaign as BloodCampaign  # if your command is in hospitals
        except Exception:
            try:
                from blood.models import BloodCampaign as BloodCampaign  # if you put it in blood
            except Exception:
                BloodCampaign = None

        if BloodCampaign:
            def safe_first(filters: dict, order_by: str):
                try:
                    return BloodCampaign.objects.filter(**filters).order_by(order_by).first()
                except (FieldError, Exception):
                    return None

            # Try common statuses without breaking if field differs
            bc = (
                safe_first({"status": "ONGOING"}, "-id")
                or safe_first({"status": "ACTIVE"}, "-id")
                or safe_first({"is_active": True}, "-id")
            )

            if bc:
                title = getattr(bc, "title", None) or getattr(bc, "name", None) or "Blood Donation Camp"
                city = getattr(bc, "city", None) or getattr(bc, "location_city", None) or ""
                image_url = ""
                try:
                    if getattr(bc, "image", None):
                        image_url = bc.image.url
                except Exception:
                    image_url = ""

                home_popup = {
                    "kind": "blood_campaign",
                    "id": bc.id,
                    "title": title,
                    "subtitle": f"Blood donation camp is active{(' in ' + city) if city else ''}.",
                    "image_url": image_url,
                    "cta_text": "View Camps",
                    "cta_url": reverse("blood_campaigns"),
                    "pct": 0,
                    "raised": "",
                    "target": "",
                    "deadline": "",
                }

    context = {
        "urgent_requests": all_requests[:5],
        "recent_requests": all_requests[:4],
        "featured_campaign": featured_campaign,
        "home_popup": home_popup, 
    }
    return render(request, "core/home.html", context)

def public_donor_directory(request):
    """
    Public Donor Directory (No login required)
    Rules:
      - Only KYC verified donors
      - Only ELIGIBLE donors (90-day rule)
      - No phone number, no exact location (city only)
    Filters:
      - blood_group
      - city (with aliases/normalization)
      - search (username/first/last)
    """
    # --- Filters ---
    blood_group = (request.GET.get("blood_group") or "").strip().upper()
    city = (request.GET.get("city") or "").strip()
    q = (request.GET.get("q") or "").strip()
    page = request.GET.get("page") or "1"

    # --- Eligibility cutoff ---
    cutoff = timezone.now() - timedelta(days=ELIGIBILITY_DAYS)

    # --- Base queryset: KYC verified + donors + active ---
    qs = (
        CustomUser.objects
        .filter(is_active=True, is_donor=True)
        .select_related("profile", "kyc")
        .filter(Q(is_verified=True) | Q(kyc__status="APPROVED"))
        .annotate(
            last_verified_donation_at=Max(
                "blood_donations__donated_at",
                filter=Q(blood_donations__status="VERIFIED"),
            )
        )
        # eligible only: never donated OR last verified donation <= cutoff
        .filter(Q(last_verified_donation_at__isnull=True) | Q(last_verified_donation_at__lte=cutoff))
        # require donor has blood group and city set for directory usefulness
        .exclude(profile__blood_group="")
        .exclude(profile__city="")
    )

    # --- Blood group filter ---
    allowed_groups = {bg for bg, _ in UserProfile.BLOOD_GROUPS}
    if blood_group:
        if blood_group in allowed_groups:
            qs = qs.filter(profile__blood_group=blood_group)
        else:
            messages.error(request, "Invalid blood group filter.")
            return redirect("public_donor_directory")

    # --- City filter (aliases) ---
    if city:
        aliases = city_aliases(city)
        city_q = Q()
        for a in aliases:
            city_q |= Q(profile__city__iexact=a)
        qs = qs.filter(city_q)

    # --- Search filter ---
    if q:
        qs = qs.filter(
            Q(username__icontains=q) |
            Q(first_name__icontains=q) |
            Q(last_name__icontains=q)
        )

    # --- Ordering: highest points first (gamification), then newest users ---
    qs = qs.order_by("-profile__points", "-date_joined")

    # --- Pagination ---
    paginator = Paginator(qs, 24)  # 24 donors per page
    page_obj = paginator.get_page(page)

    return render(request, "accounts/public_donor_directory.html", {
        "page_obj": page_obj,
        "blood_groups": UserProfile.BLOOD_GROUPS,
        "selected_blood_group": blood_group,
        "selected_city": city,
        "q": q,
        "eligibility_days": ELIGIBILITY_DAYS,
    })


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

    # Crowdfunding stats 
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

    # Social Impact stats
    blood_verified_qs = BloodDonation.objects.filter(donor_user=request.user, status="VERIFIED")
    blood_verified_count = blood_verified_qs.count()
    blood_verified_units = blood_verified_qs.aggregate(s=Sum("units"))["s"] or 0

    organ_verified_count = OrganPledge.objects.filter(donor=request.user, status="VERIFIED").count()

    impact_stats = {
        "blood_verified_count": blood_verified_count,
        "blood_verified_units": blood_verified_units,
        "organ_verified_count": organ_verified_count,
        "crowdfunding_total": don_total,
        "points": points,
        "level": cur_level,
    }

    # Certificate rule (we can change this later to our pref but for now we are going with this simple logic to allow certificate download if user is KYC verified or has at least 1 verified blood donation):
    # Allow certificate if KYC verified OR has at least 1 verified blood donation
    can_download_certificate = bool(request.user.is_verified or blood_verified_count > 0 or organ_verified_count > 0)

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
        "impact_stats": impact_stats,
        "can_download_certificate": can_download_certificate,
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
def family_edit(request, pk):
    fm = get_object_or_404(FamilyMember, pk=pk, primary_user=request.user)

    if request.method == "POST":
        form = FamilyMemberForm(request.POST, instance=fm)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.primary_user = request.user  # safety
            obj.save()
            messages.success(request, "Family member updated successfully.")
            return redirect("profile")
        messages.error(request, "Please fix the errors and try again.")
    else:
        form = FamilyMemberForm(instance=fm)

    return render(request, "accounts/family_edit.html", {
        "form": form,
        "fm": fm,
    })

@require_POST
@login_required
def family_delete(request, pk):
    fm = get_object_or_404(FamilyMember, pk=pk, primary_user=request.user)
    name = fm.name
    fm.delete()
    messages.success(request, f"Family member '{name}' deleted.")
    return redirect("profile")

@login_required
def emergency_profiles_list(request):
    """
    Lists only FamilyMember entries marked as is_emergency_profile=True
    for the logged-in user.

    Includes:
      - search by name/relationship/city
      - actions: Edit / Delete
      - one-click Request Blood (only if user is recipient + blood_group + city exist)
    """
    qtxt = (request.GET.get("q") or "").strip()

    qs = FamilyMember.objects.filter(primary_user=request.user, is_emergency_profile=True).order_by("-id")

    if qtxt:
        qs = qs.filter(
            Q(name__icontains=qtxt) |
            Q(relationship__icontains=qtxt) |
            Q(city__icontains=qtxt)
        )

    return render(request, "accounts/emergency_profiles_list.html", {
        "items": qs[:200],
        "q": qtxt,
    })


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


@login_required
def download_certificate_pdf(request):
    """
    Generates a PDF certificate with Share4Life logo and verification details.

    Unlock rule (includes organ):
      - KYC verified OR
      - at least 1 VERIFIED blood donation OR
      - at least 1 VERIFIED organ pledge
    """

    # ---------- helpers ----------
    def fmt_dt(dt):
        if not dt:
            return "—"
        try:
            return timezone.localtime(dt).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return dt.strftime("%Y-%m-%d %H:%M")

    def title_case_name(s: str) -> str:
        s = (s or "").strip()
        if not s:
            return ""
        return " ".join([w[:1].upper() + w[1:].lower() for w in s.split()])

    def display_admin(u):
        # "Share4Life Admin (Name)" style
        if not u:
            return "Share4Life Admin"
        full = title_case_name((u.get_full_name() or "").strip())
        if full:
            return f"Share4Life Admin ({full})"
        username = getattr(u, "username", "") or ""
        return f"Share4Life Admin ({username})" if username else "Share4Life Admin"

    def display_person(u):
        if not u:
            return "—"
        if getattr(u, "is_superuser", False) or getattr(u, "is_staff", False):
            return display_admin(u)
        full = title_case_name((u.get_full_name() or "").strip())
        if full:
            return full
        return getattr(u, "username", "—") or "—"

    def get_logo_reader():
        """
        Load SiteSetting.site_logo safely (works with local disk and remote storage).
        """
        try:
            ss = SiteSetting.objects.filter(pk=1).first()
            if not ss or not ss.site_logo:
                return None

            ss.site_logo.open("rb")
            data = ss.site_logo.read()
            ss.site_logo.close()

            if not data:
                return None

            return ImageReader(io.BytesIO(data))
        except Exception:
            return None

    def draw_contain_image_in_box(c, img_reader, box_x, box_y, box_w, box_h, inner_pad=6):
        """
        Fit image inside box (NO zoom/crop). Keeps aspect ratio, centered.
        """
        if not img_reader:
            return
        try:
            iw, ih = img_reader.getSize()
            if not iw or not ih:
                return

            max_w = max(box_w - 2 * inner_pad, 1)
            max_h = max(box_h - 2 * inner_pad, 1)

            scale = min(max_w / float(iw), max_h / float(ih))
            dw = iw * scale
            dh = ih * scale

            img_x = box_x + (box_w - dw) / 2
            img_y = box_y + (box_h - dh) / 2
            c.drawImage(img_reader, img_x, img_y, width=dw, height=dh, mask="auto")
        except Exception:
            pass

    def draw_section_box(
        c, title, lines, top_y, *,
        box_h=140, fill_color=None,
        left_pad=16, top_pad=16,
        title_gap=26, line_gap=17
    ):
        """
        Draw a section box with proper internal padding so headings/text never touch borders.
        Returns bottom y of the box.
        """
        box_w = w - 2 * margin
        box_x = margin
        box_y = top_y - box_h

        c.setStrokeColor(light_border)
        c.setFillColor(fill_color if fill_color is not None else white)
        c.rect(box_x, box_y, box_w, box_h, stroke=1, fill=1)

        title_y = top_y - top_pad
        c.setFillColor(navy)
        c.setFont("Helvetica-Bold", 14)
        c.drawString(box_x + left_pad, title_y, title)

        yy = title_y - title_gap
        c.setFillColor(dark)
        c.setFont("Helvetica", 12)
        for line in lines:
            c.drawString(box_x + left_pad, yy, line)
            yy -= line_gap

        return box_y

    # ---------------- Eligibility checking ----------------
    blood_verified_qs = BloodDonation.objects.filter(donor_user=request.user, status="VERIFIED")
    blood_verified_count = blood_verified_qs.count()

    organ_verified_qs = OrganPledge.objects.filter(donor=request.user, status="VERIFIED")
    organ_verified_count = organ_verified_qs.count()

    if not (request.user.is_verified or blood_verified_count > 0 or organ_verified_count > 0):
        messages.error(
            request,
            "Certificate unlocks after KYC verification or at least 1 verified blood donation / organ pledge."
        )
        return redirect("profile")

    # ---------------- Stats ----------------
    blood_verified_units = blood_verified_qs.aggregate(s=Sum("units"))["s"] or 0
    cf_total = (
        Donation.objects
        .filter(donor_user=request.user, status="SUCCESS")
        .aggregate(s=Sum("amount"))["s"] or 0
    )

    try:
        profile_points = int(
            UserProfile.objects.filter(user=request.user).values_list("points", flat=True).first() or 0
        )
    except Exception:
        profile_points = int(getattr(getattr(request.user, "profile", None), "points", 0) or 0)

    # ---------------- Verification details ----------------
    kyc = getattr(request.user, "kyc", None)
    kyc_is_approved = bool(kyc and getattr(kyc, "status", "") == "APPROVED")
    kyc_verified_for_pdf = bool(request.user.is_verified or kyc_is_approved)

    kyc_reviewer = display_person(getattr(kyc, "reviewed_by", None)) if kyc_is_approved else "—"
    kyc_reviewed_at = fmt_dt(getattr(kyc, "reviewed_at", None)) if kyc_is_approved else "—"

    last_blood = blood_verified_qs.order_by("-verified_at").select_related("verified_by", "verified_by_org").first()
    blood_verified_by = display_person(getattr(last_blood, "verified_by", None)) if last_blood else "—"
    blood_verified_org = (getattr(getattr(last_blood, "verified_by_org", None), "name", "") or "—") if last_blood else "—"
    blood_verified_at = fmt_dt(getattr(last_blood, "verified_at", None)) if last_blood else "—"

    last_pledge = organ_verified_qs.order_by("-verified_at").select_related("verified_by", "verified_by_org").first()
    organ_verified_by = display_person(getattr(last_pledge, "verified_by", None)) if last_pledge else "—"
    organ_verified_org = (getattr(getattr(last_pledge, "verified_by_org", None), "name", "") or "—") if last_pledge else "—"
    organ_verified_at = fmt_dt(getattr(last_pledge, "verified_at", None)) if last_pledge else "—"

    # ---------------- Certificate meta ----------------
    base_name = (request.user.get_full_name() or request.user.username).strip()
    full_name = title_case_name(base_name) or request.user.username
    issued_date = timezone.localdate().strftime("%Y-%m-%d")
    cert_id = f"S4L-{request.user.id:06d}-{timezone.localdate().strftime('%Y%m%d')}"

    roles = []
    if request.user.is_donor:
        roles.append("Donor")
    if request.user.is_recipient:
        roles.append("Recipient")
    if request.user.is_hospital_admin:
        roles.append("Hospital Admin")
    if not roles:
        roles = ["User"]

    # ---------------- PDF response ----------------
    filename = f"Share4Life_Certificate_{request.user.username}.pdf"
    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    c = canvas.Canvas(response, pagesize=A4)
    w, h = A4

    # Theme colors
    navy = HexColor("#0a2558")
    red = HexColor("#e63946")
    white = HexColor("#ffffff")
    dark = HexColor("#333333")
    light_border = HexColor("#e6eaf2")
    light_bg = HexColor("#f8f9fa")

    margin = 36

    # Outer frame
    c.setStrokeColor(light_border)
    c.setLineWidth(1)
    c.rect(margin - 12, margin - 12, w - 2 * (margin - 12), h - 2 * (margin - 12), stroke=1, fill=0)

    # ---------------- Header band  ----------------
    header_y = h - 128
    header_h = 98

    band_left = margin - 12
    band_width = w - 2 * (margin - 12)
    band_right = band_left + band_width

    c.setFillColor(navy)
    c.rect(band_left, header_y, band_width, header_h, stroke=0, fill=1)

    # inner padding INSIDE blue header (left/right/top/bottom)
    inner_pad_x = 22
    inner_pad_y = 12
    inner_left = band_left + inner_pad_x
    inner_right = band_right - inner_pad_x

    # Logo box 
    logo_reader = get_logo_reader()
    box_w = 190
    box_h = header_h - 2 * inner_pad_y
    box_x = inner_left
    box_y = header_y + inner_pad_y

    if logo_reader:
        c.setFillColor(white)
        c.rect(box_x, box_y, box_w, box_h, stroke=0, fill=1)
        draw_contain_image_in_box(c, logo_reader, box_x, box_y, box_w, box_h, inner_pad=6)

    # Title with right padding + auto shrink so it never touches the right edge
    title_text = "Share4Life Certificate"
    title_x = box_x + box_w + 26
    title_y = header_y + (header_h / 2) + 8
    max_title_w = max(inner_right - title_x, 60)

    font_size = 22
    while font_size >= 14:
        c.setFont("Helvetica-Bold", font_size)
        if c.stringWidth(title_text, "Helvetica-Bold", font_size) <= max_title_w:
            break
        font_size -= 1

    title_y = header_y + (header_h * 0.58)
    subtitle_y = header_y + (header_h * 0.35)
    title_font = 26
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", title_font)
    c.drawString(title_x, title_y, title_text)

    c.setFillColor(white)
    c.drawString(title_x, title_y, title_text)

    c.setFont("Helvetica", 12)
    c.setFillColor(HexColor("#dbe5ff"))
    c.drawString(title_x, subtitle_y, "Certificate of Appreciation")

    # ---------------- Meta row ----------------
    y = header_y - 28
    c.setFillColor(navy)
    c.setFont("Helvetica", 11)
    c.drawString(margin, y, f"Certificate ID: {cert_id}")
    c.drawRightString(w - margin, y, f"Issued on: {issued_date}")

    # Awarded to
    y -= 45
    c.setFont("Helvetica-Bold", 15)
    c.drawString(margin, y, "Awarded to:")
    y -= 30
    c.setFont("Helvetica-Bold", 24)
    c.setFillColor(red)
    c.drawString(margin, y, full_name)

    # Roles + KYC
    y -= 34
    c.setFillColor(navy)
    c.setFont("Helvetica", 12)
    c.drawString(margin, y, f"Role(s): {', '.join(roles)}")
    y -= 18
    c.drawString(margin, y, f"KYC Verified: {'YES' if kyc_verified_for_pdf else 'NO'}")

    # ---------------- Social Impact Summary ----------------
    y -= 46
    impact_lines = [
        f"Verified Blood Donations: {blood_verified_count}",
        f"Verified Blood Units: {blood_verified_units}",
        f"Verified Organ Pledges: {organ_verified_count}",
        f"Crowdfunding Contributions (Successful): Rs. {cf_total}",
        f"Profile Points: {profile_points}",
    ]
    bottom_y = draw_section_box(
        c, "Social Impact Summary", impact_lines, y,
        box_h=145, fill_color=light_bg
    )

    # ---------------- Verification Details ----------------
    y = bottom_y - 64
    ver_lines = [
        f"KYC reviewed by: {kyc_reviewer}   at: {kyc_reviewed_at}",
        f"Last blood verification: {blood_verified_org} / {blood_verified_by} at {blood_verified_at}",
        f"Last organ pledge verification: {organ_verified_org} / {organ_verified_by} at {organ_verified_at}",
    ]
    draw_section_box(
        c, "Verification Details", ver_lines, y,
        box_h=145, fill_color=white
    )

    # Footer note
    c.setFont("Helvetica-Oblique", 9)
    c.setFillColor(dark)
    c.drawString(margin, 62, "This certificate is generated digitally by Share4Life based on verified platform records.")
    c.drawString(margin, 48, "For confirmation, match Certificate ID and verification details with admin records.")

    c.showPage()
    c.save()
    return response