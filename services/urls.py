from django.urls import path
from .views import service_list

urlpatterns = [
    path("", service_list),
]