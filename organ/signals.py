from django.db.models.signals import pre_save, post_delete
from django.dispatch import receiver

from core.utils.file_cleanup import cleanup_replaced_file, cleanup_file_on_delete
from .models import OrganPledgeDocument, OrganRequestDocument


@receiver(pre_save, sender=OrganPledgeDocument)
def pledge_doc_cleanup_on_change(sender, instance, **kwargs):
    cleanup_replaced_file(instance, "file")


@receiver(post_delete, sender=OrganPledgeDocument)
def pledge_doc_cleanup_on_delete(sender, instance, **kwargs):
    cleanup_file_on_delete(instance, "file")


@receiver(pre_save, sender=OrganRequestDocument)
def request_doc_cleanup_on_change(sender, instance, **kwargs):
    cleanup_replaced_file(instance, "file")


@receiver(post_delete, sender=OrganRequestDocument)
def request_doc_cleanup_on_delete(sender, instance, **kwargs):
    cleanup_file_on_delete(instance, "file")