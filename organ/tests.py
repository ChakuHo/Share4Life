from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from hospitals.models import Organization, OrganizationMembership
from organ.models import OrganPledge, OrganRequest, OrganMatch

User = get_user_model()


class OrganTests(TestCase):
    def setUp(self):
        self.donor = User.objects.create_user(
            username="organdonor",
            email="organdonor@example.com",
            password="TestPass123!",
            is_donor=True,
            email_verified=True,
        )
        self.donor.profile.city = "Kathmandu"
        self.donor.profile.save()

        self.recipient = User.objects.create_user(
            username="organrecipient",
            email="organrecipient@example.com",
            password="TestPass123!",
            is_recipient=True,
            email_verified=True,
        )
        self.recipient.profile.city = "Kathmandu"
        self.recipient.profile.save()

        self.verifier = User.objects.create_user(
            username="organverifier",
            email="organverifier@example.com",
            password="TestPass123!",
            email_verified=True,
        )

        self.org = Organization.objects.create(
            name="Organ Care Hospital",
            org_type="HOSPITAL",
            city="Kathmandu",
            status="APPROVED",
        )
        OrganizationMembership.objects.create(
            organization=self.org,
            user=self.verifier,
            role="VERIFIER",
            is_active=True,
        )

    def test_pledge_submit_requires_consent_and_document(self):
        pledge = OrganPledge.objects.create(
            donor=self.donor,
            pledge_type="LIVING",
            organs=["KIDNEY"],
            consent_confirmed=False,
            status="DRAFT",
        )

        self.client.login(username="organdonor", password="TestPass123!")
        response = self.client.post(reverse("organ_pledge_submit", args=[pledge.id]))
        self.assertEqual(response.status_code, 302)

        pledge.refresh_from_db()
        self.assertEqual(pledge.status, "DRAFT")

        pledge.consent_confirmed = True
        pledge.save(update_fields=["consent_confirmed"])

        response = self.client.post(reverse("organ_pledge_submit", args=[pledge.id]))
        self.assertEqual(response.status_code, 302)

        pledge.refresh_from_db()
        self.assertNotEqual(pledge.status, "UNDER_REVIEW")

    def test_recipient_can_create_organ_request(self):
        self.client.login(username="organrecipient", password="TestPass123!")

        response = self.client.post(reverse("organ_request_create"), {
            "patient_name": "Recipient Name",
            "organ_needed": "KIDNEY",
            "urgency": "HIGH",
            "hospital_name": "Teaching Hospital",
            "city": "Kathmandu",
            "contact_phone": "9800000000",
            "note": "Urgent case",
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(OrganRequest.objects.count(), 1)

        req = OrganRequest.objects.first()
        self.assertEqual(req.created_by, self.recipient)
        self.assertEqual(req.status, "UNDER_REVIEW")

    def test_org_verifier_can_approve_pledge(self):
        pledge = OrganPledge.objects.create(
            donor=self.donor,
            pledge_type="LIVING",
            organs=["KIDNEY"],
            consent_confirmed=True,
            status="UNDER_REVIEW",
        )

        self.client.login(username="organverifier", password="TestPass123!")
        response = self.client.post(reverse("org_verify_pledge", args=[pledge.id]), {
            "action": "approve",
        })

        self.assertEqual(response.status_code, 302)
        pledge.refresh_from_db()
        self.donor.profile.refresh_from_db()

        self.assertEqual(pledge.status, "VERIFIED")
        self.assertEqual(pledge.verified_by_org, self.org)
        self.assertGreaterEqual(self.donor.profile.points, 150)

    def test_org_verifier_can_activate_request(self):
        req = OrganRequest.objects.create(
            created_by=self.recipient,
            patient_name="Patient One",
            organ_needed="KIDNEY",
            urgency="CRITICAL",
            hospital_name="Organ Hospital",
            city="Kathmandu",
            contact_phone="9800000000",
            status="UNDER_REVIEW",
        )

        self.client.login(username="organverifier", password="TestPass123!")
        response = self.client.post(reverse("org_verify_organ_request", args=[req.id]), {
            "action": "approve",
        })

        self.assertEqual(response.status_code, 302)
        req.refresh_from_db()

        self.assertEqual(req.status, "ACTIVE")
        self.assertEqual(req.target_organization, self.org)

    def test_org_can_create_match_for_active_request(self):
        pledge = OrganPledge.objects.create(
            donor=self.donor,
            pledge_type="LIVING",
            organs=["KIDNEY"],
            consent_confirmed=True,
            status="VERIFIED",
            verified_by=self.verifier,
            verified_by_org=self.org,
        )

        req = OrganRequest.objects.create(
            created_by=self.recipient,
            patient_name="Patient Match",
            organ_needed="KIDNEY",
            urgency="HIGH",
            hospital_name="Organ Hospital",
            city="Kathmandu",
            contact_phone="9800000000",
            status="ACTIVE",
            target_organization=self.org,
        )

        self.client.login(username="organverifier", password="TestPass123!")
        response = self.client.post(reverse("organ_match_create", args=[req.id]), {
            "pledge": pledge.id,
            "notes": "Potential compatible donor",
        })

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            OrganMatch.objects.filter(
                request=req,
                pledge=pledge,
                organization=self.org
            ).exists()
        )

        req.refresh_from_db()
        self.assertEqual(req.status, "MATCH_IN_PROGRESS")