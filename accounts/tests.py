import shutil
import tempfile
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.forms import RegistrationForm
from accounts.models import UserProfile, KYCProfile, FamilyMember
from accounts.tokens import make_email_token
from blood.models import BloodDonation

User = get_user_model()


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_VERIFICATION_REQUIRED=True,
)
class AccountsTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._temp_media = tempfile.mkdtemp()
        cls._media_override = override_settings(MEDIA_ROOT=cls._temp_media)
        cls._media_override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._media_override.disable()
        shutil.rmtree(cls._temp_media, ignore_errors=True)
        super().tearDownClass()

    def create_user(self, **kwargs):
        data = {
            "username": kwargs.pop("username", "user1"),
            "email": kwargs.pop("email", "user1@example.com"),
            "password": kwargs.pop("password", "TestPass123!"),
            "first_name": kwargs.pop("first_name", "Test"),
            "last_name": kwargs.pop("last_name", "User"),
            "is_donor": kwargs.pop("is_donor", False),
            "is_recipient": kwargs.pop("is_recipient", False),
            "is_verified": kwargs.pop("is_verified", False),
            "email_verified": kwargs.pop("email_verified", True),
        }
        password = data.pop("password")
        user = User.objects.create_user(password=password, **data, **kwargs)
        return user, password

    def build_registration_payload(self, **overrides):
        """
        Build payload dynamically based on the actual RegistrationForm fields.
        This makes the test survive if your form uses confirm_password,
        password1/password2, terms checkbox, role fields, etc.
        """
        password = overrides.pop("password", "StrongPass123!")

        data = {
            "username": "newuser",
            "email": "newuser@example.com",
            "password": password,
            "first_name": "New",
            "last_name": "User",
            "phone": "9800000000",
            "city": "Kathmandu",
        }

        form_fields = set(RegistrationForm().fields.keys())

        # common password confirmation names
        confirm_names = [
            "confirm_password",
            "password_confirm",
            "password_confirmation",
            "password1",
            "password2",
        ]
        for name in confirm_names:
            if name in form_fields:
                data[name] = password

        # common checkbox / agreement names
        true_fields = [
            "terms",
            "agree_terms",
            "accept_terms",
            "accept_privacy",
            "privacy_policy",
        ]
        for name in true_fields:
            if name in form_fields:
                data[name] = True

        # common role fields
        if "is_donor" in form_fields:
            data["is_donor"] = True
        if "is_recipient" in form_fields:
            data["is_recipient"] = True

        # allow explicit overrides last
        data.update(overrides)
        return data

    def test_user_signal_creates_profile_and_kyc(self):
        user, _ = self.create_user(username="signaluser", email="signal@example.com")
        self.assertTrue(UserProfile.objects.filter(user=user).exists())
        self.assertTrue(KYCProfile.objects.filter(user=user).exists())

    @patch("accounts.views.send_verification_email_to_user", return_value=True)
    def test_register_creates_user_profile_and_kyc(self, _mock_send):
        payload = self.build_registration_payload(
            username="newuser",
            email="newuser@example.com",
        )

        response = self.client.post(reverse("register"), payload)

        error_msg = ""
        if response.status_code != 302 and getattr(response, "context", None):
            form = response.context.get("form")
            if form is not None:
                error_msg = form.errors.as_json()

        self.assertEqual(response.status_code, 302, msg=error_msg)
        self.assertTrue(User.objects.filter(username="newuser").exists())

        user = User.objects.get(username="newuser")
        self.assertTrue(UserProfile.objects.filter(user=user).exists())
        self.assertTrue(KYCProfile.objects.filter(user=user).exists())
        self.assertEqual(user.profile.city, "Kathmandu")

    def test_login_blocked_for_unverified_email(self):
        user, password = self.create_user(
            username="unverified",
            email="unverified@example.com",
            email_verified=False,
        )

        response = self.client.post(reverse("login"), {
            "username": user.username,
            "password": password,
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Email not verified")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_verify_email_marks_user_as_verified(self):
        user, _ = self.create_user(
            username="verifyme",
            email="verifyme@example.com",
            email_verified=False,
        )
        token = make_email_token(user)

        response = self.client.get(reverse("verify_email", args=[token]))
        self.assertEqual(response.status_code, 302)

        user.refresh_from_db()
        self.assertTrue(user.email_verified)

    def test_family_member_add(self):
        user, password = self.create_user(
            username="familyuser",
            email="family@example.com",
            email_verified=True,
        )
        self.client.login(username=user.username, password=password)

        response = self.client.post(reverse("family_add"), {
            "name": "Brother One",
            "relationship": "Brother",
            "phone_number": "9811111111",
            "blood_group": "O+",
            "city": "Kathmandu",
            "is_emergency_profile": True,
        })

        self.assertEqual(response.status_code, 302)
        self.assertTrue(FamilyMember.objects.filter(primary_user=user, name="Brother One").exists())

    def test_public_donor_directory_shows_only_verified_and_eligible_donors(self):
        # eligible donor
        donor1, _ = self.create_user(
            username="eligible_donor",
            email="eligible@example.com",
            is_donor=True,
            is_verified=True,
        )
        donor1.profile.blood_group = "O+"
        donor1.profile.city = "Kathmandu"
        donor1.profile.save()

        # ineligible donor (recent verified donation)
        donor2, _ = self.create_user(
            username="ineligible_donor",
            email="ineligible@example.com",
            is_donor=True,
            is_verified=True,
        )
        donor2.profile.blood_group = "O+"
        donor2.profile.city = "Kathmandu"
        donor2.profile.save()

        BloodDonation.objects.create(
            donor_user=donor2,
            blood_group="O+",
            units=1,
            hospital_name="City Hospital",
            donated_at=timezone.now() - timedelta(days=10),
            status="VERIFIED",
        )

        # unverified donor
        donor3, _ = self.create_user(
            username="unverified_donor",
            email="unverifieddonor@example.com",
            is_donor=True,
            is_verified=False,
        )
        donor3.profile.blood_group = "O+"
        donor3.profile.city = "Kathmandu"
        donor3.profile.save()

        response = self.client.get(reverse("public_donor_directory"), {
            "blood_group": "O+",
            "city": "Kathmandu",
        })

        self.assertEqual(response.status_code, 200)

        page_obj = response.context["page_obj"]
        usernames = {u.username for u in page_obj.object_list}

        self.assertIn("eligible_donor", usernames)
        self.assertNotIn("ineligible_donor", usernames)
        self.assertNotIn("unverified_donor", usernames)