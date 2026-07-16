import io
import json
from django.db.models import Q
from django.http import JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
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

# 2. BOOKINGS AGGREGATION FILTER (Upcoming, Ongoing, Completed, Cancelled)
# TEMPORARILY REMOVED @login_required FOR TESTING
# @login_required
def my_bookings(request):
    """
    Get bookings for the current user with status filtering
    Filter options: upcoming, ongoing, completed, cancelled
    """
    # For testing without login - get all bookings or filter by user_id from query param
    # If you want to test with a specific user, pass ?user_id=1
    user_id = request.GET.get('user_id')
    
    if user_id:
        queryset = Booking.objects.filter(user_id=user_id)
    else:
        # If no user_id provided, get all bookings (for testing)
        # In production with @login_required, this will use request.user
        if request.user.is_authenticated:
            queryset = Booking.objects.filter(user=request.user)
        else:
            # For testing without login, return all bookings
            queryset = Booking.objects.all()
    
    status_filter = request.GET.get('filter', 'upcoming').lower()
    
    if status_filter == 'upcoming':
        queryset = queryset.filter(status__in=['SCHEDULED', 'EN_ROUTE', 'confirmed', 'pending'])
    elif status_filter == 'ongoing':
        queryset = queryset.filter(status__in=['ARRIVED', 'IN_PROGRESS'])
    elif status_filter == 'completed':
        queryset = queryset.filter(status='COMPLETED')
    elif status_filter == 'cancelled':
        queryset = queryset.filter(status='CANCELLED')

    queryset = queryset.order_by('-scheduled_at')
    
    data = []
    for booking in queryset:
        # Handle case where professional might be None
        professional_name = booking.professional.name if booking.professional else "Not Assigned"
        
        data.append({
            "id": booking.id,
            "booking_number": booking.booking_number,
            "service_name": booking.service_type.type_name if booking.service_type else "Unknown Service",
            "professional_name": professional_name,
            "date_time": booking.scheduled_at.strftime('%a %d %b · %I:%M %p') if booking.scheduled_at else "Not Scheduled",
            "location": booking.location_name,
            "address": booking.address,
            "price": str(booking.total_paid),
            "status": booking.get_status_display() if hasattr(booking, 'get_status_display') else booking.status,
            "status_code": booking.status,
            "payment_method": booking.payment_method,
            "duration_minutes": booking.duration_minutes
        })
    
    return JsonResponse({
        "status": "success", 
        "filter_applied": status_filter,
        "count": len(data),
        "data": data
    })

# 3. LIVE MAP PROGRESS TRACKER
# TEMPORARILY REMOVED @login_required FOR TESTING
# @login_required
def track_booking(request, booking_id):
    """
    Track a specific booking by ID
    """
    # For testing without login
    if request.user.is_authenticated:
        booking = get_object_or_404(Booking, id=booking_id, user=request.user)
    else:
        # Allow any booking to be tracked for testing
        booking = get_object_or_404(Booking, id=booking_id)
    
    # Calculate ETA based on booking time (mock logic)
    from datetime import datetime, timedelta
    current_time = datetime.now()
    
    if booking.scheduled_at:
        time_diff = (booking.scheduled_at - current_time).total_seconds() / 60
        eta_minutes = max(5, int(time_diff)) if time_diff > 0 else 12
    else:
        eta_minutes = 12
    
    return JsonResponse({
        "status": "success",
        "booking_id": booking.id,
        "booking_number": booking.booking_number,
        "status_code": booking.status,
        "status_display": booking.get_status_display() if hasattr(booking, 'get_status_display') else booking.status,
        "eta_minutes": eta_minutes,
        "distance_away_km": 1.2,
        "arriving_at": (booking.scheduled_at + timedelta(minutes=12)).strftime('%I:%M %p') if booking.scheduled_at else "10:12 AM",
        "service_type": booking.service_type.type_name if booking.service_type else "Unknown",
        "professional": booking.professional.name if booking.professional else "Not Assigned",
        "location": booking.location_name,
        "address": booking.address
    })

# 4. REVIEW MATRIX RATING SYSTEM
@csrf_exempt
# TEMPORARILY REMOVED @login_required FOR TESTING
# @login_required
def rate_booking(request, booking_id):
    """
    Submit a review for a booking
    """
    if request.method != 'POST':
        return JsonResponse({
            "status": "error", 
            "message": "POST method required"
        }, status=405)
    
    try:
        # For testing without login
        if request.user.is_authenticated:
            booking = get_object_or_404(Booking, id=booking_id, user=request.user)
        else:
            # Allow any booking to be rated for testing
            booking = get_object_or_404(Booking, id=booking_id)
        
        body = json.loads(request.body)
        
        rating = int(body.get('rating', 5))
        if rating < 1 or rating > 5:
            return JsonResponse({
                "status": "error", 
                "message": "Rating must be between 1 and 5"
            }, status=400)
        
        review, created = Review.objects.update_or_create(
            booking=booking,
            defaults={
                'rating': rating,
                'review_text': body.get('review_text', ''),
                'tags': body.get('tags', [])
            }
        )
        
        return JsonResponse({
            "status": "success", 
            "message": "Review captured successfully.",
            "review_id": review.id,
            "created": created,
            "data": {
                "booking_id": booking.id,
                "booking_number": booking.booking_number,
                "rating": review.rating,
                "review_text": review.review_text,
                "tags": review.tags
            }
        })
    
    except json.JSONDecodeError:
        return JsonResponse({
            "status": "error", 
            "message": "Invalid JSON body"
        }, status=400)
    except Exception as e:
        return JsonResponse({
            "status": "error", 
            "message": str(e)
        }, status=400)

