from datetime import datetime, timedelta, date as date_cls
import json
import random
import string
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from services.models import Service, ServiceType
from .models import Professional, ProfessionalServiceType, Review, Booking
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
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
    """
    Returns the list of services / service-types the LOGGED-IN professional
    (identified via JWT token, not a query param) currently offers,
    grouped by parent Service category, with each offering's own price.

    Optional: ?category_id=<Service id> to filter to one category.
    """
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

    # Group offerings by parent Service (category)
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
            "price": str(o.price),          # vendor's own price for this type
            "default_price": str(st.price), # platform default, for comparison
            "is_active": o.is_active,
        })

    data = list(grouped.values())
    total_service_types = sum(len(g["service_types"]) for g in data)

    return Response({
        "status": "success",
        "message": "Services offered by this professional fetched successfully.",
        "professional_id": professional.id,
        "professional_name": professional.name,
        "categories_count": len(data),
        "service_types_count": total_service_types,
        "data": data
    })


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