from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.utils import timezone
import random
import string

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
    
    # Fix the clash with auth.User by adding related_name
    groups = models.ManyToManyField(
        'auth.Group',
        related_name='accounts_user_groups',  # Changed from default
        blank=True,
        help_text='The groups this user belongs to.',
        verbose_name='groups',
    )
    user_permissions = models.ManyToManyField(
        'auth.Permission',
        related_name='accounts_user_permissions',  # Changed from default
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