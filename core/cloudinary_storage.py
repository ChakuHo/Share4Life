from cloudinary_storage.storage import MediaCloudinaryStorage


class AutoMediaCloudinaryStorage(MediaCloudinaryStorage):
    """
    Upload with Cloudinary resource_type='auto' so non-image KYC uploads
    (pdf/heic/etc) won't crash with "Invalid image file".
    """
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("resource_type", "auto")
        super().__init__(*args, **kwargs)