from django.db.models.signals import pre_save, post_delete
from django.dispatch import receiver

from core.utils.file_cleanup import cleanup_replaced_file, cleanup_file_on_delete
from .models import SiteSetting, TeamMember, GalleryImage


# --- Site settings images ---
@receiver(pre_save, sender=SiteSetting)
def site_setting_images_cleanup_on_change(sender, instance, **kwargs):
    cleanup_replaced_file(instance, "site_logo")
    cleanup_replaced_file(instance, "favicon")
    cleanup_replaced_file(instance, "hero_background")


@receiver(post_delete, sender=SiteSetting)
def site_setting_images_cleanup_on_delete(sender, instance, **kwargs):
    cleanup_file_on_delete(instance, "site_logo")
    cleanup_file_on_delete(instance, "favicon")
    cleanup_file_on_delete(instance, "hero_background")


# --- Team member photo ---
@receiver(pre_save, sender=TeamMember)
def team_member_photo_cleanup_on_change(sender, instance, **kwargs):
    cleanup_replaced_file(instance, "photo")


@receiver(post_delete, sender=TeamMember)
def team_member_photo_cleanup_on_delete(sender, instance, **kwargs):
    cleanup_file_on_delete(instance, "photo")


# --- Gallery image ---
@receiver(pre_save, sender=GalleryImage)
def gallery_image_cleanup_on_change(sender, instance, **kwargs):
    cleanup_replaced_file(instance, "image")


@receiver(post_delete, sender=GalleryImage)
def gallery_image_cleanup_on_delete(sender, instance, **kwargs):
    cleanup_file_on_delete(instance, "image")