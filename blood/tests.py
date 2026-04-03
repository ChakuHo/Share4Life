from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from blood.models import PublicBloodRequest, DonorResponse, BloodDonation

User = get_user_model()


@override_settings(RECAPTCHA_ENABLED=False)
class BloodTests(TestCase):
    def setUp(self):
        self.recipient = User.objects.create_user(
            username="recipient1",
            email="recipient1@example.com",
            password="TestPass123!",
            is_recipient=True,
            is_verified=True,
            email_verified=True,
        )
        self.recipient.profile.city = "Kathmandu"
        self.recipient.profile.save()

        self.donor = User.objects.create_user(
            username="donor1",
            email="donor1@example.com",
            password="TestPass123!",
            is_donor=True,
            email_verified=True,
        )
        self.donor.profile.city = "Kathmandu"
        self.donor.profile.blood_group = "O+"
        self.donor.profile.save()

        self.admin = User.objects.create_superuser(
            username="admin1",
            email="admin1@example.com",
            password="AdminPass123!",
        )

    def test_public_blood_request_generates_slug_and_city_canon(self):
        req = PublicBloodRequest.objects.create(
            patient_name="Ram",
            blood_group="O+",
            location_city="Kathmandu",
            hospital_name="Bir Hospital",
            contact_phone="9800000000",
            units_needed=1,
        )
        self.assertTrue(req.slug)
        self.assertTrue(req.location_city_canon)

    @patch("blood.views.push_ping_to_donors")
    def test_recipient_can_create_blood_request(self, _mock_push):
        self.client.login(username="recipient1", password="TestPass123!")

        response = self.client.post(reverse("recipient_request"), {
            "patient_name": "Recipient One",
            "blood_group": "O+",
            "location_city": "Kathmandu",
            "hospital_name": "Bir Hospital",
            "contact_phone": "9800000000",
            "units_needed": 1,
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(PublicBloodRequest.objects.count(), 1)

        req = PublicBloodRequest.objects.first()
        self.assertEqual(req.created_by, self.recipient)
        self.assertEqual(req.status, "OPEN")
        self.assertEqual(req.verification_status, "VERIFIED")

    @patch("blood.views.push_request_event")
    def test_donor_quick_accept_sets_request_in_progress(self, _mock_event):
        req = PublicBloodRequest.objects.create(
            patient_name="Patient A",
            blood_group="O+",
            location_city="Kathmandu",
            hospital_name="City Hospital",
            contact_phone="9800000000",
            units_needed=1,
            created_by=self.recipient,
            status="OPEN",
            is_active=True,
            verification_status="VERIFIED",
        )

        self.client.login(username="donor1", password="TestPass123!")
        response = self.client.post(reverse("quick_respond", args=[req.id]), {
            "status": "ACCEPTED",
            "message": "I can donate",
        })

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            DonorResponse.objects.filter(
                request=req,
                donor=self.donor,
                status="ACCEPTED"
            ).exists()
        )

        req.refresh_from_db()
        self.assertEqual(req.status, "IN_PROGRESS")

    @patch("blood.views.push_request_event")
    def test_request_owner_cannot_respond_to_own_request(self, _mock_event):
        owner = User.objects.create_user(
            username="ownerboth",
            email="ownerboth@example.com",
            password="TestPass123!",
            is_recipient=True,
            is_donor=True,
            email_verified=True,
        )
        owner.profile.city = "Kathmandu"
        owner.profile.blood_group = "A+"
        owner.profile.save()

        req = PublicBloodRequest.objects.create(
            patient_name="Owner Patient",
            blood_group="A+",
            location_city="Kathmandu",
            hospital_name="Hospital X",
            contact_phone="9800000001",
            units_needed=1,
            created_by=owner,
            status="OPEN",
            is_active=True,
            verification_status="VERIFIED",
        )

        self.client.login(username="ownerboth", password="TestPass123!")
        response = self.client.post(reverse("quick_respond", args=[req.id]), {
            "status": "ACCEPTED",
        })

        self.assertEqual(response.status_code, 302)
        self.assertFalse(DonorResponse.objects.filter(request=req, donor=owner).exists())

    def test_verify_donation_marks_verified_and_fulfills_request(self):
        req = PublicBloodRequest.objects.create(
            patient_name="Patient B",
            blood_group="O+",
            location_city="Kathmandu",
            hospital_name="Hospital Y",
            contact_phone="9800000002",
            units_needed=1,
            created_by=self.recipient,
            status="OPEN",
            is_active=True,
            verification_status="VERIFIED",
        )

        donation = BloodDonation.objects.create(
            request=req,
            donor_user=self.donor,
            blood_group="O+",
            units=1,
            hospital_name="Hospital Y",
            donated_at=timezone.now(),
            status="COMPLETED",
        )

        self.client.login(username="admin1", password="AdminPass123!")
        response = self.client.post(f"/blood/donation/{donation.id}/verify/")

        self.assertEqual(response.status_code, 302)

        donation.refresh_from_db()
        req.refresh_from_db()
        self.donor.profile.refresh_from_db()

        self.assertEqual(donation.status, "VERIFIED")
        self.assertEqual(req.status, "FULFILLED")
        self.assertFalse(req.is_active)
        self.assertGreaterEqual(self.donor.profile.points, 150)