import io
import json
from django.db.models import Q
from django.http import JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from .models import Service, ServiceType, Booking, Review

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
# 2. BOOKINGS AGGREGATION FILTER (Upcoming, Ongoing, Completed, Cancelled)
@login_required
def my_bookings(request):
    status_filter = request.GET.get('filter', 'upcoming').lower()
    queryset = Booking.objects.filter(user=request.user)
    
    if status_filter == 'upcoming':
        queryset = queryset.filter(status__in=['SCHEDULED', 'EN_ROUTE'])
    elif status_filter == 'ongoing':
        queryset = queryset.filter(status__in=['ARRIVED', 'IN_PROGRESS'])
    elif status_filter == 'completed':
        queryset = queryset.filter(status='COMPLETED')
    elif status_filter == 'cancelled':
        queryset = queryset.filter(status='CANCELLED')

    queryset = queryset.order_by('-scheduled_at')
    
    data = []
    for b in queryset:
        data.append({
            "id": b.id,
            "booking_number": b.booking_number,
            "service_name": b.service_type.type_name,
            "professional_name": b.professional.name,
            "date_time": b.scheduled_at.strftime('%a %d %b · %I:%M %p'),
            "location": b.location_name,
            "price": str(b.total_paid),
            "status": b.get_status_display()
        })
    return JsonResponse({"status": "success", "data": data})


# 3. LIVE MAP PROGRESS TRACKER
@login_required
def track_booking(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id, user=request.user)
    return JsonResponse({
        "status": "success",
        "booking_number": booking.booking_number,
        "status_code": booking.status,
        "eta_minutes": 12,
        "distance_away_km": 1.2,
        "arriving_at": "10:12 AM"
    })


# 4. REVIEW MATRIX RATING SYSTEM
@login_required
def rate_booking(request, booking_id):
    if request.method == 'POST':
        booking = get_object_or_404(Booking, id=booking_id, user=request.user)
        body = json.loads(request.body)
        
        review, created = Review.objects.update_or_create(
            booking=booking,
            defaults={
                'rating': int(body.get('rating', 5)),
                'review_text': body.get('review_text', ''),
                'tags': body.get('tags', [])
            }
        )
        return JsonResponse({"status": "success", "message": "Review captured."})


# 5. ORDER INVOICE DATA RECEIPT
@login_required
def booking_receipt(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id, user=request.user)
    return JsonResponse({
        "status": "success",
        "data": {
            "booking_number": booking.booking_number,
            "service_fee": str(booking.service_fee),
            "platform_fee": str(booking.platform_fee),
            "vat": str(booking.vat),
            "total_paid": str(booking.total_paid)
        }
    })


# 6. INVOICE PRINT DOWNLOAD DOCUMENT (PDF)
@login_required
def download_receipt_pdf(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id, user=request.user)
    
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    story = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], textColor=colors.HexColor('#9C27B0'))
    
    story.append(Paragraph(f"UniteOman Invoice Summary #{booking.booking_number}", title_style))
    story.append(Spacer(1, 20))
    
    invoice_data = [
        ["Service Description", booking.service_type.type_name],
        ["Assigned Professional", booking.professional.name],
        ["Base Service Rate", f"OMR {booking.service_fee}"],
        ["Platform Service Charge", f"OMR {booking.platform_fee}"],
        ["VAT Allocation", f"OMR {booking.vat}"],
        ["Total Settled In Full", f"OMR {booking.total_paid}"]
    ]
    
    t = Table(invoice_data, colWidths=[200, 200])
    t.setStyle(TableStyle([
        ('LINEBELOW', (0,0), (-1,-1), 0.5, colors.lightgrey),
        ('TEXTCOLOR', (0,-1), (-1,-1), colors.HexColor('#9C27B0')),
        ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold')
    ]))
    
    story.append(t)
    doc.build(story)
    
    buffer.seek(0)
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="Invoice_{booking.booking_number}.pdf"'
    return response