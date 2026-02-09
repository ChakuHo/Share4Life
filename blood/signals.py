from django.db.models.signals import pre_save, post_delete
from django.dispatch import receiver

from core.utils.file_cleanup import cleanup_replaced_file, cleanup_file_on_delete
from .models import PublicBloodRequest, DonationMedicalReport


@receiver(pre_save, sender=PublicBloodRequest)
def public_request_proof_cleanup_on_change(sender, instance, **kwargs):
    cleanup_replaced_file(instance, "proof_document")


@receiver(post_delete, sender=PublicBloodRequest)
def public_request_proof_cleanup_on_delete(sender, instance, **kwargs):
    cleanup_file_on_delete(instance, "proof_document")


@receiver(pre_save, sender=DonationMedicalReport)
def donation_report_cleanup_on_change(sender, instance, **kwargs):
    cleanup_replaced_file(instance, "file")


@receiver(post_delete, sender=DonationMedicalReport)
def donation_report_cleanup_on_delete(sender, instance, **kwargs):
    cleanup_file_on_delete(instance, "file")