# 5. ORDER INVOICE DATA RECEIPT
# TEMPORARILY REMOVED @login_required FOR TESTING
# @login_required
def booking_receipt(request, booking_id):
    """
    Get receipt data for a specific booking
    """
    # For testing without login
    if request.user.is_authenticated:
        booking = get_object_or_404(Booking, id=booking_id, user=request.user)
    else:
        # Allow any booking for testing
        booking = get_object_or_404(Booking, id=booking_id)
    
    return JsonResponse({
        "status": "success",
        "data": {
            "booking_id": booking.id,
            "booking_number": booking.booking_number,
            "service_name": booking.service_type.type_name if booking.service_type else "Unknown Service",
            "professional": booking.professional.name if booking.professional else "Not Assigned",
            "service_fee": str(booking.service_fee),
            "platform_fee": str(booking.platform_fee),
            "vat": str(booking.vat),
            "total_paid": str(booking.total_paid),
            "payment_method": booking.payment_method,
            "booking_date": booking.created_at.strftime('%Y-%m-%d %H:%M') if booking.created_at else None,
            "scheduled_at": booking.scheduled_at.strftime('%Y-%m-%d %H:%M') if booking.scheduled_at else None,
            "status": booking.status,
            "location": booking.location_name,
            "address": booking.address,
            "duration_minutes": booking.duration_minutes
        }
    })

# 6. INVOICE PRINT DOWNLOAD DOCUMENT (PDF)
# TEMPORARILY REMOVED @login_required FOR TESTING
# @login_required
def download_receipt_pdf(request, booking_id):
    """
    Download receipt as PDF
    """
    # For testing without login
    if request.user.is_authenticated:
        booking = get_object_or_404(Booking, id=booking_id, user=request.user)
    else:
        # Allow any booking for testing
        booking = get_object_or_404(Booking, id=booking_id)
    
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors
        from reportlab.lib.units import inch
    except ImportError:
        return JsonResponse({
            "status": "error",
            "message": "reportlab library not installed. Run: pip install reportlab"
        }, status=500)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    story = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'Title', 
        parent=styles['Heading1'], 
        textColor=colors.HexColor('#9C27B0'),
        fontSize=24,
        spaceAfter=30
    )
    
    # Add header
    story.append(Paragraph(f"UniteOman Invoice", title_style))
    story.append(Paragraph(f"Booking #{booking.booking_number}", styles['Heading2']))
    story.append(Spacer(1, 20))
    
    # Booking details
    booking_data = [
        ["Booking Number:", booking.booking_number],
        ["Date:", booking.created_at.strftime('%Y-%m-%d %H:%M') if booking.created_at else "N/A"],
        ["Service:", booking.service_type.type_name if booking.service_type else "Unknown"],
        ["Professional:", booking.professional.name if booking.professional else "Not Assigned"],
        ["Location:", booking.location_name],
        ["Address:", booking.address],
        ["Status:", booking.get_status_display() if hasattr(booking, 'get_status_display') else booking.status],
    ]
    
    t1 = Table(booking_data, colWidths=[150, 300])
    t1.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
    ]))
    
    story.append(t1)
    story.append(Spacer(1, 20))
    
    # Financial summary
    story.append(Paragraph("Payment Summary", styles['Heading3']))
    story.append(Spacer(1, 10))
    
    invoice_data = [
        ["Description", "Amount (OMR)"],
        ["Service Fee", f"{booking.service_fee}"],
        ["Platform Fee", f"{booking.platform_fee}"],
        ["VAT (9%)", f"{booking.vat}"],
        ["Total Paid", f"{booking.total_paid}"]
    ]
    
    t2 = Table(invoice_data, colWidths=[200, 150])
    t2.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#9C27B0')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 12),
        ('ALIGN', (1,0), (1,-1), 'RIGHT'),
        ('LINEBELOW', (0,0), (-1,0), 1, colors.black),
        ('LINEBELOW', (0,-1), (-1,-1), 2, colors.HexColor('#9C27B0')),
        ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
        ('TEXTCOLOR', (0,-1), (-1,-1), colors.HexColor('#9C27B0')),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
    ]))
    
    story.append(t2)
    story.append(Spacer(1, 20))
    
    # Payment method
    story.append(Paragraph(f"Payment Method: {booking.payment_method}", styles['Normal']))
    story.append(Spacer(1, 10))
    
    # Footer
    story.append(Paragraph("Thank you for using UniteOman!", styles['Normal']))
    
    doc.build(story)
    
    buffer.seek(0)
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="Invoice_{booking.booking_number}.pdf"'
    return response