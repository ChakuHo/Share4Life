from django.test import TestCase
from django.urls import reverse

from core.models import GalleryImage


class CoreTests(TestCase):
    def test_about_page_loads(self):
        response = self.client.get(reverse("about"))
        self.assertEqual(response.status_code, 200)

    def test_gallery_list_loads(self):
        response = self.client.get(reverse("gallery_list"))
        self.assertEqual(response.status_code, 200)

    def test_gallery_detail_loads(self):
        item = GalleryImage.objects.create(
            title="Impact Event",
            image="site/gallery/test.jpg",
            is_active=True,
        )
        response = self.client.get(reverse("gallery_detail", args=[item.id]))
        self.assertEqual(response.status_code, 200)