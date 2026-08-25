from datetime import datetime, timedelta, date as date_cls
import json
import random
import string
from django.db.models import Q, Avg, Count
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from services.models import Service, ServiceType
from .models import Professional, ProfessionalServiceType, Review, Booking
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.shortcuts import get_object_or_404 
from django.db import transaction
from django.utils.timezone import make_aware, is_naive
from django.contrib.auth import get_user_model

import csv
from django.http import HttpResponse
from django.db.models import Q
from django.utils import timezone
from .models import Booking, Professional
from django.core.paginator import Paginator
from statistics import mean
from .models import (
    Professional,
    ProfessionalServiceType,
    Review,
    Booking,
    ProfessionalServiceArea,
    ProfessionalArea,
)
from decimal import Decimal, InvalidOperation
from services.models import Service, ServiceType
from .models import Professional, Booking, Review, ReviewPhoto
from django.shortcuts import get_object_or_404
from professionals.models import Professional, Booking, Review, ProfessionalServiceType
from django.db.models.functions import TruncDate, TruncDay, TruncMonth
from django.db.models import (
    Avg, Count, Sum, Q, DecimalField, FloatField
)
from collections import defaultdict
from decimal import Decimal
from datetime import date, timedelta
from .models import VendorBankAccount, PayoutRequest
from django.db.models import Sum, Count, Q
from professionals.models import Professional, Booking
from decimal import Decimal, ROUND_DOWN

User = get_user_model()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

WORKING_HOURS = [
    (8, 0), (9, 0), (10, 0), (11, 0), (12, 0), (13, 0),
    (14, 0), (15, 0), (16, 0), (17, 0), (18, 0), (19, 0),
]


def serialize_professional_card(pro, service_type=None, request=None, service_type_ids=None):
    """Short card used in list views (Image 1 / Image 2)."""
    price = None
    matched_service_type_id = None

    if service_type:
        # A single specific service_type filter was applied -> show that exact price
        offering = pro.offerings.filter(service_type=service_type, is_active=True).first()
        if offering:
            price = str(offering.price)
            matched_service_type_id = offering.service_type_id
    elif service_type_ids:
        # Multiple service_type ids were selected (checkboxes) -> show the cheapest
        # matching offering among the selected ones, and which service_type it belongs to
        offering = pro.offerings.filter(
            service_type_id__in=service_type_ids, is_active=True
        ).order_by("price").first()
        if offering:
            price = str(offering.price)
            matched_service_type_id = offering.service_type_id
    else:
        # No service_type filter applied -> fall back to the professional's
        # cheapest active offering so price is never left null unnecessarily
        cheapest = pro.offerings.filter(is_active=True).order_by("price").first()
        if cheapest:
            price = str(cheapest.price)
            matched_service_type_id = cheapest.service_type_id

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
        "service_type_id": matched_service_type_id,
        "price": price,
        "ai_match_score": pro.ai_match_score(service_type),
    }


def build_ai_match_note(pro):
    """Short per-card AI note, e.g. used inside ai_top_picks cards."""
    return (
        f"Highest match score, {pro.cancellations} cancellations, "
        f"{'available today' if pro.is_available_today else 'not available today'}. "
        f"Avg wait: {pro.avg_arrival_minutes} min."
    )


def build_ai_summary_note(pro):
    """Bottom banner note shown under the AI Top Picks panel."""
    first_name = pro.name.split()[0] if pro.name else "This professional"
    return (
        f"{first_name} is ideal — highest match score, "
        f"{pro.cancellations} cancellations, "
        f"{'available today' if pro.is_available_today else 'not available today'}. "
        f"Avg wait: {pro.avg_arrival_minutes} min."
    )


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
# GET /api/service-types/?service_id=
# ---------------------------------------------------------------------------

def service_type_list(request):
    service_id = request.GET.get("service_id")
    qs = ServiceType.objects.filter(is_active=True)
    if service_id:
        qs = qs.filter(service_id=service_id)

    data = [
        {"id": st.id, "type_name": st.type_name, "price": str(st.price)}
        for st in qs.order_by("type_name")
    ]
    return JsonResponse({
        "status": "success",
        "message": "Service types fetched successfully.",
        "count": len(data),
        "data": data,
    })

# ---------------------------------------------------------------------------
# GET /api/professionals/
# ---------------------------------------------------------------------------

def professional_list(request):
    service_id = request.GET.get("service_id")
    service_type_id = request.GET.get("service_type_id")
    location_id = request.GET.get("location_id")
    area = request.GET.get("area")
    min_rating_param = request.GET.get("rating")
    price_min = request.GET.get("price_min")
    price_max = request.GET.get("price_max")
    search = request.GET.get("search")

    # Unified chip selection and sorting rule parameter
    sort = request.GET.get("sort", "").lower()

    professionals = Professional.objects.filter(is_active=True).select_related("governorate")

    if location_id:
        professionals = professionals.filter(governorate_id=location_id)
    if area:
        professionals = professionals.filter(area__iexact=area)
    if search:
        professionals = professionals.filter(
            Q(name__icontains=search) | Q(specialty__icontains=search) | Q(area__icontains=search)
        )

    # service_type_id can be a single id or a comma-separated list of ids
    service_type_ids = []
    if service_type_id:
        service_type_ids = [int(x) for x in service_type_id.split(",") if x.strip().isdigit()]

    service_type = None
    if service_type_ids:
        if len(service_type_ids) == 1:
            service_type = ServiceType.objects.filter(id=service_type_ids[0]).first()
        professionals = professionals.filter(
            offerings__service_type_id__in=service_type_ids,
            offerings__is_active=True,
        )
    elif service_id:
        professionals = professionals.filter(
            offerings__service_type__service_id=service_id,
            offerings__is_active=True,
        )

    professionals = professionals.distinct()

    base_qs = professionals
    count_all = base_qs.count()
    count_available_today = base_qs.filter(next_available_date=timezone.localdate()).count()
    count_top_rated = base_qs.filter(rating__gte=4.5).count()
    count_nearest = base_qs.filter(distance_km__lte=5.0).count()

    if sort == "available_today":
        professionals = professionals.filter(next_available_date=timezone.localdate())
    elif sort == "top_rated":
        professionals = professionals.filter(rating__gte=4.5)
    elif sort == "nearest":
        professionals = professionals.filter(distance_km__lte=5.0)

    if min_rating_param:
        try:
            professionals = professionals.filter(rating=float(min_rating_param))
        except ValueError:
            pass

    if price_min or price_max:
        price_filter = Q(offerings__is_active=True)
        if service_type_ids:
            price_filter &= Q(offerings__service_type_id__in=service_type_ids)
        if price_min:
            try:
                price_filter &= Q(offerings__price__gte=float(price_min))
            except ValueError:
                pass
        if price_max:
            try:
                price_filter &= Q(offerings__price__lte=float(price_max))
            except ValueError:
                pass
        professionals = professionals.filter(price_filter).distinct()

    professionals = list(professionals)

    if sort == "nearest":
        professionals.sort(key=lambda p: float(p.distance_km))
    elif sort == "top_rated":
        professionals.sort(key=lambda p: (-float(p.rating), -p.jobs_done))
    elif sort == "lowest_price":
        def price_key(p):
            if service_type_ids:
                o = p.offerings.filter(
                    service_type_id__in=service_type_ids, is_active=True
                ).order_by("price").first()
            else:
                o = p.offerings.filter(is_active=True).order_by("price").first()
            return float(o.price) if o else 999999
        professionals.sort(key=price_key)
    else:
        professionals.sort(key=lambda p: -float(p.rating))

    cards = [
        serialize_professional_card(p, service_type, request, service_type_ids)
        for p in professionals
    ]

    ranked = sorted(professionals, key=lambda p: p.ai_match_score(service_type), reverse=True)[:3]
    ai_top_picks = []
    for idx, p in enumerate(ranked):
        card = serialize_professional_card(p, service_type, request, service_type_ids)
        card["is_best"] = idx == 0
        card["ai_match_note"] = build_ai_match_note(p)
        ai_top_picks.append(card)

    ai_summary_note = build_ai_summary_note(ranked[0]) if ranked else None

    response = {
        "status": "success",
        "message": "Professionals fetched successfully.",
        "search_label": search or None,
        "counts": {
            "all": count_all,
            "available_today": count_available_today,
            "top_rated": count_top_rated,
            "nearest": count_nearest,
        },
        "count": len(cards),
        "ai_top_picks": ai_top_picks,
        "ai_summary_note": ai_summary_note,
        "data": cards,
    }

    if request.GET.get("debug") == "1":
        all_offerings = []
        if service_type_ids:
            all_offerings = list(
                ProfessionalServiceType.objects.filter(
                    service_type_id__in=service_type_ids
                ).values("professional_id", "service_type_id", "is_active")
            )
        elif service_id:
            all_offerings = list(
                ProfessionalServiceType.objects.filter(
                    service_type__service_id=service_id
                ).values("professional_id", "service_type_id", "is_active")
            )

        pro_ids_in_offerings = {o["professional_id"] for o in all_offerings}
        pro_active_map = dict(
            Professional.objects.filter(id__in=pro_ids_in_offerings).values_list("id", "is_active")
        )

        excluded = []
        for o in all_offerings:
            pid = o["professional_id"]
            pro_is_active = pro_active_map.get(pid)
            if pro_is_active is False:
                excluded.append({**o, "reason": "professional.is_active = False"})
            elif not o["is_active"]:
                excluded.append({**o, "reason": "offering.is_active = False"})
            elif pro_is_active is None:
                excluded.append({**o, "reason": "professional not found (deleted?)"})

        response["debug"] = {
            "filters_received": {
                "service_id": service_id,
                "service_type_id_raw": service_type_id,
                "service_type_ids_parsed": service_type_ids,
            },
            "raw_offering_rows_matched": len(all_offerings),
            "distinct_professionals_in_offerings": len(pro_ids_in_offerings),
            "final_count_returned": count_all,
            "excluded_rows": excluded,
        }

    return JsonResponse(response)


# ---------------------------------------------------------------------------
# GET /api/professionals/<id>/
# ---------------------------------------------------------------------------

def professional_detail(request, pk):
    try:
        pro = Professional.objects.get(pk=pk, is_active=True)
    except Professional.DoesNotExist:
        return JsonResponse({"status": "error", "message": "Professional not found."}, status=404)

    data = serialize_professional_detail(pro, request)

    offered_service_type_ids = list(
        pro.offerings.filter(is_active=True).values_list("service_type_id", flat=True)
    )

    pool = Professional.objects.filter(is_active=True).select_related("governorate")
    if offered_service_type_ids:
        pool = pool.filter(
            offerings__service_type_id__in=offered_service_type_ids,
            offerings__is_active=True,
        ).distinct()

    pros_available_count = pool.count()

    pool_list = list(pool)
    ranked = sorted(pool_list, key=lambda p: p.ai_match_score(), reverse=True)[:3]
    ai_top_picks = []
    for idx, p in enumerate(ranked):
        card = serialize_professional_card(p, None, request, offered_service_type_ids)
        card["is_best"] = idx == 0
        card["ai_match_note"] = build_ai_match_note(p)
        ai_top_picks.append(card)

    ai_summary_note = build_ai_summary_note(ranked[0]) if ranked else None

    data["pros_available_count"] = pros_available_count
    data["ai_top_picks"] = ai_top_picks
    data["ai_summary_note"] = ai_summary_note

    return JsonResponse({
        "status": "success",
        "message": "Professional fetched successfully.",
        "data": data,
    })


# ---------------------------------------------------------------------------
# GET /api/professionals/<id>/slots/
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
# GET /api/professionals/areas/
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
# ---------------------------------------------------------------------------

