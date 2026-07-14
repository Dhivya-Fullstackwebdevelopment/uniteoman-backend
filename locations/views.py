from django.http import JsonResponse
from .models import Governorate

def governorate_list(request):
    data = Governorate.objects.filter(is_active=True)

    locations = []

    for item in data:
        locations.append({
            "id": item.id,
            "name": item.name
        })

    return JsonResponse({
        "status": "success",
        "message": "Locations fetched successfully.",
        "count": len(locations),
        "data": locations
    }, status=200)