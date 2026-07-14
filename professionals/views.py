import json
from datetime import datetime, timedelta, date as date_cls

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.db.models import Q

from services.models import Service, ServiceType
from .models import Professional, ProfessionalServiceType, Review, Booking


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

WORKING_HOURS = [
    (8, 0), (9, 0), (10, 0), (11, 0), (12, 0), (13, 0),
    (14, 0), (15, 0), (16, 0), (17, 0), (18, 0), (19, 0),
]


def serialize_professional_card(pro, service_type=None, request=None):
    """Short card used in list views (Image 1 / Image 2)."""
    price = None
    if service_type:
        offering = pro.offerings.filter(service_type=service_type, is_active=True).first()
        if offering:
            price = str(offering.price)

    next_available_label = None
    if pro.next_available_date and pro.next_available_time:
        today = timezone.localdate()
        if pro.next_available_date == today:
            day_label = "Today"
        elif pro.next_available_date == today + timedelta(days=1):
            day_label = "Tomorrow"
        else:
            day_label = pro.next_available_date.strftime("%a %d")
        next_available_label = f"{day_label} {pro.next_available_time.strftime('%I:%M%p').lstrip('0').lower()}"

    return {
        "id": pro.id,
        "name": pro.name,
        "specialty": pro.specialty,
        "avatar": request.build_absolute_uri(pro.avatar.url) if (pro.avatar and request) else "",
        "initial": pro.name[0].upper() if pro.name else "",
        "area": pro.area,
        "governorate_id": pro.governorate_id,
        "governorate": pro.governorate.name,
        "distance_km": float(pro.distance_km),
        "rating": float(pro.rating),
        "jobs_done": pro.jobs_done,
        "next_available": next_available_label,
        "is_available_today": pro.is_available_today,
        "price": price,
        "ai_match_score": pro.ai_match_score(service_type),
    }


def serialize_professional_detail(pro, request=None):
    offerings = pro.offerings.filter(is_active=True).select_related("service_type")
    services_offered = [
        {
            "service_type_id": o.service_type.id,
            "type_name": o.service_type.type_name,
            "price": str(o.price),
        }
        for o in offerings
    ]

    reviews = [
        {
            "id": r.id,
            "reviewer_name": r.reviewer_name,
            "rating": r.rating,
            "comment": r.comment,
            "created_at": r.created_at.strftime("%d %b"),
        }
        for r in pro.reviews.all()[:20]
    ]

    return {
        "id": pro.id,
        "name": pro.name,
        "specialty": pro.specialty,
        "area": pro.area,
        "governorate": pro.governorate.name,
        "avatar": request.build_absolute_uri(pro.avatar.url) if (pro.avatar and request) else "",
        "rating": float(pro.rating),
        "jobs_done": pro.jobs_done,
        "completion_rate": pro.completion_rate,
        "distance_km": float(pro.distance_km),
        "cancellations": pro.cancellations,
        "ai_match_score": pro.ai_match_score(),
        "ai_match_note": (
            f"Best match — highest specialisation score, {pro.cancellations} cancellations, "
            f"{'available today' if pro.is_available_today else 'not available today'}. "
            f"Historical avg arrival: {pro.avg_arrival_minutes} min."
        ),
        "services_offered": services_offered,
        "reviews_count": pro.reviews.count(),
        "reviews": reviews,
    }


def get_available_slots_for_date(pro, target_date):
    """Return list of {time, available} for a professional on a given date."""
    booked_times = set(
        Booking.objects.filter(
            professional=pro,
            booking_date=target_date,
            status__in=[Booking.STATUS_PENDING, Booking.STATUS_CONFIRMED],
        ).values_list("booking_time", flat=True)
    )

    now = timezone.localtime()
    slots = []
    for hour, minute in WORKING_HOURS:
        slot_time = datetime(target_date.year, target_date.month, target_date.day, hour, minute)
        is_past = target_date == now.date() and slot_time.time() <= now.time()
        is_booked = slot_time.time() in booked_times
        slots.append({
            "time": slot_time.strftime("%I:%M %p").lstrip("0"),
            "time_24h": slot_time.strftime("%H:%M"),
            "available": not is_past and not is_booked,
        })
    return slots


# ---------------------------------------------------------------------------
# GET /api/professionals/?service_id=&service_type_id=&location_id=&area=
#     &available_today=true&min_rating=4&price_max=30&price_min=0&sort=nearest
# ---------------------------------------------------------------------------

