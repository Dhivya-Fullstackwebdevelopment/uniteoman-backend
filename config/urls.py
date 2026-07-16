from django.contrib import admin
from django.http import HttpResponse
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

def home(request):
    return HttpResponse("Welcome to Unite Oman API")

urlpatterns = [
    path('', home),
    path('admin/', admin.site.urls),
    path('api/locations/', include('locations.urls')),
    path("api/services/", include("services.urls")),
    path("api/professionals/", include("professionals.urls")),
    path('api/auth/', include('accounts.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)