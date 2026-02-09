from django.db.models.signals import pre_save, post_delete
from django.dispatch import receiver

from core.utils.file_cleanup import cleanup_replaced_file, cleanup_file_on_delete
from .models import CustomUser, KYCDocument


# --- Profile image cleanup ---
@receiver(pre_save, sender=CustomUser)
def user_profile_image_cleanup_on_change(sender, instance, **kwargs):
    cleanup_replaced_file(instance, "profile_image")


@receiver(post_delete, sender=CustomUser)
def user_profile_image_cleanup_on_delete(sender, instance, **kwargs):
    cleanup_file_on_delete(instance, "profile_image")


# --- KYC document cleanup (unique_together makes this perfect) ---
@receiver(pre_save, sender=KYCDocument)
def kyc_doc_cleanup_on_change(sender, instance, **kwargs):
    cleanup_replaced_file(instance, "file")


@receiver(post_delete, sender=KYCDocument)
def kyc_doc_cleanup_on_delete(sender, instance, **kwargs):
    cleanup_file_on_delete(instance, "file")