def professional_list(request):
    service_id = request.GET.get("service_id")
    service_type_id = request.GET.get("service_type_id")
    location_id = request.GET.get("location_id")
    area = request.GET.get("area")
    available_today = request.GET.get("available_today")
    top_rated = request.GET.get("top_rated")  # true -> rating >= 4.8
    nearest = request.GET.get("nearest")      # true -> just sorts, real "nearest(N)" count uses sort
    min_rating = request.GET.get("min_rating")
    price_min = request.GET.get("price_min")
    price_max = request.GET.get("price_max")
    sort = request.GET.get("sort")  # nearest | top_rated | lowest_price | best_match
    search = request.GET.get("search")

    # professionals = Professional.objects.filter(is_active=True)
    professionals = Professional.objects.filter(is_active=True).select_related("governorate")

    if location_id:
        professionals = professionals.filter(governorate_id=location_id)
    if area:
        professionals = professionals.filter(area__iexact=area)
    if search:
        professionals = professionals.filter(
            Q(name__icontains=search) | Q(specialty__icontains=search) | Q(area__icontains=search)
        )

    service_type = None
    if service_type_id:
        service_type = ServiceType.objects.filter(id=service_type_id).first()
        professionals = professionals.filter(offerings__service_type_id=service_type_id,
                                              offerings__is_active=True)
    elif service_id:
        professionals = professionals.filter(
            offerings__service_type__service_id=service_id,
            offerings__is_active=True,
        )

    professionals = professionals.distinct()

    # Counts BEFORE narrowing filters further (for filter chip counts)
    base_qs = professionals
    count_all = base_qs.count()
    count_available_today = base_qs.filter(next_available_date=timezone.localdate()).count()
    count_top_rated = base_qs.filter(rating__gte=4.8).count()
    count_nearest = base_qs.filter(distance_km__lte=2).count()

    if available_today in ("1", "true", "True"):
        professionals = professionals.filter(next_available_date=timezone.localdate())
    if top_rated in ("1", "true", "True"):
        professionals = professionals.filter(rating__gte=4.8)
    if min_rating:
        professionals = professionals.filter(rating__gte=float(min_rating))
    if price_min or price_max:
        if service_type_id:
            price_filter = Q(offerings__service_type_id=service_type_id)
            if price_min:
                price_filter &= Q(offerings__price__gte=price_min)
            if price_max:
                price_filter &= Q(offerings__price__lte=price_max)
            professionals = professionals.filter(price_filter).distinct()

    # Sorting
    if sort == "nearest" or nearest in ("1", "true", "True"):
        professionals = professionals.order_by("distance_km")
    elif sort == "top_rated":
        professionals = professionals.order_by("-rating", "-jobs_done")
    elif sort == "lowest_price" and service_type_id:
        professionals = professionals.order_by()  # price sort done after fetch (per-offering price)
    else:
        professionals = professionals.order_by("-rating")

    professionals = list(professionals)

    if sort == "lowest_price" and service_type_id:
        def price_key(p):
            o = p.offerings.filter(service_type_id=service_type_id, is_active=True).first()
            return float(o.price) if o else 999999
        professionals.sort(key=price_key)

    cards = [serialize_professional_card(p, service_type, request) for p in professionals]

    # AI Top Picks: top 3 by ai_match_score
    ranked = sorted(professionals, key=lambda p: p.ai_match_score(service_type), reverse=True)[:3]
    ai_top_picks = []
    for idx, p in enumerate(ranked):
        card = serialize_professional_card(p, service_type, request)
        card["is_best"] = idx == 0
        ai_top_picks.append(card)

    return JsonResponse({
        "status": "success",
        "message": "Professionals fetched successfully.",
        "search_label": search or (service_type.type_name if service_type else None),
        "counts": {
            "all": count_all,
            "available_today": count_available_today,
            "top_rated": count_top_rated,
            "nearest": count_nearest,
        },
        "count": len(cards),
        "ai_top_picks": ai_top_picks,
        "data": cards,
    })


# ---------------------------------------------------------------------------
# GET /api/professionals/<id>/
# ---------------------------------------------------------------------------

def professional_detail(request, pk):
    try:
        pro = Professional.objects.get(pk=pk, is_active=True)
    except Professional.DoesNotExist:
        return JsonResponse({"status": "error", "message": "Professional not found."}, status=404)

    return JsonResponse({
        "status": "success",
        "message": "Professional fetched successfully.",
        "data": serialize_professional_detail(pro, request),
    })


# ---------------------------------------------------------------------------
# GET /api/professionals/<id>/slots/?date=YYYY-MM-DD  (or ?days=4 to get next N days)
# ---------------------------------------------------------------------------

