from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.authtoken.models import Token
from django.contrib.auth import authenticate
from django.utils import timezone
from .models import User, OTP
from .serializers import (
    OTPSendSerializer, OTPVerifySerializer, 
    UserRegisterSerializer, UserLoginSerializer,
    UserProfileSerializer
)
import logging

logger = logging.getLogger(__name__)

# ------------------- SMS Helper Functions -------------------

def send_otp_sms(mobile_number, otp_code):
    """
    Send OTP via SMS - Testing mode or Twilio
    """
    try:
        # For testing: Print OTP to console
        print(f"=====================================")
        print(f"📱 OTP for {mobile_number}: {otp_code}")
        print(f"⏰ Expires in 5 minutes")
        print(f"=====================================")
        
        # Uncomment for production with Twilio
        # from twilio.rest import Client
        # from django.conf import settings
        # client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        # message = client.messages.create(
        #     body=f"Your OTP for UniteOman is: {otp_code}. Valid for 5 minutes.",
        #     from_=settings.TWILIO_PHONE_NUMBER,
        #     to=f"+{mobile_number}"  # Add country code if needed
        # )
        return True
    except Exception as e:
        logger.error(f"SMS sending failed: {str(e)}")
        return False

# ------------------- API Views -------------------

@api_view(['POST'])
@permission_classes([AllowAny])
def send_otp(request):
    """
    Send OTP to mobile number
    """
    serializer = OTPSendSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({
            'status': 'error',
            'message': 'Invalid data',
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)
    
    mobile_number = serializer.validated_data['mobile_number']
    
    # Check if user exists
    user_exists = User.objects.filter(mobile_number=mobile_number).exists()
    
    # Create OTP
    otp = OTP.create_otp(mobile_number)
    
    # Send SMS
    sms_sent = send_otp_sms(mobile_number, otp.otp_code)
    
    if not sms_sent:
        return Response({
            'status': 'error',
            'message': 'Failed to send OTP. Please try again.'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    return Response({
        'status': 'success',
        'message': 'OTP sent successfully',
        'data': {
            'mobile_number': mobile_number,
            'expires_in': '5 minutes',
            'user_exists': user_exists
        }
    })

@api_view(['POST'])
@permission_classes([AllowAny])
def verify_otp(request):
    """
    Verify OTP code
    """
    serializer = OTPVerifySerializer(data=request.data)
    if not serializer.is_valid():
        return Response({
            'status': 'error',
            'message': 'Invalid data',
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)
    
    mobile_number = serializer.validated_data['mobile_number']
    otp_instance = serializer.validated_data['otp_instance']
    
    # Mark OTP as verified
    otp_instance.is_verified = True
    otp_instance.save()
    
    # Check if user already exists
    user = User.objects.filter(mobile_number=mobile_number).first()
    
    return Response({
        'status': 'success',
        'message': 'OTP verified successfully',
        'data': {
            'mobile_number': mobile_number,
            'is_verified': True,
            'user_exists': user is not None,
            'user': UserProfileSerializer(user).data if user else None
        }
    })

@api_view(['POST'])
@permission_classes([AllowAny])
def register_user(request):
    """
    Register new user after OTP verification
    """
    # Check if OTP is verified
    mobile_number = request.data.get('mobile_number')
    
    try:
        otp = OTP.objects.get(
            mobile_number=mobile_number,
            is_verified=True
        )
    except OTP.DoesNotExist:
        return Response({
            'status': 'error',
            'message': 'Mobile number not verified. Please verify OTP first.'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    # Check if user already exists
    if User.objects.filter(mobile_number=mobile_number).exists():
        return Response({
            'status': 'error',
            'message': 'User already exists with this mobile number. Please login.'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    # Create user
    serializer = UserRegisterSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({
            'status': 'error',
            'message': 'Invalid data',
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)
    
    user = serializer.save()
    user.is_mobile_verified = True
    user.save()
    
    # Create token
    token, created = Token.objects.get_or_create(user=user)
    
    return Response({
        'status': 'success',
        'message': 'Account created successfully',
        'data': {
            'user': UserProfileSerializer(user).data,
            'token': token.key
        }
    })

@api_view(['POST'])
@permission_classes([AllowAny])
def login_user(request):
    """
    Login user with mobile number and password
    """
    serializer = UserLoginSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({
            'status': 'error',
            'message': 'Invalid credentials',
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)
    
    user = serializer.validated_data['user']
    
    # Create or get token
    token, created = Token.objects.get_or_create(user=user)
    
    return Response({
        'status': 'success',
        'message': 'Login successful',
        'data': {
            'user': UserProfileSerializer(user).data,
            'token': token.key
        }
    })

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_profile(request):
    """
    Get user profile
    """
    serializer = UserProfileSerializer(request.user)
    return Response({
        'status': 'success',
        'data': serializer.data
    })

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def update_profile(request):
    """
    Update user profile
    """
    user = request.user
    user.name = request.data.get('name', user.name)
    user.email = request.data.get('email', user.email)
    user.save()
    
    return Response({
        'status': 'success',
        'message': 'Profile updated successfully',
        'data': UserProfileSerializer(user).data
    })

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout_user(request):
    """
    Logout user (delete token)
    """
    try:
        request.user.auth_token.delete()
    except:
        pass
    
    return Response({
        'status': 'success',
        'message': 'Logged out successfully'
    })

# Forgot Password - Send OTP
@api_view(['POST'])
@permission_classes([AllowAny])
def forgot_password(request):
    """
    Send OTP for password reset
    """
    mobile_number = request.data.get('mobile_number')
    
    if not mobile_number:
        return Response({
            'status': 'error',
            'message': 'Mobile number is required'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    # Check if user exists
    try:
        user = User.objects.get(mobile_number=mobile_number)
    except User.DoesNotExist:
        return Response({
            'status': 'error',
            'message': 'User not found with this mobile number'
        }, status=status.HTTP_404_NOT_FOUND)
    
    # Create OTP
    otp = OTP.create_otp(mobile_number)
    
    # Send SMS
    send_otp_sms(mobile_number, otp.otp_code)
    
    return Response({
        'status': 'success',
        'message': 'OTP sent for password reset',
        'data': {
            'mobile_number': mobile_number,
            'expires_in': '5 minutes'
        }
    })

# Reset Password
@api_view(['POST'])
@permission_classes([AllowAny])
def reset_password(request):
    """
    Reset password after OTP verification
    """
    mobile_number = request.data.get('mobile_number')
    new_password = request.data.get('new_password')
    confirm_password = request.data.get('confirm_password')
    
    if not all([mobile_number, new_password, confirm_password]):
        return Response({
            'status': 'error',
            'message': 'All fields are required'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    if new_password != confirm_password:
        return Response({
            'status': 'error',
            'message': 'Passwords do not match'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    if len(new_password) < 6:
        return Response({
            'status': 'error',
            'message': 'Password must be at least 6 characters'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    # Check OTP verification
    try:
        otp = OTP.objects.get(
            mobile_number=mobile_number,
            is_verified=True
        )
    except OTP.DoesNotExist:
        return Response({
            'status': 'error',
            'message': 'Mobile number not verified. Please verify OTP first.'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    # Update password
    try:
        user = User.objects.get(mobile_number=mobile_number)
        user.set_password(new_password)
        user.save()
        
        # Invalidate the OTP
        otp.delete()
        
        return Response({
            'status': 'success',
            'message': 'Password reset successfully'
        })
    except User.DoesNotExist:
        return Response({
            'status': 'error',
            'message': 'User not found'
        }, status=status.HTTP_404_NOT_FOUND)