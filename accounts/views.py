from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth import authenticate, login, logout
from django.core.mail import send_mail
from django.conf import settings
from twilio.rest import Client
from .models import User, OTP, AdminLogin  # Import AdminLogin model
from .serializers import (
    OTPSendSerializer, OTPVerifySerializer, 
    UserRegisterSerializer, UserLoginSerializer,
    UserProfileSerializer
)
from professionals.models import Professional
from django.contrib.auth.hashers import check_password, make_password

# ============ OTP ENDPOINTS ============

@api_view(['POST'])
@permission_classes([AllowAny])
def send_otp(request):
    """
    Send OTP via SMS (Twilio) and Email
    """
    serializer = OTPSendSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({'error': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
    
    mobile_number = serializer.validated_data['mobile_number']
    
    # Generate OTP
    otp_instance = OTP.create_otp(mobile_number)
    otp_code = otp_instance.otp_code
    
    # Send OTP via Twilio SMS
    try:
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        message = client.messages.create(
            body=f'Your OTP code is: {otp_code}',
            from_=settings.TWILIO_PHONE_NUMBER,
            to=f'+{mobile_number}'
        )
        print(f"✅ SMS sent: {message.sid}")
    except Exception as e:
        print(f"❌ SMS failed: {str(e)}")
        # Still continue - we'll also send via email
    
    # Send OTP via Email (if user has email)
    try:
        # If user exists and has email
        user = User.objects.filter(mobile_number=mobile_number).first()
        if user and user.email:
            send_mail(
                subject='Your OTP Code',
                message=f'Your OTP code is: {otp_code}\nThis code expires in 5 minutes.',
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=False,
            )
            print(f"✅ Email sent to: {user.email}")
    except Exception as e:
        print(f"❌ Email failed: {str(e)}")
    
    # For testing - print OTP to console
    print(f"📱 OTP for {mobile_number}: {otp_code}")
    
    return Response({
        'message': 'OTP sent successfully',
        'mobile_number': mobile_number,
        # Remove this in production, keep for testing
        'debug_otp': otp_code  
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([AllowAny])
def otp_verify(request):
    """
    Verify OTP code
    """
    serializer = OTPVerifySerializer(data=request.data)
    if not serializer.is_valid():
        return Response({'error': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
    
    # Get OTP instance from validated data
    otp_instance = serializer.validated_data['otp_instance']
    
    # Mark OTP as verified
    otp_instance.is_verified = True
    otp_instance.save()
    
    # Update user if exists
    mobile_number = serializer.validated_data['mobile_number']
    try:
        user = User.objects.get(mobile_number=mobile_number)
        user.is_mobile_verified = True
        user.save()
    except User.DoesNotExist:
        pass
    
    return Response({
        'message': 'OTP verified successfully',
        'mobile_number': mobile_number
    }, status=status.HTTP_200_OK)


# ============ AUTH ENDPOINTS ============

@api_view(['POST'])
@permission_classes([AllowAny])
def register_user(request):
    """
    Register a new user
    """
    # Check if mobile is verified
    mobile_number = request.data.get('mobile_number')
    if mobile_number:
        if not OTP.objects.filter(mobile_number=mobile_number, is_verified=True).exists():
            return Response({
                'error': 'Mobile number not verified. Please verify OTP first.'
            }, status=status.HTTP_400_BAD_REQUEST)
    
    serializer = UserRegisterSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.save()
        return Response({
            'message': 'User registered successfully',
            'user': UserProfileSerializer(user).data
        }, status=status.HTTP_201_CREATED)
    
    return Response({'error': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([AllowAny])
def login_user(request):
    """
    Login user with mobile number and password
    """
    serializer = UserLoginSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({'error': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    user = serializer.validated_data['user']

    from rest_framework_simplejwt.tokens import RefreshToken
    refresh = RefreshToken.for_user(user)

    return Response({
        'message': 'Login successful',
        'user_id': user.id,
        'user': UserProfileSerializer(user).data,
        'access': str(refresh.access_token),
        'refresh': str(refresh),
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout_user(request):
    """
    Logout user
    """
    logout(request)
    return Response({'message': 'Logged out successfully'}, status=status.HTTP_200_OK)


# ============ PROFILE ENDPOINTS ============

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_profile(request):
    """
    Get user profile
    """
    serializer = UserProfileSerializer(request.user)
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['PUT', 'PATCH'])
@permission_classes([IsAuthenticated])
def update_profile(request):
    """
    Update user profile
    """
    user = request.user
    serializer = UserProfileSerializer(user, data=request.data, partial=True)
    
    if serializer.is_valid():
        serializer.save()
        return Response({
            'message': 'Profile updated successfully',
            'user': serializer.data
        }, status=status.HTTP_200_OK)
    
    return Response({'error': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)


# ============ PASSWORD RESET ============

@api_view(['POST'])
@permission_classes([AllowAny])
def forgot_password(request):
    """
    Send OTP for password reset
    """
    mobile_number = request.data.get('mobile_number')
    
    if not mobile_number:
        return Response({'error': 'Mobile number is required'}, 
                       status=status.HTTP_400_BAD_REQUEST)
    
    try:
        user = User.objects.get(mobile_number=mobile_number)
    except User.DoesNotExist:
        return Response({'error': 'User with this mobile number does not exist'}, 
                       status=status.HTTP_404_NOT_FOUND)
    
    # Send OTP for password reset
    otp_instance = OTP.create_otp(mobile_number)
    
    # Send OTP via SMS
    try:
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        message = client.messages.create(
            body=f'Your password reset OTP is: {otp_instance.otp_code}',
            from_=settings.TWILIO_PHONE_NUMBER,
            to=f'+{mobile_number}'
        )
    except Exception as e:
        print(f"❌ SMS failed: {str(e)}")
    
    return Response({
        'message': 'Password reset OTP sent',
        'mobile_number': mobile_number,
        'debug_otp': otp_instance.otp_code  # Remove in production
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([AllowAny])
def reset_password(request):
    """
    Reset password using OTP
    """
    mobile_number = request.data.get('mobile_number')
    otp_code = request.data.get('otp_code')
    new_password = request.data.get('new_password')
    
    if not all([mobile_number, otp_code, new_password]):
        return Response({'error': 'All fields are required'}, 
                       status=status.HTTP_400_BAD_REQUEST)
    
    # Verify OTP
    try:
        otp = OTP.objects.get(
            mobile_number=mobile_number,
            otp_code=otp_code,
            is_verified=False
        )
    except OTP.DoesNotExist:
        return Response({'error': 'Invalid OTP'}, 
                       status=status.HTTP_400_BAD_REQUEST)
    
    if otp.is_expired():
        return Response({'error': 'OTP has expired'}, 
                       status=status.HTTP_400_BAD_REQUEST)
    
    # Mark OTP as verified
    otp.is_verified = True
    otp.save()
    
    # Update password
    try:
        user = User.objects.get(mobile_number=mobile_number)
        user.set_password(new_password)
        user.save()
        return Response({'message': 'Password reset successfully'}, 
                       status=status.HTTP_200_OK)
    except User.DoesNotExist:
        return Response({'error': 'User not found'}, 
                       status=status.HTTP_404_NOT_FOUND)


# ============ ADMIN LOGIN (Using admin_login table) ============

@api_view(['POST'])
@permission_classes([AllowAny])
def admin_login(request):
    """
    Admin login endpoint - Uses admin_login table
    """
    email = request.data.get('email')
    password = request.data.get('password')
    
    if not email or not password:
        return Response({
            'error': 'Email and password are required'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    # Check admin_login table
    try:
        admin = AdminLogin.objects.get(email=email, is_active=True)
        
        # Verify password (Django hashed password)
        if not check_password(password, admin.password):
            return Response({
                'error': 'Invalid credentials'
            }, status=status.HTTP_401_UNAUTHORIZED)
            
    except AdminLogin.DoesNotExist:
        return Response({
            'error': 'Invalid credentials or admin not found'
        }, status=status.HTTP_401_UNAUTHORIZED)
    
    # Generate JWT tokens (using admin's email as identifier)
    from rest_framework_simplejwt.tokens import RefreshToken
    
    # Create a dummy user object for JWT (or use actual User if exists)
    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        # Create a temporary user for JWT
        user = User(
            email=admin.email,
            name=admin.name,
            mobile_number=admin.mobile_number,
            is_staff=admin.is_staff,
            is_superuser=admin.is_superuser
        )
    
    refresh = RefreshToken.for_user(user)
    
    return Response({
        'status': 'success',
        'message': 'Admin login successful',
        'user': {
            'id': admin.id,
            'email': admin.email,
            'name': admin.name,
            'mobile_number': admin.mobile_number,
            'is_staff': admin.is_staff,
            'is_superuser': admin.is_superuser,
            'role': 'admin'
        },
        'access': str(refresh.access_token),
        'refresh': str(refresh),
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([AllowAny])
def vendor_login(request):
    """
    Vendor login endpoint - Uses professionals_professional table
    """
    email = request.data.get('email')
    password = request.data.get('password')
    
    if not email or not password:
        return Response({
            'error': 'Email and password are required'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    # Check vendor in professionals_professional table
    professional = Professional.objects.filter(email=email, is_active=True).first()
    
    if not professional:
        return Response({
            'error': 'Invalid credentials or vendor not found'
        }, status=status.HTTP_401_UNAUTHORIZED)
    
    # Check if password is set
    if not professional.password:
        return Response({
            'error': 'Password not set for this vendor. Please contact support.'
        }, status=status.HTTP_401_UNAUTHORIZED)
    
    # Verify password - Check both hashed and plain text
    password_valid = False
    
    # Check if it's a Django hashed password (starts with pbkdf2_sha256)
    if professional.password.startswith('pbkdf2_sha256'):
        # Use Django's check_password for hashed passwords
        from django.contrib.auth.hashers import check_password
        password_valid = check_password(password, professional.password)
    else:
        # For plain text passwords (development/testing)
        password_valid = (professional.password == password)
    
    if not password_valid:
        return Response({
            'error': 'Invalid credentials'
        }, status=status.HTTP_401_UNAUTHORIZED)
    
    # Generate JWT tokens
    from rest_framework_simplejwt.tokens import RefreshToken
    
    # Create a dummy user object for JWT
    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        # Create a temporary user for JWT
        user = User(
            email=professional.email,
            name=professional.name,
            mobile_number=professional.phone
        )
    
    refresh = RefreshToken.for_user(user)
    
    return Response({
        'status': 'success',
        'message': 'Vendor login successful',
        'user': {
            'id': professional.id,
            'email': professional.email,
            'name': professional.name,
            'mobile_number': professional.phone,
            'role': 'vendor'
        },
        'professional': {
            'id': professional.id,
            'name': professional.name,
            'specialty': professional.specialty,
            'governorate': professional.governorate.name if professional.governorate else None,
            'area': professional.area,
            'rating': float(professional.rating),
            'jobs_done': professional.jobs_done,
            'is_active': professional.is_active
        },
        'access': str(refresh.access_token),
        'refresh': str(refresh),
    }, status=status.HTTP_200_OK)
# ============ AUTO-DETECT LOGIN ============

@api_view(['POST'])
@permission_classes([AllowAny])
def login_with_role(request):
    """
    Unified login that determines role (admin/vendor) automatically
    """
    email = request.data.get('email')
    password = request.data.get('password')
    
    if not email or not password:
        return Response({
            'error': 'Email and password are required'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    # Try admin login first
    try:
        admin = AdminLogin.objects.get(email=email, is_active=True)
        if check_password(password, admin.password):
            # Admin login success
            return admin_login(request)
    except AdminLogin.DoesNotExist:
        pass
    
    # Try vendor login
    try:
        professional = Professional.objects.get(email=email, is_active=True)
        if check_password(password, professional.password):
            # Vendor login success
            return vendor_login(request)
    except Professional.DoesNotExist:
        pass
    
    return Response({
        'error': 'Invalid credentials or user not found'
    }, status=status.HTTP_401_UNAUTHORIZED)