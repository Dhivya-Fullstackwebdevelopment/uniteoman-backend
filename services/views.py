from django.http import JsonResponse
from .models import Service


def service_list(request):

    location_id = request.GET.get("location_id")
    service_id = request.GET.get("service_id")

    services = Service.objects.filter(is_active=True)

    # Filter by location
    if location_id:
        services = services.filter(governorate_id=location_id)

    # Filter by service
    if service_id:
        services = services.filter(id=service_id)

    response = []

    for service in services:
        response.append({
            "id": service.id,
            "name": service.name,
            "icon": service.icon.url if service.icon else "",
            "starting_price": str(service.starting_price),
            "location": {
                "id": service.governorate.id,
                "name": service.governorate.name
            }
        })

    return JsonResponse({
        "status": "success",
        "message": "Services fetched successfully.",
        "count": len(response),
        "data": response
    })