@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def booking_create(request):
    payload = request.data

    required_fields = [
        "service_type_id",
        "booking_date",
        "booking_time",
        "user_name",
        "user_email",
        "user_mobile",
        "area",
        "villa_apartment_no",
        "street_name",
    ]

    missing = [f for f in required_fields if payload.get(f) in (None, "")]
    if missing:
        return Response({
            "status": "error",
            "message": f"Missing required fields: {', '.join(missing)}",
        }, status=400)

    raw_professional_id = payload.get("professional_id", 0)
    if raw_professional_id in (None, ""):
        raw_professional_id = 0

    try:
        professional_id = int(raw_professional_id)
    except (TypeError, ValueError):
        return Response({
            "status": "error",
            "message": "professional_id must be an integer."
        }, status=400)

    is_unassigned = professional_id == 0
    pro = None

    if not is_unassigned:
        try:
            pro = Professional.objects.get(pk=professional_id, is_active=True)
        except Professional.DoesNotExist:
            return Response({
                "status": "error",
                "message": f"Professional with ID {professional_id} not found."
            }, status=404)

    try:
        service_type = ServiceType.objects.get(pk=payload["service_type_id"], is_active=True)
    except ServiceType.DoesNotExist:
        return Response({
            "status": "error",
            "message": "Service type not found."
        }, status=404)

    if is_unassigned:
        service_fee = service_type.price
    else:
        offering = ProfessionalServiceType.objects.filter(
            professional=pro,
            service_type=service_type,
            is_active=True
        ).first()

        if not offering:
            return Response({
                "status": "error",
                "message": f"{pro.name} does not offer this service type."
            }, status=400)

        service_fee = offering.price

    try:
        booking_date = datetime.strptime(payload["booking_date"], "%Y-%m-%d").date()
        booking_time = datetime.strptime(payload["booking_time"], "%H:%M").time()
    except ValueError:
        return Response({
            "status": "error",
            "message": "Invalid date/time format. Use booking_date=YYYY-MM-DD, booking_time=HH:MM.",
        }, status=400)

    # Check availability clash for this professional (skip when unassigned)
    if not is_unassigned:
        clash = Booking.objects.filter(
            professional=pro,
            booking_date=booking_date,
            booking_time=booking_time,
            status__in=[Booking.STATUS_PENDING, Booking.STATUS_CONFIRMED],
        ).exists()

        if clash:
            return Response({
                "status": "error",
                "message": f"{pro.name} is already booked at {booking_time.strftime('%I:%M %p').lstrip('0')} on this date. Please pick another time slot."
            }, status=409)

    # Check duplicate booking for this user at the same datetime
    duplicate_booking = Booking.objects.filter(
        user_email=payload["user_email"],
        booking_date=booking_date,
        booking_time=booking_time,
    ).exclude(status__in=["cancelled", "completed"]).first()

    if duplicate_booking:
        return Response({
            "status": "error",
            "message": f"You already have a booking at {booking_time.strftime('%I:%M %p').lstrip('0')} on {booking_date.strftime('%d %b %Y')}. Please choose a different time slot."
        }, status=409)

    # Create booking using professionals.Booking
    booking = Booking(
        user_name=payload["user_name"],
        user_email=payload["user_email"],
        user_mobile=payload["user_mobile"],
        professional=pro,  # None if unassigned
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

    message = "Booking created successfully."
    if is_unassigned:
        message = "Booking created successfully. No professional has been assigned yet."

    return Response({
        "status": "success",
        "message": message,
        "data": serialize_booking(booking, request),
    }, status=201)


def serialize_booking(booking, request=None):
    if booking.professional is not None:
        professional_data = {
            "id": booking.professional.id,
            "name": booking.professional.name,
            "specialty": booking.professional.specialty,
            "rating": float(booking.professional.rating),
            "jobs_done": booking.professional.jobs_done,
            "phone": booking.professional.phone,
            "assigned": True,
        }
    else:
        professional_data = {
            "id": None,
            "name": None,
            "specialty": None,
            "rating": None,
            "jobs_done": None,
            "phone": None,
            "assigned": False,
        }

    return {
        "id": booking.id,
        "booking_code": booking.booking_code,
        "status": booking.status,
        "user": {
            "name": booking.user_name,
            "email": booking.user_email,
            "mobile": booking.user_mobile,
        },
        "professional": professional_data,
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
        "message": f"{booking.professional.name if booking.professional else 'Professional'} is confirmed. SMS + WhatsApp sent to {booking.user_mobile}.",
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

    if booking.status == Booking.STATUS_CANCELLED:
        return JsonResponse({
            "status": "error",
            "message": "Booking already cancelled.",
        }, status=400)

    # Only allow cancellation WITHIN the first 15 minutes of booking creation
    minutes_since_created = (timezone.now() - booking.created_at).total_seconds() / 60
    if minutes_since_created > 15:
        return JsonResponse({
            "status": "error",
            "message": "Cancellation window has expired. You can only cancel within 15 minutes of booking.",
        }, status=400)

    booking.status = Booking.STATUS_CANCELLED
    booking.save(update_fields=["status", "updated_at"])

    return JsonResponse({
        "status": "success",
        "message": "Booking cancelled.",
        "data": serialize_booking(booking, request),
    })

# ---------------------------------------------------------------------------
# POST /api/bookings/<id>/reschedule/
# ---------------------------------------------------------------------------

@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def reschedule_booking(request, pk):
    """
    Safely reschedules a booking.
    Expects payload: {"booking_date": "YYYY-MM-DD", "booking_time": "HH:MM"}
    """
    payload = request.data
    new_date_str = payload.get("booking_date")
    new_time_str = payload.get("booking_time")

    if not new_date_str or not new_time_str:
        return Response({
            "status": "error",
            "message": "Missing required fields: booking_date and booking_time are required."
        }, status=400)

    # Fetch the booking (ensure ownership via email)
    try:
        booking = Booking.objects.get(pk=pk, user_email=request.user.email)
    except Booking.DoesNotExist:
        return Response({
            "status": "error",
            "message": "Booking not found or you don't have permission."
        }, status=404)

    if booking.status in ['cancelled', 'completed']:
        return Response({
            "status": "error",
            "message": f"Cannot reschedule a booking that is already {booking.status}."
        }, status=400)

    # Parse input values
    try:
        new_booking_date = datetime.strptime(new_date_str, "%Y-%m-%d").date()
        new_booking_time = datetime.strptime(new_time_str, "%H:%M").time()
    except ValueError:
        return Response({
            "status": "error",
            "message": "Invalid format. Use booking_date=YYYY-MM-DD, booking_time=HH:MM."
        }, status=400)

    # Check professional availability (if assigned)
    if booking.professional:
        pro_clash = Booking.objects.filter(
            professional=booking.professional,
            booking_date=new_booking_date,
            booking_time=new_booking_time,
            status__in=[Booking.STATUS_PENDING, Booking.STATUS_CONFIRMED]
        ).exclude(id=booking.id).exists()

        if pro_clash:
            return Response({
                "status": "error",
                "message": f"{booking.professional.name} is already booked at {new_booking_time.strftime('%I:%M %p').lstrip('0')} on this date."
            }, status=409)

    # Check user duplicate booking
    user_clash = Booking.objects.filter(
        user_email=request.user.email,
        booking_date=new_booking_date,
        booking_time=new_booking_time,
    ).exclude(status__in=["cancelled", "completed"]).exclude(id=booking.id).first()

    if user_clash:
        return Response({
            "status": "error",
            "message": "You already have another active service scheduled at this exact time."
        }, status=409)

    # Update booking
    booking.booking_date = new_booking_date
    booking.booking_time = new_booking_time
    booking.status = Booking.STATUS_PENDING
    booking.save(update_fields=["booking_date", "booking_time", "status", "updated_at"])

    return Response({
        "status": "success",
        "message": f"Booking successfully rescheduled to {new_booking_date} at {new_booking_time.strftime('%I:%M %p').lstrip('0')}.",
        "data": {
            "booking_number": booking.booking_code,
            "new_date": booking.booking_date.strftime('%Y-%m-%d'),
            "new_time": booking.booking_time.strftime('%H:%M'),
            "status": booking.status
        }
    }, status=200)


# ---------------------------------------------------------------------------
# POST /api/bookings/<id>/book-again/
# ---------------------------------------------------------------------------

@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def booking_book_again(request, pk):
    """
    Reactivates a cancelled booking by flipping its status back to PENDING.
    """
    try:
        booking = Booking.objects.get(pk=pk, user_email=request.user.email)
    except Booking.DoesNotExist:
        return Response({
            "status": "error",
            "message": "Booking not found or you don't have permission."
        }, status=404)

    if booking.status != Booking.STATUS_CANCELLED:
        return Response({
            "status": "error",
            "message": "Only cancelled bookings can be booked again."
        }, status=400)

    booking.status = Booking.STATUS_PENDING
    booking.save(update_fields=["status", "updated_at"])

    return Response({
        "status": "success",
        "message": "Booking reactivated and set to pending.",
        "data": serialize_booking(booking, request),
    }, status=200)

@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def vendor_booking_list(request):
    """
    Vendor-specific booking list with status, category, and date filtering.
    """
    try:
        professional = Professional.objects.get(user=request.user)
    except Professional.DoesNotExist:
        return Response({"status": "error", "message": "Professional profile not found."}, status=404)

    queryset = Booking.objects.filter(professional=professional)

    status_filter = request.GET.get('status', '').lower()
    today = timezone.localdate()

    # Statuses considered "active" (job not yet completed/cancelled)
    ACTIVE_STATUSES = [
        Booking.STATUS_SCHEDULED,
        Booking.STATUS_PENDING,
        Booking.STATUS_CONFIRMED,
        Booking.STATUS_EN_ROUTE,
        Booking.STATUS_ARRIVED,
        Booking.STATUS_IN_PROGRESS,
    ]

    # Statuses that mean the pro is literally on the job right now
    ONGOING_STATUSES = [
        Booking.STATUS_EN_ROUTE,
        Booking.STATUS_ARRIVED,
        Booking.STATUS_IN_PROGRESS,
    ]

    # 1. Status Filtering
    if status_filter == 'today':
        queryset = queryset.filter(
            booking_date=today
        ).exclude(
            status__in=[Booking.STATUS_CANCELLED, Booking.STATUS_COMPLETED]
        )

    elif status_filter == 'ongoing':
        # Jobs currently in progress, regardless of date
        queryset = queryset.filter(status__in=ONGOING_STATUSES)

    elif status_filter == 'upcoming':
        # FIX: use __gte so TODAY'S not-yet-started bookings are included,
        # not just strictly-future dates. Ongoing jobs are included too
        # regardless of date (e.g. a job that started yesterday and is
        # still IN_PROGRESS should still show as "upcoming/active").
        queryset = queryset.filter(
            Q(booking_date__gte=today, status__in=ACTIVE_STATUSES) |
            Q(status__in=ONGOING_STATUSES)
        )

    elif status_filter == 'completed':
        queryset = queryset.filter(status=Booking.STATUS_COMPLETED)

    elif status_filter == 'cancelled':
        queryset = queryset.filter(status=Booking.STATUS_CANCELLED)
    # 2. Category / Service Filter
    category_id = request.GET.get('category_id')
    if category_id:
        queryset = queryset.filter(service_type__service_id=category_id)

    # 3. Date Filter (YYYY-MM-DD)
    date_param = request.GET.get('date')
    if date_param:
        queryset = queryset.filter(booking_date=date_param)

    queryset = queryset.order_by('-booking_date', '-booking_time')

    # Pagination — default 10 per page
    page_number = request.GET.get('page', 1)
    page_size = request.GET.get('page_size', 10)
    paginator = Paginator(queryset, page_size)
    page_obj = paginator.get_page(page_number)

    def build_page_url(page_num):
        if not page_num:
            return None
        params = request.GET.copy()
        params['page'] = page_num
        params['page_size'] = page_size
        return f"{request.path}?{params.urlencode()}"

    data = []
    for booking in page_obj:
        booking_datetime = timezone.datetime.combine(booking.booking_date, booking.booking_time)
        data.append({
            "id": booking.id,
            "booking_code": booking.booking_code,
            "service_name": booking.service_type.service.name if booking.service_type and booking.service_type.service else "",
            "service_type": booking.service_type.type_name if booking.service_type else "",
            "customer_name": booking.user_name,
            "date_time": booking_datetime.strftime('%a %d %b %I:%M %p'),
            "location": booking.area,
            "price": f"OMR {booking.total_amount}",
            "status": booking.status,
            "status_display": booking.get_status_display()
        })

    return Response({
        "status": "success",
        "count": len(data),
        "total_count": paginator.count,
        "total_pages": paginator.num_pages,
        "current_page": page_obj.number,
        "page_size": int(page_size),
        "next": build_page_url(page_obj.next_page_number()) if page_obj.has_next() else None,
        "previous": build_page_url(page_obj.previous_page_number()) if page_obj.has_previous() else None,
        "data": data
    })

@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])  # Add IsAdminUser permissions as needed
def admin_all_bookings(request):
    """
    Admin booking list with Search, Status, Area, Service filters, and CSV Export.
    """
    queryset = Booking.objects.all().select_related('professional', 'service_type', 'service_type__service')

    # 1. Search Query (ID, Customer Name, Mobile)
    search_query = request.GET.get('search', '').strip()
    if search_query:
        queryset = queryset.filter(
            Q(booking_code__icontains=search_query) |
            Q(user_name__icontains=search_query) |
            Q(user_mobile__icontains=search_query)
        )

    # 2. Status Filter
    status_filter = request.GET.get('status', '').upper()
    if status_filter and status_filter != 'ALL':
        if status_filter == 'UNASSIGNED':
            queryset = queryset.filter(professional__isnull=True)
        else:
            queryset = queryset.filter(status=status_filter)

    # 3. Area Filter
    area = request.GET.get('area', '').strip()
    if area:
        queryset = queryset.filter(area__iexact=area)

    # 4. Service Filter
    service_id = request.GET.get('service_id')
    if service_id:
        queryset = queryset.filter(service_type__service_id=service_id)

    queryset = queryset.order_by('-created_at')

    # CSV Export Handler
    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="all_bookings.csv"'

        writer = csv.writer(response)
        writer.writerow(['Booking ID', 'Service', 'Customer', 'Professional', 'Date/Time', 'Area', 'Price (OMR)', 'Payment', 'Status'])

        for b in queryset:
            pro_name = b.professional.name if b.professional else "Unassigned"
            b_dt = f"{b.booking_date} {b.booking_time.strftime('%H:%M')}"
            writer.writerow([b.booking_code, b.service_type.type_name, b.user_name, pro_name, b_dt, b.area, b.total_amount, b.get_payment_method_display(), b.status])

        return response

   # Pagination
    page_number = request.GET.get('page', 1)
    page_size = request.GET.get('page_size', 10)
    paginator = Paginator(queryset, page_size)
    page_obj = paginator.get_page(page_number)

    def build_page_url(page_num):
        if not page_num:
            return None
        params = request.GET.copy()
        params['page'] = page_num
        params['page_size'] = page_size
        return f"{request.path}?{params.urlencode()}"

    data = []
    for b in page_obj:
        data.append({
            "id": b.id,
            "booking_code": b.booking_code,
            "service_name": b.service_type.type_name if b.service_type else "",
            "customer_name": b.user_name,
            "professional_name": b.professional.name if b.professional else "Unassigned",
            "date": b.booking_date.strftime('%Y-%m-%d'),
            "time": b.booking_time.strftime('%I:%M %p'),
            "area": b.area,
            "price": f"OMR {b.total_amount}",
            "payment_status": "Paid" if b.payment_method != "cash_on_completion" else "Pending",
            "status": b.status
        })

    return Response({
        "status": "success",
        "count": len(data),
        "total_count": paginator.count,
        "total_pages": paginator.num_pages,
        "current_page": page_obj.number,
        "page_size": int(page_size),
        "next": build_page_url(page_obj.next_page_number()) if page_obj.has_next() else None,
        "previous": build_page_url(page_obj.previous_page_number()) if page_obj.has_previous() else None,
        "data": data
    })

