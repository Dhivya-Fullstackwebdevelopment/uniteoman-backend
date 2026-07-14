from django.http import JsonResponse
from .models import Service, ServiceType

def service_list(request):

    location_id = request.GET.get("location_id")
    service_id = request.GET.get("service_id")

    services = Service.objects.filter(is_active=True)

    if location_id:
        services = services.filter(governorate_id=location_id)

    if service_id:
        services = services.filter(id=service_id)

    response = []

    for service in services:

        service_types = ServiceType.objects.filter(
            service_id=service.id,
            is_active=True
        )

        types = []

        for t in service_types:
            types.append({
                "id": t.id,
                "type_name": t.type_name,
                "price": str(t.price),
                "duration": t.duration,
                "description": t.description
            })

        response.append({
            "id": service.id,
            "name": service.name,
            "icon": request.build_absolute_uri(service.icon.url) if service.icon else "",
            "starting_price": str(service.starting_price),
            "description": service.description,
            "location": {
                "id": service.governorate.id,
                "name": service.governorate.name
            },
            "service_types": types
        })

    return JsonResponse({
        "status": "success",
        "message": "Services fetched successfully.",
        "count": len(response),
        "data": response
    })