def professional_slots(request, pk):
    try:
        pro = Professional.objects.get(pk=pk, is_active=True)
    except Professional.DoesNotExist:
        return JsonResponse({"status": "error", "message": "Professional not found."}, status=404)

    date_param = request.GET.get("date")
    days_param = request.GET.get("days")

    if date_param:
        try:
            target_date = datetime.strptime(date_param, "%Y-%m-%d").date()
        except ValueError:
            return JsonResponse({"status": "error", "message": "Invalid date format, use YYYY-MM-DD."}, status=400)

        return JsonResponse({
            "status": "success",
            "message": "Slots fetched successfully.",
            "data": {
                "date": target_date.isoformat(),
                "slots": get_available_slots_for_date(pro, target_date),
            },
        })

    # Return next N days with slots (used to render the date picker, Image 4)
    days = int(days_param) if days_param else 6
    today = timezone.localdate()
    result = []
    for i in range(days):
        d = today + timedelta(days=i)
        result.append({
            "date": d.isoformat(),
            "day_label": d.strftime("%a"),
            "day_number": d.day,
            "month_label": d.strftime("%b"),
            "slots": get_available_slots_for_date(pro, d),
        })

    return JsonResponse({
        "status": "success",
        "message": "Slots fetched successfully.",
        "data": result,
    })


# ---------------------------------------------------------------------------
# GET /api/locations/<governorate_id>/areas/?service_id=  (Image 5 area chips)
# Simple hard-coded-per-professional areas derived from Professional.area values
# ---------------------------------------------------------------------------

def area_list(request):
    governorate_id = request.GET.get("location_id")
    qs = Professional.objects.filter(is_active=True)
    if governorate_id:
        qs = qs.filter(governorate_id=governorate_id)
    areas = sorted(set(qs.exclude(area="").values_list("area", flat=True)))
    return JsonResponse({
        "status": "success",
        "message": "Areas fetched successfully.",
        "count": len(areas),
        "data": areas,
    })


# ---------------------------------------------------------------------------
# POST /api/bookings/create/
# Body (JSON):
# {
#   "professional_id": 1,
#   "service_type_id": 4,
#   "booking_date": "2026-07-09",
#   "booking_time": "10:00",
#   "user_name": "Ahmed",
#   "user_email": "ahmed@example.com",
#   "user_mobile": "+968 9234 5678",
#   "area": "Qurum",
#   "villa_apartment_no": "Villa 12",
#   "street_name": "Al Noor Street",
#   "building_floor": "Ground Floor",
#   "nearest_landmark": "Near Al Qurum Park",
#   "payment_method": "bank_of_muscat_card",
#   "card_last4": "4521",
#   "save_card": true
# }
# ---------------------------------------------------------------------------

@csrf_exempt
def booking_create(request):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "POST required."}, status=405)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"status": "error", "message": "Invalid JSON body."}, status=400)

    required_fields = [
        "professional_id", "service_type_id", "booking_date", "booking_time",
        "user_name", "user_email", "user_mobile",
        "area", "villa_apartment_no", "street_name",
    ]
    missing = [f for f in required_fields if not payload.get(f)]
    if missing:
        return JsonResponse({
            "status": "error",
            "message": f"Missing required fields: {', '.join(missing)}",
        }, status=400)

    try:
        pro = Professional.objects.get(pk=payload["professional_id"], is_active=True)
    except Professional.DoesNotExist:
        return JsonResponse({"status": "error", "message": "Professional not found."}, status=404)

    try:
        service_type = ServiceType.objects.get(pk=payload["service_type_id"], is_active=True)
    except ServiceType.DoesNotExist:
        return JsonResponse({"status": "error", "message": "Service type not found."}, status=404)

    offering = ProfessionalServiceType.objects.filter(
        professional=pro, service_type=service_type, is_active=True
    ).first()
    service_fee = offering.price if offering else service_type.price

    try:
        booking_date = datetime.strptime(payload["booking_date"], "%Y-%m-%d").date()
        booking_time = datetime.strptime(payload["booking_time"], "%H:%M").time()
    except ValueError:
        return JsonResponse({
            "status": "error",
            "message": "Invalid date/time format. Use booking_date=YYYY-MM-DD, booking_time=HH:MM.",
        }, status=400)

    # Prevent double-booking the same slot
    clash = Booking.objects.filter(
        professional=pro,
        booking_date=booking_date,
        booking_time=booking_time,
        status__in=[Booking.STATUS_PENDING, Booking.STATUS_CONFIRMED],
    ).exists()
    if clash:
        return JsonResponse({"status": "error", "message": "This time slot is no longer available."}, status=409)

    booking = Booking(
        user_name=payload["user_name"],
        user_email=payload["user_email"],
        user_mobile=payload["user_mobile"],
        professional=pro,
        service_type=service_type,
        booking_date=booking_date,
        booking_time=booking_time,
        area=payload["area"],
        villa_apartment_no=payload["villa_apartment_no"],
        street_name=payload["street_name"],
        building_floor=payload.get("building_floor", ""),
        nearest_landmark=payload.get("nearest_landmark", ""),
        latitude=payload.get("latitude"),
        longitude=payload.get("longitude"),
        payment_method=payload.get("payment_method", "cash_on_completion"),
        card_last4=payload.get("card_last4", ""),
        save_card=bool(payload.get("save_card", False)),
        service_fee=service_fee,
    )
    booking.calculate_pricing()
    booking.save()

    return JsonResponse({
        "status": "success",
        "message": "Booking created successfully.",
        "data": serialize_booking(booking, request),
    }, status=201)


