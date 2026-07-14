from django.urls import path
from .views import governorate_list

urlpatterns = [
    path('', governorate_list),
]