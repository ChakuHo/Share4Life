from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from blood.models import PublicBloodRequest, DonorResponse
from communication.models import Notification, ChatThread

User = get_user_model()


class CommunicationTests(TestCase):
    def setUp(self):
        self.requester = User.objects.create_user(
            username="requester1",
            email="requester1@example.com",
            password="TestPass123!",
            is_recipient=True,
            email_verified=True,
        )

        self.donor = User.objects.create_user(
            username="donorchat1",
            email="donorchat1@example.com",
            password="TestPass123!",
            is_donor=True,
            email_verified=True,
        )

        self.other_user = User.objects.create_user(
            username="otheruser1",
            email="otheruser1@example.com",
            password="TestPass123!",
            email_verified=True,
        )

        self.req = PublicBloodRequest.objects.create(
            patient_name="Chat Patient",
            blood_group="O+",
            location_city="Kathmandu",
            hospital_name="Chat Hospital",
            contact_phone="9800000000",
            units_needed=1,
            created_by=self.requester,
            status="OPEN",
            is_active=True,
            verification_status="VERIFIED",
        )

    def test_mark_read_sets_read_at(self):
        notif = Notification.objects.create(
            user=self.requester,
            title="Test notification",
            body="Body",
            category="SYSTEM",
        )

        self.client.login(username="requester1", password="TestPass123!")
        response = self.client.get(reverse("notification_read", args=[notif.id]))

        self.assertEqual(response.status_code, 302)
        notif.refresh_from_db()
        self.assertIsNotNone(notif.read_at)

    def test_start_blood_chat_blocked_without_accepted_response(self):
        self.client.login(username="requester1", password="TestPass123!")
        response = self.client.get(reverse("chat_start_blood", args=[self.req.id, self.donor.id]))

        self.assertEqual(response.status_code, 302)
        self.assertFalse(ChatThread.objects.filter(request=self.req, donor=self.donor).exists())

    def test_start_blood_chat_creates_thread_after_accept(self):
        DonorResponse.objects.create(
            request=self.req,
            donor=self.donor,
            status="ACCEPTED",
        )

        self.client.login(username="requester1", password="TestPass123!")
        response = self.client.get(reverse("chat_start_blood", args=[self.req.id, self.donor.id]))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(ChatThread.objects.filter(request=self.req, donor=self.donor).exists())

    def test_unrelated_user_cannot_open_chat_thread_detail(self):
        thread = ChatThread.objects.create(
            request=self.req,
            requester=self.requester,
            donor=self.donor,
        )

        self.client.login(username="otheruser1", password="TestPass123!")
        response = self.client.get(reverse("chat_thread_detail", args=[thread.id]))

        self.assertEqual(response.status_code, 302)