def serialize_booking(booking, request=None):
    return {
        "id": booking.id,
        "booking_code": booking.booking_code,
        "status": booking.status,
        "user": {
            "name": booking.user_name,
            "email": booking.user_email,
            "mobile": booking.user_mobile,
        },
        "professional": {
            "id": booking.professional.id,
            "name": booking.professional.name,
            "specialty": booking.professional.specialty,
            "rating": float(booking.professional.rating),
            "jobs_done": booking.professional.jobs_done,
            "phone": booking.professional.phone,
        },
        "service": {
            "service_type_id": booking.service_type.id,
            "type_name": booking.service_type.type_name,
            "duration": booking.service_type.duration,
        },
        "date": booking.booking_date.isoformat(),
        "time": booking.booking_time.strftime("%I:%M %p").lstrip("0"),
        "address": {
            "area": booking.area,
            "villa_apartment_no": booking.villa_apartment_no,
            "street_name": booking.street_name,
            "building_floor": booking.building_floor,
            "nearest_landmark": booking.nearest_landmark,
        },
        "payment": {
            "method": booking.get_payment_method_display(),
            "card_last4": booking.card_last4,
        },
        "pricing": {
            "service_fee": str(booking.service_fee),
            "platform_fee": str(booking.platform_fee),
            "vat_amount": str(booking.vat_amount),
            "total_amount": str(booking.total_amount),
        },
        "created_at": booking.created_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# GET /api/bookings/<id>/
# ---------------------------------------------------------------------------

def booking_detail(request, pk):
    try:
        booking = Booking.objects.get(pk=pk)
    except Booking.DoesNotExist:
        return JsonResponse({"status": "error", "message": "Booking not found."}, status=404)

    return JsonResponse({
        "status": "success",
        "message": "Booking fetched successfully.",
        "data": serialize_booking(booking, request),
    })


# ---------------------------------------------------------------------------
# POST /api/bookings/<id>/confirm/
# Marks booking confirmed (this is the final "Confirm & Pay" step, Image 6 -> 7)
# ---------------------------------------------------------------------------

@csrf_exempt
def booking_confirm(request, pk):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "POST required."}, status=405)

    try:
        booking = Booking.objects.get(pk=pk)
    except Booking.DoesNotExist:
        return JsonResponse({"status": "error", "message": "Booking not found."}, status=404)

    if booking.status != Booking.STATUS_PENDING:
        return JsonResponse({
            "status": "error",
            "message": f"Booking cannot be confirmed from status '{booking.status}'.",
        }, status=400)

    booking.status = Booking.STATUS_CONFIRMED
    booking.save(update_fields=["status", "updated_at"])

    return JsonResponse({
        "status": "success",
        "message": f"{booking.professional.name} is confirmed. SMS + WhatsApp sent to {booking.user_mobile}.",
        "data": serialize_booking(booking, request),
    })


# ---------------------------------------------------------------------------
# POST /api/bookings/<id>/cancel/
# ---------------------------------------------------------------------------

@csrf_exempt
def booking_cancel(request, pk):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "POST required."}, status=405)

    try:
        booking = Booking.objects.get(pk=pk)
    except Booking.DoesNotExist:
        return JsonResponse({"status": "error", "message": "Booking not found."}, status=404)

    if booking.status in (Booking.STATUS_CANCELLED, Booking.STATUS_COMPLETED):
        return JsonResponse({
            "status": "error",
            "message": f"Booking already {booking.status}.",
        }, status=400)

    booking.status = Booking.STATUS_CANCELLED
    booking.save(update_fields=["status", "updated_at"])

    return JsonResponse({
        "status": "success",
        "message": "Booking cancelled.",
        "data": serialize_booking(booking, request),
    })