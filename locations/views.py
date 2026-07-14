from django.http import JsonResponse
from .models import Governorate

def governorate_list(request):
    data = Governorate.objects.filter(is_active=True)

    response = []

    for item in data:
        response.append({
            "id": item.id,
            "name": item.name
        })

    return JsonResponse(response, safe=False)