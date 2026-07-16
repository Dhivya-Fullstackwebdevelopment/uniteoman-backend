from rest_framework import serializers
from django.contrib.auth import authenticate
from .models import User, OTP
import re

class OTPSendSerializer(serializers.Serializer):
    mobile_number = serializers.CharField(max_length=15)
    
    def validate_mobile_number(self, value):
        # Validate mobile number format (Oman format)
        if not re.match(r'^[0-9]{8,15}$', value):
            raise serializers.ValidationError("Invalid mobile number format")
        return value

class OTPVerifySerializer(serializers.Serializer):
    mobile_number = serializers.CharField(max_length=15)
    otp_code = serializers.CharField(max_length=6)
    
    def validate(self, data):
        mobile_number = data.get('mobile_number')
        otp_code = data.get('otp_code')
        
        try:
            otp = OTP.objects.get(
                mobile_number=mobile_number,
                otp_code=otp_code,
                is_verified=False
            )
        except OTP.DoesNotExist:
            raise serializers.ValidationError("Invalid OTP code")
        
        if otp.is_expired():
            raise serializers.ValidationError("OTP has expired")
        
        if otp.attempts >= 3:
            raise serializers.ValidationError("Too many attempts")
        
        data['otp_instance'] = otp
        return data

class UserRegisterSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'mobile_number', 'name', 'email', 'password']
        extra_kwargs = {
            'password': {'write_only': True}
        }
    
    def validate_mobile_number(self, value):
        if User.objects.filter(mobile_number=value).exists():
            raise serializers.ValidationError("User with this mobile number already exists")
        return value
    
    def create(self, validated_data):
        user = User.objects.create_user(
            mobile_number=validated_data['mobile_number'],
            name=validated_data.get('name', ''),
            email=validated_data.get('email', ''),
            password=validated_data['password']
        )
        user.is_mobile_verified = True
        user.save()
        return user

class UserLoginSerializer(serializers.Serializer):
    mobile_number = serializers.CharField(max_length=15)
    password = serializers.CharField(write_only=True)
    
    def validate(self, data):
        mobile_number = data.get('mobile_number')
        password = data.get('password')
        
        # Try to authenticate
        user = authenticate(mobile_number=mobile_number, password=password)
        
        if not user:
            raise serializers.ValidationError("Invalid credentials")
        
        if not user.is_mobile_verified:
            raise serializers.ValidationError("Mobile number not verified")
        
        data['user'] = user
        return data

class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'mobile_number', 'name', 'email', 'is_mobile_verified', 'created_at']