from django.db.models.fields.files import FieldFile

def cleanup_replaced_file(instance, field_name: str):
    """
    If a FileField/ImageField on `instance` is changed (or cleared), delete the old file.
    Only affects the given field on the given model.
    """
    if not instance.pk:
        return

    try:
        old_instance = instance.__class__.objects.get(pk=instance.pk)
    except instance.__class__.DoesNotExist:
        return

    old_file = getattr(old_instance, field_name, None)
    new_file = getattr(instance, field_name, None)

    # Old exists?
    if not isinstance(old_file, FieldFile) or not old_file or not old_file.name:
        return

    # Case A: field cleared
    if not new_file or (isinstance(new_file, FieldFile) and not new_file.name):
        old_file.delete(save=False)
        return

    # Case B: file replaced
    if isinstance(new_file, FieldFile) and old_file.name != new_file.name:
        old_file.delete(save=False)


def cleanup_file_on_delete(instance, field_name: str):
    """
    When a model row is deleted, delete its file field from storage.
    """
    f = getattr(instance, field_name, None)
    if isinstance(f, FieldFile) and f and f.name:
        f.delete(save=False)