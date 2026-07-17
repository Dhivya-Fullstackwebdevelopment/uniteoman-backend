from django.contrib.auth.backends import BaseBackend
from .models import User

class MobileNumberBackend(BaseBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        # Try to get the user by mobile number
        try:
            user = User.objects.get(mobile_number=username)
            if user.check_password(password):
                return user
        except User.DoesNotExist:
            return None
        return None

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None