@api_view(['GET', 'POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def admin_booking_control_assign(request, booking_id=None):
    """
    GET: List unassigned bookings with available vendors and AI smart routing recommendations.
    POST: Assign or Override vendor assignment for a booking.
    """
    # POST: Manual / AI Confirm Assignment
    if request.method == 'POST':
        booking_id = request.data.get('booking_id') or booking_id
        professional_id = request.data.get('professional_id')

        if not booking_id or not professional_id:
            return Response({"status": "error", "message": "booking_id and professional_id required."}, status=400)

        booking = get_object_or_404(Booking, id=booking_id)
        professional = get_object_or_404(Professional, id=professional_id, is_active=True)

        booking.professional = professional
        booking.status = Booking.STATUS_CONFIRMED
        booking.save()

        return Response({
            "status": "success",
            "message": f"Booking {booking.booking_code} assigned to {professional.name} successfully."
        })

    # GET: Dispatch Queue & Smart Routing Data
    unassigned_bookings = Booking.objects.filter(professional__isnull=True).exclude(status=Booking.STATUS_CANCELLED)

    queue_data = []
    smart_routing_data = []

    for b in unassigned_bookings:
        # Find matching active professionals offering this service
        available_pros = Professional.objects.filter(
            offerings__service_type=b.service_type,
            offerings__is_active=True,
            is_active=True
        ).distinct()

        pros_list = []
        for p in available_pros:
            pros_list.append({
                "id": p.id,
                "name": p.name,
                "rating": float(p.rating),
                "distance_km": float(p.distance_km),
                "ai_score": p.ai_match_score(b.service_type)
            })

        queue_data.append({
            "booking_id": b.id,
            "booking_code": b.booking_code,
            "service_name": b.service_type.type_name,
            "customer_name": b.user_name,
            "area": b.area,
            "time": b.booking_time.strftime('%I:%M %p'),
            "price": f"OMR {b.total_amount}",
            "available_vendors_count": len(pros_list),
            "available_vendors": pros_list
        })

        # Calculate AI Top Pick for Smart Routing panel
        if pros_list:
            top_pick = max(pros_list, key=lambda x: x['ai_score'])
            smart_routing_data.append({
                "booking_id": b.id,
                "customer_name": b.user_name,
                "recommended_vendor_id": top_pick['id'],
                "recommended_vendor_name": top_pick['name'],
                "ai_score": top_pick['ai_score'],
                "reason": f"Closest distance ({top_pick['distance_km']}km) and highest rating ({top_pick['rating']}★)"
            })

    return Response({
        "status": "success",
        "unassigned_count": len(queue_data),
        "unassigned_queue": queue_data,
        "ai_smart_routing": smart_routing_data
    })

@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def vendor_my_services(request):
    try:
        professional = Professional.objects.get(user=request.user)
    except Professional.DoesNotExist:
        return Response({
            "status": "error",
            "message": "Professional profile not found for this account."
        }, status=404)

    offerings = ProfessionalServiceType.objects.filter(
        professional=professional
    ).select_related('service_type', 'service_type__service')

    category_id = request.GET.get('category_id')
    if category_id:
        offerings = offerings.filter(service_type__service_id=category_id)

    # ---- EXISTING GROUPING LOGIC (unchanged) ----
    grouped = {}
    for o in offerings:
        st = o.service_type
        service = st.service
        if service is None:
            continue
        key = service.id
        if key not in grouped:
            grouped[key] = {
                "service_id": service.id,
                "service_name": service.name,
                "icon": request.build_absolute_uri(service.icon.url) if service.icon and hasattr(service.icon, 'url') else "",
                "service_types": []
            }
        grouped[key]["service_types"].append({
            "service_type_id": st.id,
            "type_name": st.type_name,
            "duration": st.duration,
            "price": str(o.price),
            "default_price": str(st.price),
            "is_active": o.is_active,
        })

    data = list(grouped.values())
    total_service_types = sum(len(g["service_types"]) for g in data)

    # ---- NEW: build the AI pricing banner dynamically ----
    ai_note = _build_ai_pricing_note(professional)

    return Response({
        "status": "success",
        "message": "Services offered by this professional fetched successfully.",
        "professional_id": professional.id,
        "professional_name": professional.name,
        "categories_count": len(data),
        "service_types_count": total_service_types,
        "data": data,
        "ai_pricing_note": ai_note,   # <-- new field only, nothing else changed
    })


def _build_ai_pricing_note(professional):
    """
    Computes a single dynamic AI banner message, same comparison logic
    as vendor_ai_pricing_suggestions, but only returns the SINGLE
    most relevant suggestion (biggest opportunity) as text.
    """
    my_offerings = ProfessionalServiceType.objects.filter(
        professional=professional, is_active=True
    ).select_related("service_type").prefetch_related("area_prices")

    my_areas = list(
        ProfessionalArea.objects.filter(professional=professional).values_list("area", flat=True)
    )

    candidates = []

    for o in my_offerings:
        area_price_map = {ap.area: ap.price for ap in o.area_prices.all()}

        for area in my_areas:
            my_price = area_price_map.get(area, o.price)

            market_qs = ProfessionalServiceArea.objects.filter(
                offering__service_type=o.service_type,
                area=area,
            ).exclude(offering__professional=professional).values_list("price", flat=True)

            market_prices = list(market_qs)
            if not market_prices:
                market_prices = list(
                    ProfessionalServiceType.objects.filter(
                        service_type=o.service_type, is_active=True
                    ).exclude(professional=professional).values_list("price", flat=True)
                )

            if not market_prices:
                continue

            market_avg = round(mean([float(p) for p in market_prices]), 2)
            diff = round(market_avg - float(my_price), 2)

            if abs(diff) < 1:
                continue

            direction = "increase" if diff > 0 else "decrease"

            if direction == "increase":
                message = (
                    f"Your {o.service_type.type_name} OMR {my_price} is market-rate. "
                    f"{area} avg is OMR {market_avg} — you could charge more there."
                )
            else:
                message = (
                    f"Your {o.service_type.type_name} OMR {my_price} is above the "
                    f"{area} avg of OMR {market_avg} — consider lowering to stay competitive."
                )

            candidates.append({
                "service_type_id": o.service_type.id,
                "service_name": o.service_type.type_name,
                "area": area,
                "your_price": str(my_price),
                "market_avg": str(market_avg),
                "direction": direction,
                "gap": abs(diff),
                "message": message,
            })

    if not candidates:
        return None

    # pick the biggest price gap = most "worth showing" suggestion
    best = max(candidates, key=lambda c: c["gap"])
    return {
        "service_type_id": best["service_type_id"],
        "service_name": best["service_name"],
        "area": best["area"],
        "your_price": best["your_price"],
        "market_avg": best["market_avg"],
        "direction": best["direction"],
        "message": best["message"],
    }


def professional_services_by_id(request, pk):
    """
    PUBLIC endpoint — list the services/service-types a specific
    professional (given by professional_id in the URL) offers.
    No login required — used for customer-facing profile pages.

    Optional: ?category_id=<Service id> to filter to one category.
    """
    try:
        professional = Professional.objects.get(pk=pk, is_active=True)
    except Professional.DoesNotExist:
        return JsonResponse({
            "status": "error",
            "message": "Professional not found."
        }, status=404)

    offerings = ProfessionalServiceType.objects.filter(
        professional=professional,
        is_active=True
    ).select_related('service_type', 'service_type__service')

    category_id = request.GET.get('category_id')
    if category_id:
        offerings = offerings.filter(service_type__service_id=category_id)

    grouped = {}
    for o in offerings:
        st = o.service_type
        service = st.service
        if service is None:
            continue
        key = service.id
        if key not in grouped:
            grouped[key] = {
                "service_id": service.id,
                "service_name": service.name,
                "icon": request.build_absolute_uri(service.icon.url) if service.icon and hasattr(service.icon, 'url') else "",
                "service_types": []
            }
        grouped[key]["service_types"].append({
            "service_type_id": st.id,
            "type_name": st.type_name,
            "duration": st.duration,
            "price": str(o.price),
        })

    data = list(grouped.values())
    total_service_types = sum(len(g["service_types"]) for g in data)

    return JsonResponse({
        "status": "success",
        "message": "Services offered by this professional fetched successfully.",
        "professional_id": professional.id,
        "professional_name": professional.name,
        "categories_count": len(data),
        "service_types_count": total_service_types,
        "data": data
    })

@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def booking_available_professionals(request, booking_id):
    """
    Returns the list of professionals available to be assigned to a
    SPECIFIC booking, based on that booking's service_type.
    Used to populate the 'Assign Professional' dropdown when the admin
    clicks Assign/Reassign on a particular booking row.
    """
    booking = get_object_or_404(Booking, id=booking_id)

    available_pros = Professional.objects.filter(
        offerings__service_type=booking.service_type,
        offerings__is_active=True,
        is_active=True
    ).distinct().select_related("governorate")

    pros_list = []
    for p in available_pros:
        offering = p.offerings.filter(
            service_type=booking.service_type, is_active=True
        ).first()
        pros_list.append({
            "id": p.id,
            "name": p.name,
            "specialty": p.specialty,
            "rating": float(p.rating),
            "jobs_done": p.jobs_done,
            "distance_km": float(p.distance_km),
            "area": p.area,
            "governorate": p.governorate.name if p.governorate else None,
            "is_available_today": p.is_available_today,
            "price": str(offering.price) if offering else None,
            "ai_score": p.ai_match_score(booking.service_type),
            "is_current": booking.professional_id == p.id,
        })

    # Sort best match first
    pros_list.sort(key=lambda x: x["ai_score"], reverse=True)

    return Response({
        "status": "success",
        "booking_id": booking.id,
        "booking_code": booking.booking_code,
        "service_type": booking.service_type.type_name if booking.service_type else None,
        "current_professional_id": booking.professional_id,
        "available_count": len(pros_list),
        "data": pros_list,
    })


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def vendor_services_pricing(request):
    try:
        professional = Professional.objects.get(user=request.user)
    except Professional.DoesNotExist:
        return Response({"status": "error", "message": "Professional profile not found."}, status=404)

    offerings = ProfessionalServiceType.objects.filter(
        professional=professional
    ).select_related("service_type", "service_type__service").prefetch_related("area_prices")

    category_id = request.GET.get("category_id")
    if category_id:
        offerings = offerings.filter(service_type__service_id=category_id)

    offerings = offerings.order_by("service_type__service_id", "service_type__type_name")

    my_areas = list(
        ProfessionalArea.objects.filter(professional=professional).values_list("area", flat=True)
    )

    # ---- Build flat list (one row per service_type) — this is what service_types_count counts ----
    all_rows = []
    for o in offerings:
        area_price_map = {ap.area: str(ap.price) for ap in o.area_prices.all()}
        area_prices = {area: area_price_map.get(area, str(o.price)) for area in my_areas}

        all_rows.append({
            "offering_id": o.id,
            "service_type_id": o.service_type.id,
            "service_name": o.service_type.type_name,
            "category_id": o.service_type.service_id,
            "category_name": o.service_type.service.name if o.service_type.service else None,
            "base_price": str(o.price),
            "area_prices": area_prices,
            "status": "active" if o.is_active else "paused",
        })

    total_service_types = len(all_rows)

    # ---- Category filter chips (All + per-category counts), for the tab bar ----
    category_chip_qs = ProfessionalServiceType.objects.filter(
        professional=professional
    ).select_related("service_type__service")

    chip_counts = {}
    for o in category_chip_qs:
        if not o.service_type.service:
            continue
        cid = o.service_type.service_id
        cname = o.service_type.service.name
        if cid not in chip_counts:
            chip_counts[cid] = {"category_id": cid, "category_name": cname, "count": 0}
        chip_counts[cid]["count"] += 1

    category_filters = [{"category_id": None, "category_name": "All", "count": category_chip_qs.count()}]
    category_filters += sorted(chip_counts.values(), key=lambda c: c["category_name"])

    # ---- Pagination on the flat service_type rows ----
    page_number = request.GET.get("page", 1)
    page_size = request.GET.get("page_size", 10)
    paginator = Paginator(all_rows, page_size)
    page_obj = paginator.get_page(page_number)

    def build_page_url(page_num):
        if not page_num:
            return None
        params = request.GET.copy()
        params["page"] = page_num
        params["page_size"] = page_size
        return f"{request.path}?{params.urlencode()}"

    # ---- AI suggestions, scoped to the SAME category filter, as a cyclable list ----
    ai_suggestions = _build_ai_pricing_suggestions(professional, category_id)
    ai_index = int(request.GET.get("ai_index", 0))
    ai_note = None
    if ai_suggestions:
        ai_index = max(0, min(ai_index, len(ai_suggestions) - 1))
        ai_note = {
            **ai_suggestions[ai_index],
            "position": ai_index + 1,          # 1-based, e.g. "2" in "2/6"
            "total": len(ai_suggestions),        # e.g. "6" in "2/6"
            "has_next": ai_index + 1 < len(ai_suggestions),
            "has_previous": ai_index > 0,
        }

    return Response({
        "status": "success",
        "professional_id": professional.id,
        "service_areas": my_areas,
        "category_filters": category_filters,
        "categories_count": len({r["category_id"] for r in all_rows}),
        "service_types_count": total_service_types,
        "count": len(page_obj.object_list),
        "total_count": paginator.count,
        "total_pages": paginator.num_pages,
        "current_page": page_obj.number,
        "page_size": int(page_size),
        "next": build_page_url(page_obj.next_page_number()) if page_obj.has_next() else None,
        "previous": build_page_url(page_obj.previous_page_number()) if page_obj.has_previous() else None,
        "data": list(page_obj.object_list),
        "ai_pricing_note": ai_note,
    })


def _build_ai_pricing_suggestions(professional, category_id=None):
    """
    Returns ALL price-gap suggestions (not just one), optionally scoped
    to a single category, sorted by biggest gap first — so ai_index=0
    is the most important suggestion, matching the "Next ->" cycling UI.
    """
    my_offerings = ProfessionalServiceType.objects.filter(
        professional=professional, is_active=True
    ).select_related("service_type", "service_type__service").prefetch_related("area_prices")

    if category_id:
        my_offerings = my_offerings.filter(service_type__service_id=category_id)

    my_areas = list(
        ProfessionalArea.objects.filter(professional=professional).values_list("area", flat=True)
    )

    suggestions = []

    for o in my_offerings:
        area_price_map = {ap.area: ap.price for ap in o.area_prices.all()}

        for area in my_areas:
            my_price = area_price_map.get(area, o.price)

            market_qs = ProfessionalServiceArea.objects.filter(
                offering__service_type=o.service_type,
                area=area,
            ).exclude(offering__professional=professional).values_list("price", flat=True)

            market_prices = list(market_qs)
            if not market_prices:
                market_prices = list(
                    ProfessionalServiceType.objects.filter(
                        service_type=o.service_type, is_active=True
                    ).exclude(professional=professional).values_list("price", flat=True)
                )

            if not market_prices:
                continue

            market_avg = round(mean([float(p) for p in market_prices]), 2)
            diff = round(market_avg - float(my_price), 2)

            if abs(diff) < 1:
                continue

            direction = "increase" if diff > 0 else "decrease"

            if direction == "increase":
                message = (
                    f"Your {o.service_type.type_name} OMR {my_price} is market-rate. "
                    f"{area} avg is OMR {market_avg} — you could charge more there."
                )
            else:
                message = (
                    f"Your {o.service_type.type_name} OMR {my_price} is above the "
                    f"{area} avg of OMR {market_avg} — consider lowering to stay competitive."
                )

            suggestions.append({
                "service_type_id": o.service_type.id,
                "service_name": o.service_type.type_name,
                "category_id": o.service_type.service_id,
                "area": area,
                "your_price": str(my_price),
                "market_avg": str(market_avg),
                "direction": direction,
                "gap": abs(diff),
                "message": message,
            })

    # biggest gap first — so cycling "Next" moves from most to least urgent
    suggestions.sort(key=lambda s: s["gap"], reverse=True)
    for s in suggestions:
        s.pop("gap", None)  # internal sort key, not needed in response

    return suggestions

# ---------------------------------------------------------------------------
# PATCH /api/professionals/vendor/services/<offering_id>/price/
# Body: { "base_price": 15.00, "area_prices": {"MSQ Hills": 18.00} }
# ---------------------------------------------------------------------------

@api_view(['PATCH'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def vendor_update_service_price(request, offering_id):
    try:
        professional = Professional.objects.get(user=request.user)
    except Professional.DoesNotExist:
        return Response({"status": "error", "message": "Professional profile not found."}, status=404)

    offering = get_object_or_404(
        ProfessionalServiceType, id=offering_id, professional=professional
    )

    base_price = request.data.get("base_price")
    area_prices = request.data.get("area_prices", {})

    floor = offering.service_type.price_floor
    cap = offering.service_type.price_cap

    def validate(p):
        p = Decimal(str(p))
        if floor is not None and p < floor:
            raise ValueError(f"Price cannot be below the admin floor of OMR {floor}.")
        if cap is not None and p > cap:
            raise ValueError(f"Price cannot exceed the admin cap of OMR {cap}.")
        return p

    from decimal import Decimal
    try:
        if base_price is not None:
            offering.price = validate(base_price)
            offering.save(update_fields=["price"])

        for area, price in area_prices.items():
            validated = validate(price)
            ProfessionalServiceArea.objects.update_or_create(
                offering=offering, area=area, defaults={"price": validated}
            )
    except ValueError as e:
        return Response({"status": "error", "message": str(e)}, status=400)

    return Response({
        "status": "success",
        "message": "Pricing updated.",
        "offering_id": offering.id,
        "base_price": str(offering.price),
        "area_prices": {ap.area: str(ap.price) for ap in offering.area_prices.all()},
    })


# ---------------------------------------------------------------------------
# PATCH /api/professionals/vendor/services/<offering_id>/status/
# Body: { "is_active": true }
# ---------------------------------------------------------------------------

@api_view(['PATCH'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def vendor_toggle_service_status(request, offering_id):
    try:
        professional = Professional.objects.get(user=request.user)
    except Professional.DoesNotExist:
        return Response({"status": "error", "message": "Professional profile not found."}, status=404)

    offering = get_object_or_404(
        ProfessionalServiceType, id=offering_id, professional=professional
    )

    is_active = request.data.get("is_active")
    if is_active is None:
        return Response({"status": "error", "message": "is_active is required."}, status=400)

    offering.is_active = bool(is_active)
    offering.save(update_fields=["is_active"])

    return Response({
        "status": "success",
        "message": f"{offering.service_type.type_name} is now {'active' if offering.is_active else 'paused'}.",
        "offering_id": offering.id,
        "status_value": "active" if offering.is_active else "paused",
    })


# ---------------------------------------------------------------------------
# POST /api/professionals/vendor/services/add/
# Body: { "service_type_id": 5, "base_price": 20.00 }
# ---------------------------------------------------------------------------

# @api_view(['POST'])
# @authentication_classes([JWTAuthentication])
# @permission_classes([IsAuthenticated])
# def vendor_add_service(request):
#     try:
#         professional = Professional.objects.get(user=request.user)
#     except Professional.DoesNotExist:
#         return Response({"status": "error", "message": "Professional profile not found."}, status=404)

#     service_type_id = request.data.get("service_type_id")
#     base_price = request.data.get("base_price")

#     if not service_type_id or base_price is None:
#         return Response({
#             "status": "error",
#             "message": "service_type_id and base_price are required."
#         }, status=400)

#     service_type = get_object_or_404(ServiceType, id=service_type_id, is_active=True)

#     if ProfessionalServiceType.objects.filter(
#         professional=professional, service_type=service_type
#     ).exists():
#         return Response({
#             "status": "error",
#             "message": "You already offer this service."
#         }, status=409)

#     offering = ProfessionalServiceType.objects.create(
#         professional=professional,
#         service_type=service_type,
#         price=base_price,
#         is_active=True,
#     )

#     return Response({
#         "status": "success",
#         "message": f"{service_type.type_name} added to your services.",
#         "offering_id": offering.id,
#     }, status=201)

def _validate_decimal(value, field_name):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field_name} must be a valid number.")


# ---------------------------------------------------------------------------
# GET  /api/professionals/vendor/services/categories/
# Returns categories + their service names, for populating the two dropdowns
# ---------------------------------------------------------------------------

@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def vendor_service_categories(request):
    """
    Returns categories + service names available in the vendor's
    OWN governorate (working location) only — not all 231 duplicated
    rows across every governorate in the system.
    """
    try:
        professional = Professional.objects.get(user=request.user)
    except Professional.DoesNotExist:
        return Response({"status": "error", "message": "Professional profile not found."}, status=404)

    # Only categories tied to this vendor's governorate
    categories = Service.objects.filter(
        is_active=True,
        governorate=professional.governorate
    ).order_by("name")

    data = []
    for c in categories:
        types = ServiceType.objects.filter(service=c, is_active=True).order_by("type_name")
        data.append({
            "category_id": c.id,
            "category_name": c.name,
            "service_names": [
                {"id": t.id, "type_name": t.type_name, "price": str(t.price)}
                for t in types
            ]
        })

    return Response({
        "status": "success",
        "governorate_id": professional.governorate_id,
        "governorate": professional.governorate.name if professional.governorate else None,
        "count": len(data),
        "data": data,
    })

# ---------------------------------------------------------------------------
# POST /api/professionals/vendor/services/add/
# PUT/PATCH /api/professionals/vendor/services/<offering_id>/edit/
#
# Body:
# {
#   "category_id": 3,                 // OR
#   "new_category_name": "AC & HVAC", // if creating a new category
#
#   "service_type_id": 12,            // OR
#   "new_service_name": "AC Cleaning",// if creating a new service name
#
#   "base_price": 20,
#   "status": "active" | "paused",
#   "area_prices": {"Qurum": 15, "Al Khuwair": 15, "MSQ Hills": 18}
# }
# ---------------------------------------------------------------------------

@api_view(['POST', 'PUT', 'PATCH'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def vendor_add_or_edit_service(request, offering_id=None):
    try:
        professional = Professional.objects.get(user=request.user)
    except Professional.DoesNotExist:
        return Response({"status": "error", "message": "Professional profile not found."}, status=404)

    payload = request.data
    is_edit = offering_id is not None

    # -----------------------------------------------------------------
    # 1. Resolve / create CATEGORY (services_service)
    # -----------------------------------------------------------------
    category_id = payload.get("category_id")
    new_category_name = (payload.get("new_category_name") or "").strip()

    if new_category_name:
        # "+ Add New Category" was used -> create it if it doesn't exist
        category, _ = Service.objects.get_or_create(
            name__iexact=new_category_name,
            defaults={
                "name": new_category_name,
                "governorate": professional.governorate,
                "starting_price": payload.get("base_price") or 0,
                "is_active": True,
                # icon is required (non-null ImageField) — must be uploaded
                # separately via multipart/form-data 'icon' if you enforce it,
                # or make Service.icon blank=True/null=True to relax this.
            }
        )
    elif category_id:
        try:
            category = Service.objects.get(id=category_id, is_active=True)
        except Service.DoesNotExist:
            return Response({"status": "error", "message": "Category not found."}, status=404)
    elif is_edit:
        # editing: category not changing, pull from existing offering
        existing = get_object_or_404(ProfessionalServiceType, id=offering_id, professional=professional)
        category = existing.service_type.service
    else:
        return Response({
            "status": "error",
            "message": "Provide category_id or new_category_name."
        }, status=400)

    # -----------------------------------------------------------------
    # 2. Resolve / create SERVICE NAME (services_servicetype)
    # -----------------------------------------------------------------
    service_type_id = payload.get("service_type_id")
    new_service_name = (payload.get("new_service_name") or "").strip()
    base_price = payload.get("base_price")

    if base_price is None:
        return Response({"status": "error", "message": "base_price is required."}, status=400)

    try:
        base_price = _validate_decimal(base_price, "base_price")
    except ValueError as e:
        return Response({"status": "error", "message": str(e)}, status=400)

    if new_service_name:
        # "+ Add New Service Name" was used -> create it under the category
        service_type, created = ServiceType.objects.get_or_create(
            service=category,
            type_name__iexact=new_service_name,
            defaults={
                "type_name": new_service_name,
                "price": base_price,
                "duration": payload.get("duration", ""),
                "description": payload.get("description", ""),
                "is_active": True,
            }
        )
    elif service_type_id:
        try:
            service_type = ServiceType.objects.get(id=service_type_id, service=category, is_active=True)
        except ServiceType.DoesNotExist:
            return Response({
                "status": "error",
                "message": "Service name not found under selected category."
            }, status=404)
    elif is_edit:
        existing = get_object_or_404(ProfessionalServiceType, id=offering_id, professional=professional)
        service_type = existing.service_type
    else:
        return Response({
            "status": "error",
            "message": "Provide service_type_id or new_service_name."
        }, status=400)

    # -----------------------------------------------------------------
    # 3. Status
    # -----------------------------------------------------------------
    status_value = (payload.get("status") or "active").lower()
    is_active = status_value != "paused"

    # -----------------------------------------------------------------
    # 4. Create or update the VENDOR'S offering (ProfessionalServiceType)
    # -----------------------------------------------------------------
    if is_edit:
        offering = get_object_or_404(ProfessionalServiceType, id=offering_id, professional=professional)
        offering.service_type = service_type
        offering.price = base_price
        offering.is_active = is_active
        offering.save(update_fields=["service_type", "price", "is_active"])
        created = False
    else:
        if ProfessionalServiceType.objects.filter(
            professional=professional, service_type=service_type
        ).exists():
            return Response({
                "status": "error",
                "message": "You already offer this service. Use edit instead."
            }, status=409)

        offering = ProfessionalServiceType.objects.create(
            professional=professional,
            service_type=service_type,
            price=base_price,
            is_active=is_active,
        )
        created = True

    # -----------------------------------------------------------------
    # 5. Area-specific pricing (Qurum / Al Khuwair / MSQ Hills, etc.)
    # -----------------------------------------------------------------
    area_prices_in = payload.get("area_prices", {}) or {}
    saved_area_prices = {}

    for area_name, price_val in area_prices_in.items():
        if price_val in (None, ""):
            continue
        try:
            validated_price = _validate_decimal(price_val, f"area_prices[{area_name}]")
        except ValueError as e:
            return Response({"status": "error", "message": str(e)}, status=400)

        # make sure this area is registered for the vendor (auto-add if missing)
        ProfessionalArea.objects.get_or_create(professional=professional, area=area_name)

        ProfessionalServiceArea.objects.update_or_create(
            offering=offering, area=area_name, defaults={"price": validated_price}
        )
        saved_area_prices[area_name] = str(validated_price)

    return Response({
        "status": "success",
        "message": f"{service_type.type_name} {'updated' if is_edit else 'added'} successfully.",
        "created": created,
        "data": {
            "offering_id": offering.id,
            "category_id": category.id,
            "category_name": category.name,
            "service_type_id": service_type.id,
            "service_name": service_type.type_name,
            "base_price": str(offering.price),
            "status": "active" if offering.is_active else "paused",
            "area_prices": saved_area_prices,
        }
    }, status=201 if not is_edit else 200)


# ---------------------------------------------------------------------------
# GET /api/professionals/vendor/services/ai-pricing/
# ---------------------------------------------------------------------------

@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def vendor_ai_pricing_suggestions(request):
    """
    Compares this vendor's price per service+area against the market
    average (all OTHER active vendors' price for that service_type+area)
    and flags where they're under/over market.
    """
    try:
        professional = Professional.objects.get(user=request.user)
    except Professional.DoesNotExist:
        return Response({"status": "error", "message": "Professional profile not found."}, status=404)

    my_offerings = ProfessionalServiceType.objects.filter(
        professional=professional, is_active=True
    ).select_related("service_type").prefetch_related("area_prices")

    suggestions = []

    for o in my_offerings:
        my_areas = ProfessionalArea.objects.filter(professional=professional).values_list("area", flat=True)
        area_price_map = {ap.area: ap.price for ap in o.area_prices.all()}

        for area in my_areas:
            my_price = area_price_map.get(area, o.price)

            # Market prices: other vendors' price for same service_type in same area
            market_qs = ProfessionalServiceArea.objects.filter(
                offering__service_type=o.service_type,
                area=area,
            ).exclude(offering__professional=professional).values_list("price", flat=True)

            market_prices = list(market_qs)
            if not market_prices:
                # fallback to base prices of other vendors offering this service_type
                market_prices = list(
                    ProfessionalServiceType.objects.filter(
                        service_type=o.service_type, is_active=True
                    ).exclude(professional=professional).values_list("price", flat=True)
                )

            if not market_prices:
                continue

            market_avg = round(mean([float(p) for p in market_prices]), 2)
            diff = round(market_avg - float(my_price), 2)

            if abs(diff) < 1:
                continue  # close enough to market, no suggestion needed

            if diff > 0:
                message = (
                    f"Your {o.service_type.type_name} OMR {my_price} is market-rate. "
                    f"{area} avg is OMR {market_avg} — you could charge more there."
                )
                direction = "increase"
            else:
                message = (
                    f"Your {o.service_type.type_name} OMR {my_price} is above the "
                    f"{area} avg of OMR {market_avg} — consider lowering to stay competitive."
                )
                direction = "decrease"

            suggestions.append({
                "offering_id": o.id,
                "service_type_id": o.service_type.id,
                "service_name": o.service_type.type_name,
                "area": area,
                "your_price": str(my_price),
                "market_avg": str(market_avg),
                "direction": direction,
                "message": message,
            })

    return Response({
        "status": "success",
        "count": len(suggestions),
        "data": suggestions,
    })


# ---------------------------------------------------------------------------
# Service Areas: GET list / POST add / DELETE remove
# ---------------------------------------------------------------------------

@api_view(['GET', 'POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def vendor_service_areas(request):
    try:
        professional = Professional.objects.get(user=request.user)
    except Professional.DoesNotExist:
        return Response({"status": "error", "message": "Professional profile not found."}, status=404)

    if request.method == 'GET':
        my_areas = list(
            ProfessionalArea.objects.filter(professional=professional)
            .order_by("area")
            .values_list("area", flat=True)
        )

        # Areas available to pick from, based on the vendor's own governorate
        available_areas = sorted(set(
            Professional.objects.filter(
                governorate=professional.governorate, is_active=True
            ).exclude(area="").values_list("area", flat=True)
        ))

        # Areas not yet added by this vendor
        not_added = [a for a in available_areas if a not in my_areas]

        return Response({
            "status": "success",
            "governorate_id": professional.governorate_id,
            "governorate": professional.governorate.name if professional.governorate else None,
            "my_areas": my_areas,
            "available_areas": available_areas,
            "not_added_areas": not_added,
        })

    # POST — add a new area (must be one of the available areas for their governorate)
    area = request.data.get("area", "").strip()
    if not area:
        return Response({"status": "error", "message": "area is required."}, status=400)

    valid_areas = set(
        Professional.objects.filter(
            governorate=professional.governorate, is_active=True
        ).exclude(area="").values_list("area", flat=True)
    )

    if area not in valid_areas:
        return Response({
            "status": "error",
            "message": f"'{area}' is not a recognized area in {professional.governorate.name if professional.governorate else 'your region'}.",
            "valid_areas": sorted(valid_areas),
        }, status=400)

    obj, created = ProfessionalArea.objects.get_or_create(professional=professional, area=area)
    if not created:
        return Response({"status": "error", "message": "Area already added."}, status=409)

    return Response({"status": "success", "message": f"{area} added.", "data": area}, status=201)

@api_view(['DELETE'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def vendor_remove_service_area(request, area_name):
    try:
        professional = Professional.objects.get(user=request.user)
    except Professional.DoesNotExist:
        return Response({"status": "error", "message": "Professional profile not found."}, status=404)

    deleted, _ = ProfessionalArea.objects.filter(professional=professional, area=area_name).delete()
    if not deleted:
        return Response({"status": "error", "message": "Area not found."}, status=404)

    return Response({"status": "success", "message": f"{area_name} removed."})


def professional_working_areas(request, pk):
    """
    PUBLIC endpoint — returns the list of working/service areas for a
    SPECIFIC professional (by professional_id in the URL).
    No login required — used on customer-facing profile pages.
    """
    try:
        professional = Professional.objects.get(pk=pk, is_active=True)
    except Professional.DoesNotExist:
        return JsonResponse({
            "status": "error",
            "message": "Professional not found."
        }, status=404)

    areas = list(
        ProfessionalArea.objects.filter(professional=professional)
        .order_by("area")
        .values_list("area", flat=True)
    )

    return JsonResponse({
        "status": "success",
        "message": "Working areas fetched successfully.",
        "professional_id": professional.id,
        "professional_name": professional.name,
        "primary_area": professional.area,          # their main/HQ area
        "governorate": professional.governorate.name if professional.governorate else None,
        "count": len(areas),
        "data": areas,
    })


    
def _ai_flag(rating: int, comment: str, reviewer_booking_count: int) -> str:
    """
    Very simple heuristic AI flag — swap for a real model call if needed.
    Returns: 'likely_fake' | 'abuse_competitor' | 'genuine'
    """
    lower = (comment or '').lower()
 
    # Abuse / competitor mentions
    abuse_words = ['competitor', 'use [competitor]', 'worst', 'scam', 'fake', 'fraud']
    if any(w in lower for w in abuse_words):
        return 'abuse_competitor'
 
    # Likely fake: 5-star generic praise from brand-new account with 0 bookings
    generic_phrases = ['perfect', 'amazing in every way', 'best ever', 'absolutely']
    if rating == 5 and reviewer_booking_count == 0 and any(p in lower for p in generic_phrases):
        return 'likely_fake'
 
    return 'genuine'
 
 
def _serialize_review(review, request=None):
    photos = []
    for p in review.photos.all():
        url = request.build_absolute_uri(p.image.url) if request and p.image else ''
        photos.append({'id': p.id, 'url': url})
 
    return {
        'id': review.id,
        'booking_id': review.booking_id,
        'professional_id': review.professional_id,
        'reviewer_name': review.reviewer_name,
        'rating': review.rating,
        'comment': review.comment,
        'tags': review.tags or [],
        'photos': photos,
        'status': review.status,
        'ai_flag': review.ai_flag,
        'vendor_reply': review.vendor_reply,
        'vendor_replied_at': (
            review.vendor_replied_at.isoformat() if review.vendor_replied_at else None
        ),
        'created_at': review.created_at.strftime('%d %b %Y'),
    }
 
 
# ─────────────────────────────────────────────────────────────────────────────
# USER: Submit review for a completed booking
# POST /api/professionals/bookings/<booking_id>/review/
# Body (multipart/form-data):
#   rating        int          1-5  (required)
#   comment       str          optional
#   tags          JSON array   e.g. ["Punctual","Professional"]
#   photos        file(s)      optional, up to 3
# ─────────────────────────────────────────────────────────────────────────────
 
@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def submit_review(request, booking_id):
    """Customer submits a review for their completed booking."""
    booking = get_object_or_404(Booking, id=booking_id, user_email=request.user.email)
 
    # Only allow review after service is completed (or pending/confirmed for demo flexibility)
    # Tighten to STATUS_COMPLETED only in production:
    # if booking.status != Booking.STATUS_COMPLETED:
    #     return Response({'status': 'error', 'message': 'Can only review completed bookings.'}, status=400)
 
    # Prevent duplicate reviews
    if hasattr(booking, 'review'):
        return Response({
            'status': 'error',
            'message': 'You have already submitted a review for this booking.'
        }, status=409)
 
    # Validate rating
    try:
        rating = int(request.data.get('rating', 5))
        if not (1 <= rating <= 5):
            raise ValueError
    except (ValueError, TypeError):
        return Response({'status': 'error', 'message': 'Rating must be an integer between 1 and 5.'}, status=400)
 
    comment = (request.data.get('comment') or '').strip()
 
    # Tags: accept JSON string or list
    raw_tags = request.data.get('tags', [])
    if isinstance(raw_tags, str):
        import json
        try:
            raw_tags = json.loads(raw_tags)
        except Exception:
            raw_tags = []
    tags = [str(t) for t in raw_tags if t]
 
    # How many bookings has this reviewer made? (used for AI flag)
    reviewer_booking_count = Booking.objects.filter(user_email=request.user.email).count()
 
    # AI moderation flag
    ai_flag = _ai_flag(rating, comment, reviewer_booking_count)
 
    # Auto-publish genuine reviews; hold fake/abusive ones for admin review
    status = Review.STATUS_PUBLISHED if ai_flag == 'genuine' else Review.STATUS_PENDING
 
    review = Review.objects.create(
        booking=booking,
        professional=booking.professional,
        reviewer_name=booking.user_name,
        rating=rating,
        comment=comment,
        tags=tags,
        ai_flag=ai_flag,
        status=status,
    )
 
    # Handle photo uploads (up to 3)
    photos = request.FILES.getlist('photos')[:3]
    for photo in photos:
        ReviewPhoto.objects.create(review=review, image=photo)
 
    # Recalculate professional average rating from published reviews only
    if booking.professional:
        _update_professional_rating(booking.professional)

    if not booking.professional:
        return Response({
        'status': 'error',
        'message': 'Cannot review a booking without an assigned professional.'
    }, status=400)
 
    return Response({
        'status': 'success',
        'message': (
            'Review submitted and published.'
            if status == Review.STATUS_PUBLISHED
            else 'Review submitted and is pending admin approval.'
        ),
        'data': _serialize_review(review, request),
    }, status=201)
 

@api_view(['PATCH'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def edit_review(request, booking_id):
    """Customer edits their existing review."""
    booking = get_object_or_404(Booking, id=booking_id, user_email=request.user.email)

    # Get existing review
    if not hasattr(booking, 'review'):
        return Response({
            'status': 'error',
            'message': 'No review found for this booking.'
        }, status=404)

    review = booking.review

    # Update rating if provided
    if 'rating' in request.data:
        try:
            rating = int(request.data.get('rating'))
            if not (1 <= rating <= 5):
                raise ValueError
            review.rating = rating
        except (ValueError, TypeError):
            return Response({'status': 'error', 'message': 'Rating must be 1-5.'}, status=400)

    # Update comment if provided
    if 'comment' in request.data:
        review.comment = (request.data.get('comment') or '').strip()

    # Update tags if provided
    if 'tags' in request.data:
        raw_tags = request.data.get('tags', [])
        if isinstance(raw_tags, str):
            import json
            try:
                raw_tags = json.loads(raw_tags)
            except Exception:
                raw_tags = []
        review.tags = [str(t) for t in raw_tags if t]

    # Re-run AI flag on updated content
    reviewer_booking_count = Booking.objects.filter(user_email=request.user.email).count()
    review.ai_flag = _ai_flag(review.rating, review.comment, reviewer_booking_count)
    review.status = Review.STATUS_PUBLISHED if review.ai_flag == 'genuine' else Review.STATUS_PENDING

    review.save(update_fields=['rating', 'comment', 'tags', 'ai_flag', 'status'])

    # Handle new photos if provided
    new_photos = request.FILES.getlist('photos')
    if new_photos:
        # Delete old photos first
        review.photos.all().delete()
        for photo in new_photos[:3]:
            ReviewPhoto.objects.create(review=review, image=photo)

    # Recalculate rating
    if review.professional:
        _update_professional_rating(review.professional)

    return Response({
        'status': 'success',
        'message': 'Review updated successfully.',
        'data': _serialize_review(review, request),
    })

@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def get_booking_review(request, booking_id):
    """
    Fetch existing review details for a specific booking.
    Returns populated data if submitted, or default placeholders for the frontend.
    """
    booking = get_object_or_404(Booking, id=booking_id)

    # Optional: Verify the requesting user owns the booking
    if booking.user_email != request.user.email and not request.user.is_staff:
        return Response({
            "status": "error",
            "message": "You do not have permission to view review details for this booking."
        }, status=403)

    review = getattr(booking, 'review', None)

    if not review:
        return Response({
            "status": "success",
            "has_reviewed": False,
            "data": {
                "booking_id": booking.id,
                "professional_id": booking.professional.id if booking.professional else None,
                "professional_name": booking.professional.name if booking.professional else "",
                "reviewer_name": booking.user_name,
                "rating": 5,
                "comment": "",
                "tags": [],
                "photos": [],
                "status": None,
                "vendor_reply": None,
                "vendor_replied_at": None,
                "created_at": None,
            }
        }, status=200)

    # Serialize uploaded photos with absolute URLs
    photos = [
        {
            "id": photo.id,
            "url": request.build_absolute_uri(photo.image.url) if photo.image else ""
        }
        for photo in review.photos.all()
    ]

    return Response({
        "status": "success",
        "has_reviewed": True,
        "data": {
            "id": review.id,
            "booking_id": booking.id,
            "professional_id": booking.professional.id if booking.professional else None,
            "professional_name": booking.professional.name if booking.professional else "",
            "reviewer_name": review.reviewer_name,
            "rating": review.rating,
            "comment": review.comment,
            "tags": review.tags or [],
            "photos": photos,
            "status": review.status,
            "vendor_reply": review.vendor_reply,
            "vendor_replied_at": review.vendor_replied_at.isoformat() if review.vendor_replied_at else None,
            "created_at": review.created_at.isoformat(),
        }
    }, status=200)
# ─────────────────────────────────────────────────────────────────────────────
# VENDOR: Reply to a review
# PATCH /api/professionals/reviews/<review_id>/reply/
# Body: { "vendor_reply": "Thank you so much! Looking forward to serving you again." }
# ─────────────────────────────────────────────────────────────────────────────
 
@api_view(['PATCH'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def vendor_reply_review(request, review_id):
    """Vendor replies to a published review on their profile."""
    try:
        professional = Professional.objects.get(user=request.user)
    except Professional.DoesNotExist:
        return Response({'status': 'error', 'message': 'Professional profile not found.'}, status=404)
 
    review = get_object_or_404(Review, id=review_id, professional=professional)
 
    if review.status != Review.STATUS_PUBLISHED:
        return Response({
            'status': 'error',
            'message': 'Can only reply to published reviews.'
        }, status=400)
 
    reply_text = (request.data.get('vendor_reply') or '').strip()
    if not reply_text:
        return Response({'status': 'error', 'message': 'vendor_reply is required.'}, status=400)
 
    review.vendor_reply = reply_text
    review.vendor_replied_at = timezone.now()
    review.save(update_fields=['vendor_reply', 'vendor_replied_at'])
 
    return Response({
        'status': 'success',
        'message': 'Reply posted successfully.',
        'data': _serialize_review(review, request),
    })
 
 
# ─────────────────────────────────────────────────────────────────────────────
# VENDOR: My reviews list (Image 2)
# GET /api/professionals/vendor/reviews/
# Query params: ?status=published|pending|all  &service=<name>  &rating=<1-5>
# ─────────────────────────────────────────────────────────────────────────────
 
@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def vendor_reviews(request):
    """Returns all reviews for the logged-in vendor with rating breakdown."""
    try:
        professional = Professional.objects.get(user=request.user)
    except Professional.DoesNotExist:
        return Response({'status': 'error', 'message': 'Professional profile not found.'}, status=404)
 
    qs = Review.objects.filter(professional=professional).prefetch_related('photos')
 
    # Filter by status (default: show published + pending for vendor)
    status_filter = request.GET.get('status', 'all').lower()
    if status_filter == 'published':
        qs = qs.filter(status=Review.STATUS_PUBLISHED)
    elif status_filter == 'pending':
        qs = qs.filter(status=Review.STATUS_PENDING)
    elif status_filter != 'all':
        qs = qs.filter(status=Review.STATUS_PUBLISHED)
 
    # Filter by service name
    service_name = request.GET.get('service', '').strip()
    if service_name:
        qs = qs.filter(booking__service_type__type_name__icontains=service_name)
 
    # Filter by rating
    rating_filter = request.GET.get('rating', '').strip()
    if rating_filter.isdigit():
        qs = qs.filter(rating=int(rating_filter))
 
    # Rating breakdown (published reviews only)
    published_qs = Review.objects.filter(
        professional=professional, status=Review.STATUS_PUBLISHED
    )
    total_published = published_qs.count()
    avg_rating = published_qs.aggregate(avg=Avg('rating'))['avg'] or 0.0
 
    breakdown = {str(i): 0 for i in range(1, 6)}
    for row in published_qs.values('rating').annotate(cnt=Count('id')):
        breakdown[str(row['rating'])] = row['cnt']
 
    breakdown_pct = {
        k: round((v / total_published * 100)) if total_published else 0
        for k, v in breakdown.items()
    }
 
    reviews_data = [_serialize_review(r, request) for r in qs]
 
    return Response({
        'status': 'success',
        'professional_id': professional.id,
        'total_reviews': total_published,
        'avg_rating': round(avg_rating, 1),
        'rating_breakdown': breakdown,
        'rating_breakdown_pct': breakdown_pct,
        'count': len(reviews_data),
        'data': reviews_data,
    })
 
 
# ─────────────────────────────────────────────────────────────────────────────
# ADMIN: Moderation queue (Image 3)
# GET /api/professionals/admin/reviews/moderation/
# Query params: ?status=pending|published|removed|all  &ai_flag=likely_fake|abuse_competitor|genuine
# ─────────────────────────────────────────────────────────────────────────────
 
@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def admin_review_moderation(request):
    """Admin sees all reviews with AI flags, can filter by status / flag type."""
    qs = Review.objects.all().prefetch_related('photos').select_related('professional', 'booking')
 
    status_filter = request.GET.get('status', 'pending').lower()
    if status_filter != 'all':
        qs = qs.filter(status=status_filter)
 
    ai_flag_filter = request.GET.get('ai_flag', '').strip()
    if ai_flag_filter:
        qs = qs.filter(ai_flag=ai_flag_filter)
 
    total = Review.objects.count()
    pending_count = Review.objects.filter(status=Review.STATUS_PENDING).count()
 
    # Counts per ai_flag among pending
    flag_counts = {}
    for row in Review.objects.filter(status=Review.STATUS_PENDING).values('ai_flag').annotate(cnt=Count('id')):
        flag_counts[row['ai_flag'] or 'unknown'] = row['cnt']
 
    data = []
    for r in qs:
        booking_count = (
            Booking.objects.filter(user_email=r.booking.user_email).count()
            if r.booking else 0
        )
        entry = _serialize_review(r, request)
        entry['professional_name'] = r.professional.name if r.professional else None
        entry['reviewer_booking_count'] = booking_count
        entry['is_new_account'] = booking_count == 0
        data.append(entry)
 
    return Response({
        'status': 'success',
        'total_reviews': total,
        'pending_moderation': pending_count,
        'flag_counts': flag_counts,
        'count': len(data),
        'data': data,
    })
 
 
# ─────────────────────────────────────────────────────────────────────────────
# ADMIN: Approve / Remove a review
# PATCH /api/professionals/admin/reviews/<review_id>/moderate/
# Body: { "action": "publish" | "remove", "admin_note": "optional reason" }
# ─────────────────────────────────────────────────────────────────────────────
 
@api_view(['PATCH'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def admin_moderate_review(request, review_id):
    """Admin publishes or removes a flagged review."""
    review = get_object_or_404(Review, id=review_id)
 
    action = (request.data.get('action') or '').lower()
    if action not in ('publish', 'remove'):
        return Response({
            'status': 'error',
            'message': 'action must be "publish" or "remove".'
        }, status=400)
 
    review.status = (
        Review.STATUS_PUBLISHED if action == 'publish' else Review.STATUS_REMOVED
    )
    review.admin_note = (request.data.get('admin_note') or '').strip() or None
    review.save(update_fields=['status', 'admin_note'])
 
    # Recalculate professional's rating after any status change
    if review.professional:
        _update_professional_rating(review.professional)
 
    return Response({
        'status': 'success',
        'message': f'Review {review.status}.',
        'data': _serialize_review(review, request),
    })
 
 
# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC: Get published reviews for a professional
# GET /api/professionals/<professional_id>/reviews/
# Used on customer-facing profile page & service listing
# ─────────────────────────────────────────────────────────────────────────────
 
@api_view(['GET'])
@permission_classes([AllowAny])
def professional_reviews_public(request, pk):
    """
    Returns only PUBLISHED reviews for a professional.
    Includes vendor reply if present.
    """
    professional = get_object_or_404(Professional, pk=pk, is_active=True)
 
    qs = Review.objects.filter(
        professional=professional,
        status=Review.STATUS_PUBLISHED
    ).prefetch_related('photos')
 
    total = qs.count()
    avg = qs.aggregate(avg=Avg('rating'))['avg'] or 0.0
 
    breakdown = {str(i): 0 for i in range(1, 6)}
    for row in qs.values('rating').annotate(cnt=Count('id')):
        breakdown[str(row['rating'])] = row['cnt']
 
    breakdown_pct = {
        k: round((v / total * 100)) if total else 0
        for k, v in breakdown.items()
    }
 
    data = [_serialize_review(r, request) for r in qs]
 
    return Response({
        'status': 'success',
        'professional_id': professional.id,
        'professional_name': professional.name,
        'total_reviews': total,
        'avg_rating': round(avg, 1),
        'rating_breakdown': breakdown,
        'rating_breakdown_pct': breakdown_pct,
        'count': len(data),
        'data': data,
    })
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Internal helper
# ─────────────────────────────────────────────────────────────────────────────
 
def _update_professional_rating(professional: Professional):
    """Recalculates and saves the professional's rating from published reviews only."""
    result = Review.objects.filter(
        professional=professional,
        status=Review.STATUS_PUBLISHED
    ).aggregate(avg=Avg('rating'))
    
    new_avg = round(result['avg'] or 5.0, 1)
    Professional.objects.filter(pk=professional.pk).update(rating=new_avg)

    
def _parse_month(month_str):
    """
    Parse 'YYYY-MM' into (date_start, date_end).
    Falls back to current month if blank / invalid.
    """
    today = timezone.localdate()
    if month_str:
        try:
            year, month = [int(p) for p in month_str.split("-")]
            start = date(year, month, 1)
        except (ValueError, AttributeError):
            start = today.replace(day=1)
    else:
        start = today.replace(day=1)
 
    # last day of the month
    next_month = (start.replace(day=28) + timedelta(days=4))
    end = next_month.replace(day=1) - timedelta(days=1)
    return start, end
 
 
def _month_label(d: date) -> str:
    return d.strftime("%B %Y")          # e.g. "July 2026"
 
 
def _pct_change(new_val, old_val):
    """Return percentage change string, e.g. '↑ 23%' or '↓ 5%'."""
    if not old_val:
        return None
    change = ((new_val - old_val) / old_val) * 100
    arrow = "↑" if change >= 0 else "↓"
    return f"{arrow} {abs(round(change, 1))}%"
 
 
def _revenue_last_n_days(queryset, days=7):
    """
    Return list of {day_label, revenue} for the last `days` days,
    ordered Mon → Sun relative to today.
    """
    today = timezone.localdate()
    # align to the most-recent Monday
    monday = today - timedelta(days=today.weekday())
 
    result = []
    for i in range(days):
        d = monday + timedelta(days=i)
        day_qs = queryset.filter(booking_date=d, status=Booking.STATUS_COMPLETED)
        revenue = day_qs.aggregate(s=Sum("total_amount"))["s"] or Decimal("0")
        result.append({
            "day_label": d.strftime("%a")[0],   # M, T, W …
            "date": d.isoformat(),
            "revenue": float(round(revenue, 3)),
        })
    return result
 
 
def _jobs_by_category(queryset):
    """
    Return list of {category, icon_emoji, percentage} sorted desc,
    derived from completed bookings.
    """
    SERVICE_ICONS = {
        "AC Service": "❄️",
        "Electrical": "⚡",
        "Plumbing": "🔧",
        "Appliance": "🏠",
        "Cleaning": "🧹",
        "Beauty": "💅",
    }
    rows = (
        queryset
        .filter(status=Booking.STATUS_COMPLETED)
        .values(cat_name=models_F("service_type__service__name"))
        .annotate(cnt=Count("id"))
        .order_by("-cnt")
    )
    total = sum(r["cnt"] for r in rows) or 1
    return [
        {
            "category": r["cat_name"] or "Other",
            "icon": SERVICE_ICONS.get(r["cat_name"] or "", "🔩"),
            "count": r["cnt"],
            "percentage": round(r["cnt"] / total * 100),
        }
        for r in rows
    ]
 
 
# We need django.db.models.F — alias to avoid shadowing built-in
from django.db.models import F as models_F
 
 
# ---------------------------------------------------------------------------
# ── VENDOR ANALYTICS  (Image 1)
# GET /api/analytics/vendor/?month=YYYY-MM&ai=on
# ---------------------------------------------------------------------------
 
@api_view(["GET"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def vendor_analytics(request):
    """
    Vendor-facing analytics dashboard.
 
    Returns
    -------
    - ai_insight          : str | None        — banner shown when ai=on
    - month_label         : str               — e.g. "July 2026"
    - kpis.revenue        : {value, change}
    - kpis.jobs           : {value, change}
    - kpis.rating         : {value, review_count}
    - kpis.completion     : {value_pct, market_avg_pct}
    - revenue_last_7_days : [{day_label, date, revenue}]
    - jobs_by_category    : [{category, icon, count, percentage}]
    """
    try:
        professional = Professional.objects.get(user=request.user)
    except Professional.DoesNotExist:
        return Response(
            {"status": "error", "message": "Professional profile not found."},
            status=404,
        )
 
    month_str  = request.GET.get("month", "")
    ai_enabled = request.GET.get("ai", "on").lower() != "off"
 
    start, end = _parse_month(month_str)
 
    # Previous month window (for Δ % change)
    prev_end   = start - timedelta(days=1)
    prev_start = prev_end.replace(day=1)
 
    base_qs   = Booking.objects.filter(professional=professional)
    month_qs  = base_qs.filter(booking_date__range=(start, end))
    prev_qs   = base_qs.filter(booking_date__range=(prev_start, prev_end))
 
    # ── KPIs ──────────────────────────────────────────────────────────────
    revenue_curr = (
        month_qs.filter(status=Booking.STATUS_COMPLETED)
        .aggregate(s=Sum("total_amount"))["s"] or Decimal("0")
    )
    revenue_prev = (
        prev_qs.filter(status=Booking.STATUS_COMPLETED)
        .aggregate(s=Sum("total_amount"))["s"] or Decimal("0")
    )
 
    jobs_curr = month_qs.filter(status=Booking.STATUS_COMPLETED).count()
    jobs_prev = prev_qs.filter(status=Booking.STATUS_COMPLETED).count()
 
    # Completion rate = completed / (completed + cancelled)  × 100
    done_curr      = month_qs.filter(status=Booking.STATUS_COMPLETED).count()
    cancelled_curr = month_qs.filter(status=Booking.STATUS_CANCELLED).count()
    denom_curr     = done_curr + cancelled_curr or 1
    completion_pct = round(done_curr / denom_curr * 100)
 
    # Market-wide completion rate (all professionals, same month)
    mkt_done   = Booking.objects.filter(
        booking_date__range=(start, end), status=Booking.STATUS_COMPLETED
    ).count()
    mkt_cancel = Booking.objects.filter(
        booking_date__range=(start, end), status=Booking.STATUS_CANCELLED
    ).count()
    mkt_denom  = mkt_done + mkt_cancel or 1
    market_avg_completion = round(mkt_done / mkt_denom * 100)
 
    # Rating from published reviews
    avg_rating   = float(professional.rating)
    review_count = Review.objects.filter(
        professional=professional, status=Review.STATUS_PUBLISHED
    ).count()
 
    # ── Revenue last 7 days ───────────────────────────────────────────────
    revenue_chart = _revenue_last_n_days(base_qs)
 
    # ── Jobs by category ─────────────────────────────────────────────────
    jobs_cat = _jobs_by_category(month_qs)
 
    # ── AI insight ────────────────────────────────────────────────────────
    ai_insight = None
    if ai_enabled:
        ai_insight = _build_vendor_ai_insight(
            professional, month_qs, completion_pct, market_avg_completion
        )
 
    return Response({
        "status":       "success",
        "month_label":  _month_label(start),
        "ai_enabled":   ai_enabled,
        "ai_insight":   ai_insight,
        "kpis": {
            "revenue": {
                "value":    float(round(revenue_curr, 3)),
                "currency": "OMR",
                "change":   _pct_change(float(revenue_curr), float(revenue_prev)),
            },
            "jobs": {
                "value":  jobs_curr,
                "change": _pct_change(jobs_curr, jobs_prev),
            },
            "rating": {
                "value":        avg_rating,
                "review_count": review_count,
            },
            "completion": {
                "value_pct":      completion_pct,
                "market_avg_pct": market_avg_completion,
            },
        },
        "revenue_last_7_days": revenue_chart,
        "jobs_by_category":    jobs_cat,
    })
 
 
def _build_vendor_ai_insight(professional, month_qs, completion_pct, market_avg_pct):
    """
    Generate the AI banner shown at the top of the Vendor Analytics screen.
    Mirrors the example in Image 1:
      "Completion rate 98% vs market avg 91%.
       Fri–Sat peak demand — add slots.
       Bowsher has 12 unmatched AC bookings — expand coverage there for more revenue."
    """
    parts = []
 
    # 1. Completion vs market
    parts.append(
        f"Completion rate {completion_pct}% vs market avg {market_avg_pct}%."
    )
 
    # 2. Peak-day detection (find the 2 busiest booking days in the month)
    day_counts = (
        month_qs
        .values("booking_date")
        .annotate(cnt=Count("id"))
        .order_by("-cnt")[:2]
    )
    if day_counts:
        day_names = sorted({
            date.fromisoformat(str(r["booking_date"])).strftime("%a")
            for r in day_counts
        })
        if day_names:
            parts.append(
                f"{'–'.join(day_names)} peak demand — add slots."
            )
 
    # 3. Unmatched bookings in vendor's areas that they could cover
    vendor_service_type_ids = list(
        ProfessionalServiceType.objects.filter(
            professional=professional, is_active=True
        ).values_list("service_type_id", flat=True)
    )
 
    unmatched_count = Booking.objects.filter(
        professional__isnull=True,
        service_type_id__in=vendor_service_type_ids,
    ).exclude(status=Booking.STATUS_CANCELLED).count()
 
    if unmatched_count:
        # Find the area with the most unmatched bookings
        top_area_row = (
            Booking.objects.filter(
                professional__isnull=True,
                service_type_id__in=vendor_service_type_ids,
            )
            .exclude(status=Booking.STATUS_CANCELLED)
            .values("area")
            .annotate(cnt=Count("id"))
            .order_by("-cnt")
            .first()
        )
        area_label = top_area_row["area"] if top_area_row else "your area"
        parts.append(
            f"{area_label} has {unmatched_count} unmatched bookings "
            f"— expand coverage there for more revenue."
        )
 
    return " ".join(parts) if parts else None
 
 
# ---------------------------------------------------------------------------
# ── ADMIN ANALYTICS  (Image 2)
# GET /api/analytics/admin/?month=YYYY-MM&ai=on
# ---------------------------------------------------------------------------
 
@api_view(["GET"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def admin_analytics(request):
    """
    Admin-facing AI analytics dashboard.
 
    Returns
    -------
    - ai_weekly_banner      : str | None
    - month_label           : str
    - revenue_90_days       : [{date, revenue, is_forecast}]
    - demand_by_service     : [{service, icon, percentage}]
    - ai_churn_alerts       : {high_risk, medium_risk, recovered_risk}
    """
    month_str  = request.GET.get("month", "")
    ai_enabled = request.GET.get("ai", "on").lower() != "off"
 
    start, end = _parse_month(month_str)
 
    # ── Revenue: 60 actual days + 30 forecast days ────────────────────────
    revenue_90 = _build_revenue_90_days(end)
 
    # ── Demand by service (all bookings in the month) ─────────────────────
    demand_rows = (
        Booking.objects
        .filter(booking_date__range=(start, end))
        .exclude(status=Booking.STATUS_CANCELLED)
        .values(service_name=models_F("service_type__service__name"))
        .annotate(cnt=Count("id"))
        .order_by("-cnt")
    )
    SERVICE_ICONS_ADMIN = {
        "AC":           "❄️",
        "AC Service":   "❄️",
        "Cleaning":     "🧹",
        "Plumbing":     "🔧",
        "Electrical":   "⚡",
        "Beauty":       "💅",
    }
    total_demand = sum(r["cnt"] for r in demand_rows) or 1
 
    demand_by_service = []
    others_pct = 0
    for i, r in enumerate(demand_rows):
        pct = round(r["cnt"] / total_demand * 100)
        name = r["service_name"] or "Other"
        if i < 5:
            demand_by_service.append({
                "service":    name,
                "icon":       SERVICE_ICONS_ADMIN.get(name, "🔩"),
                "count":      r["cnt"],
                "percentage": pct,
            })
        else:
            others_pct += pct
 
    if others_pct:
        demand_by_service.append({
            "service":    "Others",
            "icon":       "📦",
            "count":      None,
            "percentage": others_pct,
        })
 
    # ── AI Churn Alerts ───────────────────────────────────────────────────
    churn_alerts = _build_churn_alerts()
 
    # ── AI Weekly banner ──────────────────────────────────────────────────
    ai_weekly_banner = None
    if ai_enabled:
        ai_weekly_banner = _build_admin_ai_weekly(start, end)
 
    return Response({
        "status":           "success",
        "month_label":      _month_label(start),
        "ai_enabled":       ai_enabled,
        "ai_weekly_banner": ai_weekly_banner,
        "revenue_90_days":  revenue_90,
        "demand_by_service": demand_by_service,
        "ai_churn_alerts":  churn_alerts,
    })
 
 
def _build_revenue_90_days(period_end: date):
    """
    Returns 60 days of actual completed-booking revenue
    PLUS 30 days of simple linear-trend forecast.
    Each entry: {date, revenue, is_forecast}
    """
    actual_start = period_end - timedelta(days=59)
 
    # Aggregate actual revenue per day
    rows = (
        Booking.objects
        .filter(
            booking_date__range=(actual_start, period_end),
            status=Booking.STATUS_COMPLETED,
        )
        .values("booking_date")
        .annotate(rev=Sum("total_amount"))
        .order_by("booking_date")
    )
    rev_map = {r["booking_date"]: float(r["rev"] or 0) for r in rows}
 
    actual_series = []
    for i in range(60):
        d = actual_start + timedelta(days=i)
        actual_series.append({
            "date":        d.isoformat(),
            "revenue":     round(rev_map.get(d, 0), 3),
            "is_forecast": False,
        })
 
    # Simple linear forecast: use avg of last 14 actual days as baseline,
    # apply a small growth factor per day
    last_14 = [p["revenue"] for p in actual_series[-14:] if p["revenue"] > 0]
    baseline = sum(last_14) / len(last_14) if last_14 else 0
    growth_per_day = baseline * 0.005   # 0.5% daily growth assumption
 
    forecast_series = []
    for i in range(1, 31):
        d = period_end + timedelta(days=i)
        forecast_val = round(baseline + growth_per_day * i, 3)
        forecast_series.append({
            "date":        d.isoformat(),
            "revenue":     forecast_val,
            "is_forecast": True,
        })
 
    return actual_series + forecast_series
 
 
def _build_churn_alerts():
    """
    Classify all active professionals into churn risk tiers.
 
    High Risk    : 0 completed bookings in last 18 days
    Medium Risk  : 0 completed bookings in last 32 days (but not high-risk)
    Recovered    : had 0 bookings 14+ days ago, now has bookings in last 7 days
    """
    today = timezone.localdate()
 
    all_pros = Professional.objects.filter(is_active=True)
 
    high_risk      = []
    medium_risk    = []
    recovered_risk = []
 
    for pro in all_pros:
        jobs_last_7  = Booking.objects.filter(
            professional=pro,
            booking_date__gte=today - timedelta(days=7),
            status=Booking.STATUS_COMPLETED,
        ).count()
 
        jobs_last_18 = Booking.objects.filter(
            professional=pro,
            booking_date__gte=today - timedelta(days=18),
            status=Booking.STATUS_COMPLETED,
        ).count()
 
        jobs_last_32 = Booking.objects.filter(
            professional=pro,
            booking_date__gte=today - timedelta(days=32),
            status=Booking.STATUS_COMPLETED,
        ).count()
 
        days_since = None
        last_booking = (
            Booking.objects.filter(
                professional=pro, status=Booking.STATUS_COMPLETED
            )
            .order_by("-booking_date")
            .first()
        )
        if last_booking:
            days_since = (today - last_booking.booking_date).days
 
        if jobs_last_18 == 0:
            label = f"0 jobs in {days_since if days_since else 18}+ days"
            high_risk.append({
                "professional_id":   pro.id,
                "professional_name": pro.name,
                "label":             label,
                "days_inactive":     days_since,
                "action":            "send_retention_offer",
            })
        elif jobs_last_32 == 0:
            label = f"No booking {days_since if days_since else 32} days"
            medium_risk.append({
                "professional_id":   pro.id,
                "professional_name": pro.name,
                "label":             label,
                "days_inactive":     days_since,
                "action":            "send_nudge",
            })
        elif jobs_last_7 > 0 and days_since is not None and days_since < 7:
            # Was inactive (no bookings between day-14 and day-7) but now active
            was_inactive = Booking.objects.filter(
                professional=pro,
                booking_date__range=(today - timedelta(days=14), today - timedelta(days=8)),
                status=Booking.STATUS_COMPLETED,
            ).count() == 0
 
            if was_inactive:
                recovered_risk.append({
                    "professional_id":   pro.id,
                    "professional_name": pro.name,
                    "label":             "Re-engaged via AI push",
                    "days_inactive":     None,
                    "action":            None,
                })
 
    return {
        "high_risk":      high_risk[:5],
        "medium_risk":    medium_risk[:5],
        "recovered_risk": recovered_risk[:5],
    }
 
 
def _build_admin_ai_weekly(start: date, end: date):
    """
    Compose the AI Weekly banner string shown in Image 2:
    "Bookings ↑118% vs last week. AC demand peaking. 3 vendors risk churn —
     0 bookings in 14+ days. Bowsher underserved — 38 unmatched bookings last
     7 days. Recommend recruiting 4 more AC techs."
    """
    today   = timezone.localdate()
    parts   = []
 
    # 1. Booking volume vs last week
    this_week_start = today - timedelta(days=today.weekday())
    last_week_start = this_week_start - timedelta(days=7)
    last_week_end   = this_week_start - timedelta(days=1)
 
    bookings_this = Booking.objects.filter(
        booking_date__gte=this_week_start
    ).exclude(status=Booking.STATUS_CANCELLED).count()
 
    bookings_last = Booking.objects.filter(
        booking_date__range=(last_week_start, last_week_end)
    ).exclude(status=Booking.STATUS_CANCELLED).count()
 
    if bookings_last > 0:
        pct = round((bookings_this - bookings_last) / bookings_last * 100)
        arrow = "↑" if pct >= 0 else "↓"
        parts.append(f"Bookings {arrow}{abs(pct)}% vs last week.")
 
    # 2. Peaking service
    top_service = (
        Booking.objects.filter(
            booking_date__range=(today - timedelta(days=7), today)
        )
        .exclude(status=Booking.STATUS_CANCELLED)
        .values(name=models_F("service_type__service__name"))
        .annotate(cnt=Count("id"))
        .order_by("-cnt")
        .first()
    )
    if top_service:
        parts.append(f"{top_service['name']} demand peaking.")
 
    # 3. Churn risk count
    churn_count = Professional.objects.filter(is_active=True).count()
    high_churn  = 0
    for pro in Professional.objects.filter(is_active=True):
        jobs = Booking.objects.filter(
            professional=pro,
            booking_date__gte=today - timedelta(days=14),
            status=Booking.STATUS_COMPLETED,
        ).count()
        if jobs == 0:
            high_churn += 1
 
    if high_churn:
        parts.append(
            f"{high_churn} vendor{'s' if high_churn > 1 else ''} risk churn "
            f"— 0 bookings in 14+ days."
        )
 
    # 4. Most underserved area (unmatched bookings)
    unmatched_by_area = (
        Booking.objects.filter(
            professional__isnull=True,
            booking_date__gte=today - timedelta(days=7),
        )
        .exclude(status=Booking.STATUS_CANCELLED)
        .values("area")
        .annotate(cnt=Count("id"))
        .order_by("-cnt")
        .first()
    )
    if unmatched_by_area:
        area = unmatched_by_area["area"]
        cnt  = unmatched_by_area["cnt"]
        parts.append(
            f"{area} underserved — {cnt} unmatched bookings last 7 days."
        )
 
        # 5. Recruitment suggestion: top service in that area
        top_svc = (
            Booking.objects.filter(
                professional__isnull=True,
                booking_date__gte=today - timedelta(days=7),
                area=area,
            )
            .exclude(status=Booking.STATUS_CANCELLED)
            .values(name=models_F("service_type__service__name"))
            .annotate(cnt=Count("id"))
            .order_by("-cnt")
            .first()
        )
        if top_svc:
            needed = max(1, round(cnt / 10))   # rough heuristic
            parts.append(
                f"Recommend recruiting {needed} more "
                f"{top_svc['name']} tech{'s' if needed > 1 else ''}."
            )
 
    return " ".join(parts) if parts else None
 
 
# ---------------------------------------------------------------------------
# ── ADMIN ANALYTICS: Retention Action
# POST /api/analytics/admin/churn/<professional_id>/retention/
# ---------------------------------------------------------------------------
 
@api_view(["POST"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def admin_send_retention_offer(request, professional_id):
    """
    Trigger a retention offer for a high-risk vendor.
    In production this would fire an SMS/email/push notification.
    Returns a confirmation payload.
    """
    try:
        pro = Professional.objects.get(pk=professional_id, is_active=True)
    except Professional.DoesNotExist:
        return Response(
            {"status": "error", "message": "Professional not found."},
            status=404,
        )
 
    # ── placeholder: hook your notification service here ──
    # e.g. send_sms(pro.phone, "We miss you! Here's a 10% bonus on your next job.")
 
    return Response({
        "status":  "success",
        "message": f"Retention offer sent to {pro.name} ({pro.phone or pro.email or 'no contact'}).",
        "data": {
            "professional_id":   pro.id,
            "professional_name": pro.name,
            "phone":             pro.phone,
            "action_taken":      "retention_offer_sent",
        },
    })
 
 
# ---------------------------------------------------------------------------
# ── ADMIN ANALYTICS: Summary KPIs
# GET /api/analytics/admin/kpis/?month=YYYY-MM
# ---------------------------------------------------------------------------
 
@api_view(["GET"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def admin_kpis(request):
    """
    High-level KPIs for the admin header/summary row.
 
    Returns
    -------
    - total_revenue, total_bookings, active_vendors,
      avg_rating, completion_rate, unmatched_bookings
    Each with optional change vs previous month.
    """
    month_str = request.GET.get("month", "")
    start, end = _parse_month(month_str)
 
    prev_end   = start - timedelta(days=1)
    prev_start = prev_end.replace(day=1)
 
    def _bqs(s, e):
        return Booking.objects.filter(booking_date__range=(s, e))
 
    curr_qs = _bqs(start, end)
    prev_qs = _bqs(prev_start, prev_end)
 
    # Revenue
    rev_curr = curr_qs.filter(status=Booking.STATUS_COMPLETED).aggregate(
        s=Sum("total_amount")
    )["s"] or Decimal("0")
    rev_prev = prev_qs.filter(status=Booking.STATUS_COMPLETED).aggregate(
        s=Sum("total_amount")
    )["s"] or Decimal("0")
 
    # Bookings
    bk_curr = curr_qs.exclude(status=Booking.STATUS_CANCELLED).count()
    bk_prev = prev_qs.exclude(status=Booking.STATUS_CANCELLED).count()
 
    # Active vendors (had at least 1 booking in the month)
    av_curr = (
        curr_qs.exclude(status=Booking.STATUS_CANCELLED)
        .values("professional")
        .distinct()
        .count()
    )
 
    # Avg rating across all professionals
    avg_rating = Professional.objects.filter(is_active=True).aggregate(
        avg=Avg("rating")
    )["avg"] or 0.0
 
    # Completion rate
    done   = curr_qs.filter(status=Booking.STATUS_COMPLETED).count()
    cancel = curr_qs.filter(status=Booking.STATUS_CANCELLED).count()
    denom  = done + cancel or 1
    comp_pct = round(done / denom * 100)
 
    # Unmatched / unassigned bookings
    unmatched = Booking.objects.filter(
        professional__isnull=True
    ).exclude(status__in=[Booking.STATUS_CANCELLED, Booking.STATUS_COMPLETED]).count()
 
    return Response({
        "status":      "success",
        "month_label": _month_label(start),
        "kpis": {
            "total_revenue": {
                "value":    float(round(rev_curr, 3)),
                "currency": "OMR",
                "change":   _pct_change(float(rev_curr), float(rev_prev)),
            },
            "total_bookings": {
                "value":  bk_curr,
                "change": _pct_change(bk_curr, bk_prev),
            },
            "active_vendors":  av_curr,
            "avg_rating":      round(float(avg_rating), 1),
            "completion_rate": comp_pct,
            "unmatched_bookings": unmatched,
        },
    })

    
PLATFORM_FEE_PCT = Decimal("15")   # 15% platform fee shown in the UI subtitle
 
 
def _parse_month(month_str):
    """Return (start_date, end_date) for a 'YYYY-MM' string; defaults to current month."""
    today = timezone.localdate()
    if month_str:
        try:
            year, month = [int(p) for p in month_str.split("-")]
            start = date(year, month, 1)
        except (ValueError, AttributeError):
            start = today.replace(day=1)
    else:
        start = today.replace(day=1)
 
    next_month = (start.replace(day=28) + timedelta(days=4))
    end = next_month.replace(day=1) - timedelta(days=1)
    return start, end
 
 
def _net(gross: Decimal) -> Decimal:
    """Deduct platform fee and return net amount (3 d.p.)."""
    fee = (gross * PLATFORM_FEE_PCT / 100).quantize(Decimal("0.001"), rounding=ROUND_DOWN)
    return (gross - fee).quantize(Decimal("0.001"))
 
 
def _date_label(booking_date: date) -> str:
    today = timezone.localdate()
    if booking_date == today:
        return "Today"
    if booking_date == today - timedelta(days=1):
        return "Yesterday"
    return booking_date.strftime("%-d %b")   # e.g. "8 Jul"
 
 
def _serialize_transaction(booking: Booking) -> dict:
    gross = booking.total_amount or Decimal("0")
    net   = _net(gross)
 
    # Payment / settlement status
    if booking.status == Booking.STATUS_COMPLETED:
        if booking.payment_method == "cash_on_completion":
            payout_status = "pending"
        else:
            payout_status = "paid"
    elif booking.status == Booking.STATUS_CANCELLED:
        payout_status = "cancelled"
    else:
        payout_status = "pending"
 
    return {
        "booking_id":    booking.id,
        "booking_code":  booking.booking_code,
        "service":       booking.service_type.type_name if booking.service_type else "",
        "area":          booking.area,
        "service_area":  f"{booking.service_type.type_name if booking.service_type else ''} · {booking.area}",
        "date":          booking.booking_date.isoformat(),
        "date_label":    _date_label(booking.booking_date),
        "gross":         f"OMR {gross}",
        "gross_value":   float(gross),
        "net_paid":      f"OMR {net}",
        "net_value":     float(net),
        "status":        payout_status,          # paid | pending | cancelled
    }
 
 
# ---------------------------------------------------------------------------
# GET /api/payments/vendor/summary/
# ---------------------------------------------------------------------------
 
@api_view(["GET"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def vendor_payment_summary(request):
    """
    Returns the 4 KPI cards + bank account card shown at the top of the screen.
 
    KPIs
    ----
    revenue      – total gross of completed bookings this month
    net_earnings – revenue minus platform fee
    platform_fee – the deducted amount
    pending      – gross of completed bookings not yet settled (cash_on_completion)
 
    Bank account card
    -----------------
    bank_name, account_name, iban, is_verified, settlement_info
    """
    try:
        professional = Professional.objects.get(user=request.user)
    except Professional.DoesNotExist:
        return Response({"status": "error", "message": "Professional profile not found."}, status=404)
 
    month_str    = request.GET.get("month", "")
    start, end   = _parse_month(month_str)
 
    completed_qs = Booking.objects.filter(
        professional=professional,
        booking_date__range=(start, end),
        status=Booking.STATUS_COMPLETED,
    )
 
    revenue = completed_qs.aggregate(s=Sum("total_amount"))["s"] or Decimal("0")
    fee     = (revenue * PLATFORM_FEE_PCT / 100).quantize(Decimal("0.001"), rounding=ROUND_DOWN)
    net     = (revenue - fee).quantize(Decimal("0.001"))
 
    # Pending = completed + cash_on_completion (not yet wired)
    pending = completed_qs.filter(
        payment_method="cash_on_completion"
    ).aggregate(s=Sum("total_amount"))["s"] or Decimal("0")
    pending_net = _net(pending)
 
    # Bank account
    try:
        bank = VendorBankAccount.objects.get(professional=professional, is_primary=True)
        bank_data = {
            "bank_name":       bank.bank_name,
            "account_name":    bank.account_name,
            "iban":            bank.iban,
            "is_verified":     bank.is_verified,
            "is_primary":      True,
            "settlement_info": "T+1 settlement",
        }
    except VendorBankAccount.DoesNotExist:
        bank_data = None
 
    month_label = date(start.year, start.month, 1).strftime("%B %Y")
 
    return Response({
        "status":       "success",
        "month_label":  month_label,
        "platform_fee_pct": float(PLATFORM_FEE_PCT),
        "settlement":   "T+1",
        "kpis": {
            "revenue": {
                "label":    "Revenue",
                "value":    f"OMR {revenue}",
                "amount":   float(revenue),
                "subtitle": "This month",
            },
            "net_earnings": {
                "label":    "Net Earnings",
                "value":    f"OMR {net}",
                "amount":   float(net),
                "subtitle": f"After {int(PLATFORM_FEE_PCT)}% fee",
            },
            "platform_fee": {
                "label":    "Platform Fee",
                "value":    f"OMR {fee}",
                "amount":   float(fee),
                "subtitle": "Deducted",
            },
            "pending": {
                "label":    "Pending",
                "value":    f"OMR {pending_net}",
                "amount":   float(pending_net),
                "subtitle": "Settled T+1",
            },
        },
        "bank_account": bank_data,
    })
 
 
# ---------------------------------------------------------------------------
# GET /api/payments/vendor/transactions/
# ---------------------------------------------------------------------------
 
@api_view(["GET"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def vendor_transactions(request):
    """
    Paginated list of Recent Transactions for the vendor.
 
    Query params
    ------------
    month      YYYY-MM   filter by month (default: current month)
    status     paid | pending | cancelled   optional filter
    page       int        default 1
    page_size  int        default 10
    """
    try:
        professional = Professional.objects.get(user=request.user)
    except Professional.DoesNotExist:
        return Response({"status": "error", "message": "Professional profile not found."}, status=404)
 
    month_str  = request.GET.get("month", "")
    start, end = _parse_month(month_str)
 
    qs = Booking.objects.filter(
        professional=professional,
        booking_date__range=(start, end),
    ).exclude(status=Booking.STATUS_CANCELLED).select_related(
        "service_type", "service_type__service"
    ).order_by("-booking_date", "-booking_time")
 
    # Optional status filter (maps UI pill to booking statuses)
    status_filter = request.GET.get("status", "").lower()
    if status_filter == "paid":
        qs = qs.filter(
            status=Booking.STATUS_COMPLETED
        ).exclude(payment_method="cash_on_completion")
    elif status_filter == "pending":
        qs = qs.filter(
            Q(status=Booking.STATUS_COMPLETED, payment_method="cash_on_completion") |
            Q(status__in=[
                Booking.STATUS_CONFIRMED,
                Booking.STATUS_PENDING,
                Booking.STATUS_EN_ROUTE,
                Booking.STATUS_ARRIVED,
                Booking.STATUS_IN_PROGRESS,
            ])
        )
 
    page_number = request.GET.get("page", 1)
    page_size   = int(request.GET.get("page_size", 10))
    paginator   = Paginator(qs, page_size)
    page_obj    = paginator.get_page(page_number)
 
    def _page_url(num):
        if not num:
            return None
        p = request.GET.copy()
        p["page"] = num
        p["page_size"] = page_size
        return f"{request.path}?{p.urlencode()}"
 
    return Response({
        "status":       "success",
        "month_label":  date(start.year, start.month, 1).strftime("%B %Y"),
        "count":        len(page_obj.object_list),
        "total_count":  paginator.count,
        "total_pages":  paginator.num_pages,
        "current_page": page_obj.number,
        "page_size":    page_size,
        "next":         _page_url(page_obj.next_page_number() if page_obj.has_next() else None),
        "previous":     _page_url(page_obj.previous_page_number() if page_obj.has_previous() else None),
        "data": [_serialize_transaction(b) for b in page_obj],
    })
 
 
# ---------------------------------------------------------------------------
# POST /api/payments/vendor/payout/request/
# ---------------------------------------------------------------------------
 
@api_view(["POST"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def vendor_request_payout(request):
    """
    "Request Payout" button handler.
 
    Body (optional)
    ---------------
    month   YYYY-MM   defaults to current month if omitted
 
    Returns
    -------
    Payout request record with amount, status, and ETA.
    """
    try:
        professional = Professional.objects.get(user=request.user)
    except Professional.DoesNotExist:
        return Response({"status": "error", "message": "Professional profile not found."}, status=404)
 
    # Must have a verified bank account
    try:
        bank = VendorBankAccount.objects.get(professional=professional, is_primary=True, is_verified=True)
    except VendorBankAccount.DoesNotExist:
        return Response({
            "status":  "error",
            "message": "No verified bank account found. Please add and verify your bank account first.",
        }, status=400)
 
    month_str  = request.data.get("month", "")
    start, end = _parse_month(month_str)
 
    # Calculate net payable (completed bookings, not yet in a payout request)
    already_requested_ids = PayoutRequest.objects.filter(
        professional=professional,
        status__in=["pending", "processing", "paid"],
    ).values_list("booking_ids", flat=True)
 
    # Flatten the list of booking id lists
    excluded_ids = set()
    for id_list in already_requested_ids:
        if id_list:
            excluded_ids.update(id_list)
 
    eligible_qs = Booking.objects.filter(
        professional=professional,
        booking_date__range=(start, end),
        status=Booking.STATUS_COMPLETED,
    ).exclude(id__in=excluded_ids)
 
    gross = eligible_qs.aggregate(s=Sum("total_amount"))["s"] or Decimal("0")
    net   = _net(gross)
    fee   = (gross - net).quantize(Decimal("0.001"))
 
    if net <= 0:
        return Response({
            "status":  "error",
            "message": "No eligible earnings available for payout this month.",
        }, status=400)
 
    booking_ids = list(eligible_qs.values_list("id", flat=True))
 
    payout = PayoutRequest.objects.create(
        professional  = professional,
        month_start   = start,
        month_end     = end,
        gross_amount  = gross,
        platform_fee  = fee,
        net_amount    = net,
        bank_account  = bank,
        booking_ids   = booking_ids,
        status        = "pending",
    )
 
    eta = timezone.localdate() + timedelta(days=1)   # T+1
 
    return Response({
        "status":  "success",
        "message": f"Payout of OMR {net} requested successfully. Expected by {eta.strftime('%-d %b %Y')}.",
        "data": {
            "payout_id":     payout.id,
            "month":         date(start.year, start.month, 1).strftime("%B %Y"),
            "gross_amount":  f"OMR {gross}",
            "platform_fee":  f"OMR {fee}",
            "net_amount":    f"OMR {net}",
            "status":        payout.status,
            "eta":           eta.isoformat(),
            "bank": {
                "bank_name":    bank.bank_name,
                "account_name": bank.account_name,
                "iban":         bank.iban,
            },
        },
    }, status=201)
 
 
# ---------------------------------------------------------------------------
# GET / POST  /api/payments/vendor/bank-account/
# ---------------------------------------------------------------------------
 
@api_view(["GET", "POST"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def vendor_bank_account(request):
    """
    GET  — Return the vendor's saved bank accounts.
    POST — Add or update (upsert) the primary bank account.
 
    POST body
    ---------
    bank_name     str   e.g. "Bank of Muscat"
    account_name  str   e.g. "Mohammed Al-Balushi"
    iban          str   e.g. "OM80 0001 0000 2345 6789"
    """
    try:
        professional = Professional.objects.get(user=request.user)
    except Professional.DoesNotExist:
        return Response({"status": "error", "message": "Professional profile not found."}, status=404)
 
    if request.method == "GET":
        accounts = VendorBankAccount.objects.filter(professional=professional)
        data = [
            {
                "id":           a.id,
                "bank_name":    a.bank_name,
                "account_name": a.account_name,
                "iban":         a.iban,
                "is_primary":   a.is_primary,
                "is_verified":  a.is_verified,
            }
            for a in accounts
        ]
        return Response({"status": "success", "count": len(data), "data": data})
 
    # POST — upsert primary account
    bank_name    = (request.data.get("bank_name") or "").strip()
    account_name = (request.data.get("account_name") or "").strip()
    iban         = (request.data.get("iban") or "").strip().upper().replace(" ", "")
 
    if not all([bank_name, account_name, iban]):
        return Response({
            "status":  "error",
            "message": "bank_name, account_name, and iban are all required.",
        }, status=400)
 
    # Basic Oman IBAN format check: starts with OM, 23 chars
    if not (iban.startswith("OM") and len(iban) == 23):
        return Response({
            "status":  "error",
            "message": "Invalid Oman IBAN. Must start with 'OM' and be 23 characters long.",
        }, status=400)
 
    # Format for display: OM80 0001 0000 2345 6789
    formatted_iban = " ".join([iban[i:i+4] for i in range(0, len(iban), 4)])
 
    account, created = VendorBankAccount.objects.update_or_create(
        professional=professional,
        is_primary=True,
        defaults={
            "bank_name":    bank_name,
            "account_name": account_name,
            "iban":         formatted_iban,
            "is_verified":  False,   # resets verification on any change
        },
    )
 
    return Response({
        "status":  "success",
        "message": "Bank account saved. Verification is pending." if created else "Bank account updated. Re-verification required.",
        "data": {
            "id":           account.id,
            "bank_name":    account.bank_name,
            "account_name": account.account_name,
            "iban":         account.iban,
            "is_primary":   account.is_primary,
            "is_verified":  account.is_verified,
        },
    }, status=201 if created else 200)
 
 
# ---------------------------------------------------------------------------
# PATCH /api/payments/vendor/bank-account/<id>/verify/
# Admin-only: mark a bank account as verified
# ---------------------------------------------------------------------------
 
@api_view(["PATCH"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def admin_verify_bank_account(request, account_id):
    """Admin marks a vendor's bank account as verified."""
    try:
        account = VendorBankAccount.objects.get(id=account_id)
    except VendorBankAccount.DoesNotExist:
        return Response({"status": "error", "message": "Bank account not found."}, status=404)
 
    account.is_verified = True
    account.save(update_fields=["is_verified"])
 
    return Response({
        "status":  "success",
        "message": f"Bank account for {account.professional.name} verified.",
        "data": {
            "id":          account.id,
            "bank_name":   account.bank_name,
            "iban":        account.iban,
            "is_verified": account.is_verified,
        },
    })
 
 
# ---------------------------------------------------------------------------
# GET /api/payments/vendor/payout/history/
# ---------------------------------------------------------------------------
 
@api_view(["GET"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def vendor_payout_history(request):
    """Returns list of all payout requests for the vendor."""
    try:
        professional = Professional.objects.get(user=request.user)
    except Professional.DoesNotExist:
        return Response({"status": "error", "message": "Professional profile not found."}, status=404)
 
    payouts = PayoutRequest.objects.filter(professional=professional).order_by("-created_at")
 
    data = [
        {
            "id":           p.id,
            "month":        p.month_start.strftime("%B %Y"),
            "gross_amount": f"OMR {p.gross_amount}",
            "platform_fee": f"OMR {p.platform_fee}",
            "net_amount":   f"OMR {p.net_amount}",
            "status":       p.status,
            "requested_at": p.created_at.isoformat(),
            "bank": {
                "bank_name": p.bank_account.bank_name if p.bank_account else None,
                "iban":      p.bank_account.iban if p.bank_account else None,
            },
        }
        for p in payouts
    ]
 
    return Response({"status": "success", "count": len(data), "data": data})