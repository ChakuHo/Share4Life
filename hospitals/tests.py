import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from blood.models import PublicBloodRequest, BloodDonation
from hospitals.models import Organization, OrganizationMembership

User = get_user_model()


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class HospitalsTests(TestCase):
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
        self.user = User.objects.create_user(
            username="orgapplicant",
            email="orgapplicant@example.com",
            password="TestPass123!",
            email_verified=True,
        )
        self.user.profile.city = "Kathmandu"
        self.user.profile.save()

        self.verifier = User.objects.create_user(
            username="orgverifier",
            email="orgverifier@example.com",
            password="TestPass123!",
            email_verified=True,
        )

        self.recipient = User.objects.create_user(
            username="bloodrecipient",
            email="bloodrecipient@example.com",
            password="TestPass123!",
            is_recipient=True,
            is_verified=True,
            email_verified=True,
        )
        self.recipient.profile.city = "Kathmandu"
        self.recipient.profile.save()

        self.donor = User.objects.create_user(
            username="blooddonor",
            email="blooddonor@example.com",
            password="TestPass123!",
            is_donor=True,
            email_verified=True,
        )
        self.donor.profile.city = "Kathmandu"
        self.donor.profile.blood_group = "O+"
        self.donor.profile.save()

        self.org = Organization.objects.create(
            name="Kathmandu General Hospital",
            org_type="HOSPITAL",
            email="hospital@example.com",
            phone="9800000000",
            city="Kathmandu",
            address="Kathmandu",
            status="APPROVED",
            approved_at=timezone.now(),
        )
        OrganizationMembership.objects.create(
            organization=self.org,
            user=self.verifier,
            role="VERIFIER",
            is_active=True,
        )

    def test_organization_register_creates_pending_org_and_admin_membership(self):
        self.client.login(username="orgapplicant", password="TestPass123!")

        proof = SimpleUploadedFile(
            "orgproof.pdf",
            b"%PDF-1.4 org proof",
            content_type="application/pdf",
        )

        response = self.client.post(reverse("org_register"), {
            "name": "New Helping Hospital",
            "org_type": "HOSPITAL",
            "email": "neworg@example.com",
            "phone": "9811111111",
            "city": "Kathmandu",
            "address": "Some Address",
            "proof_document": proof,
        })

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            Organization.objects.filter(
                name="New Helping Hospital",
                status="PENDING"
            ).exists()
        )

        new_org = Organization.objects.get(name="New Helping Hospital")
        self.assertTrue(
            OrganizationMembership.objects.filter(
                organization=new_org,
                user=self.user,
                role="ADMIN",
            ).exists()
        )

    def test_institutions_directory_shows_only_approved_orgs(self):
        Organization.objects.create(
            name="Pending Hospital",
            org_type="HOSPITAL",
            city="Kathmandu",
            status="PENDING",
        )

        response = self.client.get(reverse("institutions_directory"))
        self.assertContains(response, "Kathmandu General Hospital")
        self.assertNotContains(response, "Pending Hospital")

    def test_org_verifier_can_approve_blood_request(self):
        req = PublicBloodRequest.objects.create(
            patient_name="Patient A",
            blood_group="O+",
            location_city="Kathmandu",
            hospital_name="Any Hospital",
            contact_phone="9800000000",
            units_needed=1,
            created_by=self.recipient,
            status="OPEN",
            is_active=True,
            verification_status="PENDING",
        )

        self.client.login(username="orgverifier", password="TestPass123!")
        response = self.client.post(reverse("org_verify_request", args=[req.id]), {
            "action": "approve",
        })

        self.assertEqual(response.status_code, 302)
        req.refresh_from_db()
        self.assertEqual(req.verification_status, "VERIFIED")
        self.assertEqual(req.target_organization, self.org)

    def test_org_verifier_can_verify_donation(self):
        req = PublicBloodRequest.objects.create(
            patient_name="Patient B",
            blood_group="O+",
            location_city="Kathmandu",
            hospital_name="Any Hospital",
            contact_phone="9800000000",
            units_needed=1,
            created_by=self.recipient,
            status="OPEN",
            is_active=True,
            verification_status="VERIFIED",
            target_organization=self.org,
        )

        donation = BloodDonation.objects.create(
            request=req,
            donor_user=self.donor,
            blood_group="O+",
            units=1,
            hospital_name="Any Hospital",
            status="COMPLETED",
        )

        self.client.login(username="orgverifier", password="TestPass123!")
        response = self.client.post(f"/institutions/portal/donations/{donation.id}/verify/")

        self.assertEqual(response.status_code, 302)
        donation.refresh_from_db()
        self.assertEqual(donation.status, "VERIFIED")