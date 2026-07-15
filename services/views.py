from django.db.models import Q, Case, When, Value, IntegerField
from django.http import JsonResponse
from .models import Service, ServiceType

def service_list(request):
    # Get all query parameters
    location_id = request.GET.get("location_id")
    service_id = request.GET.get("service_id")
    search_query = request.GET.get("search", "").strip()
    
    # Start with base queryset
    services = Service.objects.filter(is_active=True)
    
    # Apply filters
    if location_id:
        services = services.filter(governorate_id=location_id)
    
    if service_id:
        services = services.filter(id=service_id)
    
    # Apply search filter - search on main service name OR service_types
    if search_query:
        services = services.filter(
            Q(name__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(governorate__name__icontains=search_query) |
            Q(servicetype__type_name__icontains=search_query) |
            Q(servicetype__description__icontains=search_query)
        ).distinct()
    
    # Get unique service names with their first occurrence
    seen_names = set()
    unique_services = []
    
    for service in services:
        if service.name not in seen_names:
            seen_names.add(service.name)
            unique_services.append(service)
    
    # Sort by name
    unique_services.sort(key=lambda x: x.name)
    
    response = []
    
    for service in unique_services:
        service_types = ServiceType.objects.filter(
            service_id=service.id,
            is_active=True
        )
        
        # Apply search on service_types if search query exists
        if search_query:
            service_types = service_types.filter(
                Q(type_name__icontains=search_query) |
                Q(description__icontains=search_query)
            )
        
        types = []
        for t in service_types:
            types.append({
                "id": t.id,
                "type_name": t.type_name,
                "icon": request.build_absolute_uri(t.icon.url) if t.icon and hasattr(t.icon, 'url') else "",
                "price": str(t.price),
                "duration": t.duration,
                "description": t.description
            })
        
        # Only include services that have matching service_types when searching
        if search_query and not types:
            if not (search_query.lower() in service.name.lower() or 
                    search_query.lower() in service.description.lower()):
                continue
        
        # Get first available location for this service (or all if no location filter)
        if location_id:
            # If location filter is applied, show the current location
            location_data = {
                "id": service.governorate.id,
                "name": service.governorate.name
            }
        else:
            # Show all available locations
            locations = Service.objects.filter(
                name=service.name,
                is_active=True
            ).values('governorate__id', 'governorate__name').distinct()
            
            location_data = [
                {
                    "id": loc['governorate__id'],
                    "name": loc['governorate__name']
                }
                for loc in locations
            ]
        
        response.append({
            "id": service.id,
            "name": service.name,
            "icon": request.build_absolute_uri(service.icon.url) if service.icon and hasattr(service.icon, 'url') else "",
            "starting_price": str(service.starting_price),
            "description": service.description,
            "location": location_data if location_id else location_data,
            "service_types": types,
            "search_match": "main_category" if search_query and search_query.lower() in service.name.lower() else ("service_type" if search_query and types else None)
        })
    
    return JsonResponse({
        "status": "success",
        "message": "Services fetched successfully." + (f" Search results for: '{search_query}'" if search_query else ""),
        "count": len(response),
        "search_query": search_query if search_query else None,
        "filters": {
            "location_id": location_id if location_id else None,
            "service_id": service_id if service_id else None
        },
        "data": response
    })