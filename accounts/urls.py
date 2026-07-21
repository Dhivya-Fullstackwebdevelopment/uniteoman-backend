from django.urls import path
from . import views

urlpatterns = [
    # OTP endpoints
    path('otp/send/', views.send_otp, name='send_otp'),
    path('otp/verify/', views.otp_verify, name='otp_verify'),
    
    # Auth endpoints
    path('register/', views.register_user, name='register'),
    path('login/', views.login_user, name='login'),
    path('logout/', views.logout_user, name='logout'),
    
    # Admin and Vendor specific logins
    path('login/admin/', views.admin_login, name='admin_login'),
    path('login/vendor/', views.vendor_login, name='vendor_login'),
    path('login/role/', views.login_with_role, name='login_with_role'),
    
    # Profile endpoints
    path('profile/', views.get_profile, name='profile'),
    path('profile/update/', views.update_profile, name='update_profile'),
    
    # Password reset
    path('password/forgot/', views.forgot_password, name='forgot_password'),
    path('password/reset/', views.reset_password, name='reset_password'),
]