import shutil
import tempfile
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from crowdfunding.models import Campaign, CampaignDocument, Donation

User = get_user_model()


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class CrowdfundingTests(TestCase):
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

    def setUp(self):
        self.verified_user = User.objects.create_user(
            username="verifiedowner",
            email="verifiedowner@example.com",
            password="TestPass123!",
            is_verified=True,
            email_verified=True,
        )
        self.normal_user = User.objects.create_user(
            username="normaluser",
            email="normaluser@example.com",
            password="TestPass123!",
            is_verified=False,
            email_verified=True,
        )

    def test_campaign_slug_generation(self):
        camp = Campaign.objects.create(
            title="Heart Surgery Support",
            patient_name="Hari",
            description="Need urgent support",
            target_amount=Decimal("50000.00"),
            owner=self.verified_user,
            hospital_city="Kathmandu",
            deadline=timezone.localdate() + timedelta(days=10),
        )
        self.assertTrue(camp.slug)

    @patch("crowdfunding.views.notify_user")
    def test_verified_user_can_create_campaign(self, _mock_notify):
        self.client.login(username="verifiedowner", password="TestPass123!")

        proof = SimpleUploadedFile(
            "proof.pdf",
            b"%PDF-1.4 test file",
            content_type="application/pdf",
        )

        response = self.client.post(reverse("campaign_create"), {
            "title": "Kidney Treatment Fund",
            "patient_name": "Sita",
            "description": "Medical fundraising case",
            "target_amount": "100000.00",
            "deadline": str(timezone.localdate() + timedelta(days=7)),
            "hospital_name": "Teaching Hospital",
            "hospital_city": "Kathmandu",
            "hospital_contact_phone": "9800000000",
            "proof_type": "MEDICAL_REPORT",
            "proof_file": proof,
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Campaign.objects.count(), 1)

        camp = Campaign.objects.first()
        self.assertEqual(camp.owner, self.verified_user)
        self.assertEqual(camp.status, "PENDING")
        self.assertTrue(CampaignDocument.objects.filter(campaign=camp).exists())

    def test_non_verified_user_blocked_from_campaign_create(self):
        self.client.login(username="normaluser", password="TestPass123!")
        response = self.client.get(reverse("campaign_create"))
        self.assertEqual(response.status_code, 302)

    def test_owner_cannot_donate_to_own_campaign(self):
        camp = Campaign.objects.create(
            title="Self Campaign",
            patient_name="Owner",
            description="Owner campaign",
            target_amount=Decimal("10000.00"),
            owner=self.verified_user,
            status="APPROVED",
            deadline=timezone.localdate() + timedelta(days=5),
        )

        self.client.login(username="verifiedowner", password="TestPass123!")
        response = self.client.post(reverse("donate_start", args=[camp.id]), {
            "amount": "1000.00",
            "gateway": "KHALTI",
        })

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Donation.objects.filter(campaign=camp).exists())

    def test_campaign_mark_completed_if_needed(self):
        camp = Campaign.objects.create(
            title="Goal Reached Campaign",
            patient_name="Patient Z",
            description="Goal reached soon",
            target_amount=Decimal("1000.00"),
            owner=self.verified_user,
            status="APPROVED",
            deadline=timezone.localdate() + timedelta(days=5),
        )

        Donation.objects.create(
            campaign=camp,
            donor_user=self.normal_user,
            amount=Decimal("1200.00"),
            gateway="KHALTI",
            status="SUCCESS",
        )

        camp.refresh_raised_amount()
        camp.mark_completed_if_needed()
        camp.refresh_from_db()

        self.assertEqual(camp.status, "COMPLETED")