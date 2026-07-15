from django.http import JsonResponse
from django.db.models import Q
from .models import Governorate

def governorate_list(request):
    # Get search parameter from request
    search_query = request.GET.get('search', '').strip()
    
    # Start with base queryset
    queryset = Governorate.objects.filter(is_active=True)
    
    # Apply search filter if search query is provided
    if search_query:
        queryset = queryset.filter(
            Q(name__icontains=search_query)  # Case-insensitive partial match
        )
    
    locations = []
    for item in queryset:
        locations.append({
            "id": item.id,
            "name": item.name
        })
    
    return JsonResponse({
        "status": "success",
        "message": "Locations fetched successfully." + (f" Search results for: '{search_query}'" if search_query else ""),
        "count": len(locations),
        "search_query": search_query if search_query else None,
        "data": locations
    }, status=200)