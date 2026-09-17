from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.utils import timezone
import random
import string
from django.conf import settings


class UserManager(BaseUserManager):
    def create_user(self, mobile_number, password=None, **extra_fields):
        if not mobile_number:
            raise ValueError('Mobile number is required')
        user = self.model(mobile_number=mobile_number, **extra_fields)
        if password:
            user.set_password(password)
        user.save()
        return user

    def create_superuser(self, mobile_number, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(mobile_number, password, **extra_fields)

class User(AbstractUser):
    username = None
    mobile_number = models.CharField(max_length=15, unique=True)
    name = models.CharField(max_length=100, blank=True)
    email = models.EmailField(blank=True, null=True)
    is_mobile_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    groups = models.ManyToManyField(
        'auth.Group',
        related_name='accounts_user_groups',
        blank=True,
        help_text='The groups this user belongs to.',
        verbose_name='groups',
    )
    user_permissions = models.ManyToManyField(
        'auth.Permission',
        related_name='accounts_user_permissions',
        blank=True,
        help_text='Specific permissions for this user.',
        verbose_name='user permissions',
    )
    
    USERNAME_FIELD = 'mobile_number'
    REQUIRED_FIELDS = []
    
    objects = UserManager()
    
    def __str__(self):
        return f"{self.name} ({self.mobile_number})"

class OTP(models.Model):
    mobile_number = models.CharField(max_length=15)
    otp_code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_verified = models.BooleanField(default=False)
    attempts = models.IntegerField(default=0)
    
    def __str__(self):
        return f"{self.mobile_number} - {self.otp_code}"
    
    def is_expired(self):
        return timezone.now() > self.expires_at
    
    @classmethod
    def generate_otp(cls):
        return ''.join(random.choices(string.digits, k=6))
    
    @classmethod
    def create_otp(cls, mobile_number):
        cls.objects.filter(mobile_number=mobile_number, is_verified=False).delete()
        otp_code = cls.generate_otp()
        expires_at = timezone.now() + timezone.timedelta(minutes=5)
        return cls.objects.create(
            mobile_number=mobile_number,
            otp_code=otp_code,
            expires_at=expires_at
        )


# ============ ADMIN LOGIN MODEL ============
class AdminLogin(models.Model):
    """
    Admin login table - separate from User model
    """
    email = models.EmailField(unique=True)
    password = models.CharField(max_length=128)  # Django hashed password
    name = models.CharField(max_length=100)
    mobile_number = models.CharField(max_length=15, blank=True, null=True)
    is_staff = models.BooleanField(default=True)
    is_superuser = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_mobile_verified = models.BooleanField(default=False)
    last_login = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'admin_login'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.email} - {self.name}"
    
    def set_password(self, raw_password):
        from django.contrib.auth.hashers import make_password
        self.password = make_password(raw_password)
        self.save()

class UserProfile(models.Model):
    """Extra profile fields not on the core User model."""
    LANGUAGE_CHOICES = [("en", "English"), ("ar", "Arabic")]
    NOTIFICATION_CHOICES = [
        ("sms_push_whatsapp", "SMS + Push + WhatsApp"),
        ("sms_push", "SMS + Push"),
        ("push_only", "Push Only"),
        ("none", "None"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    preferred_area = models.CharField(max_length=100, blank=True)
    language = models.CharField(max_length=5, choices=LANGUAGE_CHOICES, default="en")
    notification_preference = models.CharField(
        max_length=30, choices=NOTIFICATION_CHOICES, default="sms_push_whatsapp"
    )
    avatar = models.ImageField(upload_to="user_avatars", blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Profile for {self.user}"


class SavedAddress(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_addresses"
    )
    label = models.CharField(max_length=50, blank=True)  # "Home", "Work"
    area = models.CharField(max_length=100)
    villa_apartment_no = models.CharField(max_length=100)
    street_name = models.CharField(max_length=150)
    building_floor = models.CharField(max_length=100, blank=True)
    nearest_landmark = models.CharField(max_length=150, blank=True)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_default", "-created_at"]

    def __str__(self):
        return f"{self.label or self.area} — {self.user}"


class SavedCard(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_cards"
    )
    card_brand = models.CharField(max_length=30, blank=True)  # "Visa", "Mastercard"
    last4 = models.CharField(max_length=4)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_default", "-created_at"]