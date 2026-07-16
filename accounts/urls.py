from django.urls import path
from . import views

urlpatterns = [
    # OTP endpoints
    path('otp/send/', views.send_otp, name='send_otp'),
    path('otp/verify/', views.verify_otp, name='verify_otp'),
    
    # Auth endpoints
    path('register/', views.register_user, name='register'),
    path('login/', views.login_user, name='login'),
    path('logout/', views.logout_user, name='logout'),
    
    # Profile endpoints
    path('profile/', views.get_profile, name='profile'),
    path('profile/update/', views.update_profile, name='update_profile'),
    
    # Password reset
    path('password/forgot/', views.forgot_password, name='forgot_password'),
    path('password/reset/', views.reset_password, name='reset_password'),
]