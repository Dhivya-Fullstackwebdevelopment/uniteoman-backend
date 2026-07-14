from django.contrib import admin
from django.http import HttpResponse
from django.urls import path, include

def home(request):
    return HttpResponse("Welcome to Unite Oman API")

urlpatterns = [
    path('', home),
    path('admin/', admin.site.urls),
    path('api/locations/', include('locations.urls')),
    path("api/services/", include("services.urls")),
]