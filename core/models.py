from django.db import models
from django.utils import timezone

class SiteSetting(models.Model):
    site_name = models.CharField(max_length=100, default="Share4Life")
    site_logo = models.ImageField(upload_to='site/', blank=True, null=True)
    favicon = models.ImageField(upload_to='site/', blank=True, null=True)

    # Homepage Hero Section
    hero_title = models.CharField(max_length=200, default="Every Drop Counts, Every Penny Helps.")
    hero_subtitle = models.TextField(default="The integrated platform for Blood Donation, Organ Pledging, and Medical Crowdfunding.")
    hero_background = models.ImageField(upload_to='site/hero/', blank=True, null=True, help_text="Upload a 1920x600 image")

    # Contact Info (Footer)
    contact_email = models.EmailField(default="share4life.noreply@gmail.com")
    contact_phone = models.CharField(max_length=20, default="+977-9849632576")
    address = models.CharField(max_length=255, default="Lalitpur, Nepal")

    # Social Media
    facebook_url = models.URLField(blank=True)
    twitter_url = models.URLField(blank=True)
    instagram_url = models.URLField(blank=True)

    # Meta
    footer_text = models.TextField(default="Saving Lives, One Donation at a Time.")

    # About page content (dynamic)
    about_title = models.CharField(max_length=200, default="About Share4Life")
    about_intro = models.TextField(
        default="Share4Life connects donors, recipients, and verified institutions to save lives faster in emergencies."
    )
    about_trust_safety = models.TextField(
        default="• Proof required for critical requests\n• Institution verification for trust\n• Privacy-aware contact sharing\n• Audit-friendly history & records"
    )
    about_how_it_works = models.TextField(
        default="• Request created with proof\n• Donors receive notifications\n• Donor responds and donates at hospital\n• Institution verifies donation\n• Eligibility & history updated"
    )

    def save(self, *args, **kwargs):
        self.pk = 1
        super(SiteSetting, self).save(*args, **kwargs)

    def __str__(self):
        return "Site Configuration"

    class Meta:
        verbose_name = "Site Setting"
        verbose_name_plural = "Site Settings"


class TeamMember(models.Model):
    name = models.CharField(max_length=120)
    role = models.CharField(max_length=120, blank=True)
    photo = models.ImageField(upload_to="site/team/", blank=True, null=True)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class GalleryImage(models.Model):
    """
    Gallery item with impact info (blood units, funds, etc.)
    """
    title = models.CharField(max_length=120, blank=True)
    image = models.ImageField(upload_to="site/gallery/")

    # Impact / event info
    event_date = models.DateField(null=True, blank=True)
    city = models.CharField(max_length=100, blank=True)
    venue = models.CharField(max_length=150, blank=True)

    blood_units_collected = models.PositiveIntegerField(null=True, blank=True)
    funds_raised = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    people_helped = models.PositiveIntegerField(null=True, blank=True)

    description = models.TextField(blank=True, help_text="Write what happened, highlights, outcomes, etc.")

    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["order", "-event_date", "-created_at"]

    def __str__(self):
        return self.title or f"Gallery #{self.id}"