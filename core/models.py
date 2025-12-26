from django.db import models

class SiteSetting(models.Model):
    site_name = models.CharField(max_length=100, default="Share4Life")
    site_logo = models.ImageField(upload_to='site/', blank=True, null=True)
    favicon = models.ImageField(upload_to='site/', blank=True, null=True)

        # Homepage Hero Section

    hero_title = models.CharField(max_length=200, default="Every Drop Counts, Every Penny Helps.")
    hero_subtitle = models.TextField(default="The integrated platform for Blood Donation, Organ Pledging, and Medical Crowdfunding.")
    hero_background = models.ImageField(upload_to='site/hero/', blank=True, null=True, help_text="Upload a 1920x600 image")
    
    # Contact Info (Footer)
    contact_email = models.EmailField(default="support@share4life.com")
    contact_phone = models.CharField(max_length=20, default="+977-9800000000")
    address = models.CharField(max_length=255, default="Kathmandu, Nepal")
    
    # Social Media
    facebook_url = models.URLField(blank=True)
    twitter_url = models.URLField(blank=True)
    instagram_url = models.URLField(blank=True)
    
    # Meta
    footer_text = models.TextField(default="Saving Lives, One Donation at a Time.")


    def save(self, *args, **kwargs):
        # This ensures there is only ever ONE settings object (ID=1)
        self.pk = 1
        super(SiteSetting, self).save(*args, **kwargs)

    def __str__(self):
        return "Site Configuration"
    
    class Meta:
        verbose_name = "Site Setting"
        verbose_name_plural = "Site Settings"