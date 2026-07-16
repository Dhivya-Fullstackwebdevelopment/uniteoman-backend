from datetime import datetime, timedelta, date as date_cls
import json
import random
import string

from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from services.models import Service, ServiceType
from services.models import Booking as ServiceBooking  # Imported for auto-syncing
from .models import Professional, ProfessionalServiceType, Review, Booking

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
    """Bottom banner note shown under the AI Top Picks panel, e.g.
    'AI: Mohammed is ideal — highest AC score, 0 cancellations, available today. Avg wait: 22 min.'
    """
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
    # (used when the user has multiple "Choose a Service" checkboxes selected)
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

    # Calculate exact Badge counter labels dynamically based on clean requirements.
    # NOTE: base_qs is taken AFTER the service_id / service_type_id filter above,
    # so count_all correctly reflects "pros available" for whatever service(s)
    # are currently selected on the frontend (e.g. "312 pros available").
    base_qs = professionals
    count_all = base_qs.count()
    count_available_today = base_qs.filter(next_available_date=timezone.localdate()).count()
    count_top_rated = base_qs.filter(rating__gte=4.5).count()  # Displays high ratings count
    count_nearest = base_qs.filter(distance_km__lte=5.0).count()

    # Chip Filtering Logic handling both direct subsets and sort updates.
    # This must run BEFORE list(professionals) below, since .filter() only
    # works on querysets, not on plain Python lists.
    if sort == "available_today":
        professionals = professionals.filter(next_available_date=timezone.localdate())
    elif sort == "top_rated":
        professionals = professionals.filter(rating__gte=4.5)
    elif sort == "nearest":
        professionals = professionals.filter(distance_km__lte=5.0)

    # Secondary Filter overrides (Sidebar parameters)
    # exact match on rating (e.g. ?rating=4.9)
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

    # Order processing depending on current sorting chip.
    # NOTE: sorting is done in Python (not via .order_by() on the queryset) because
    # the queryset already has .distinct() applied from the service_type_id join filter.
    # Combining .distinct() with .order_by() on a different field is unreliable across
    # databases (e.g. Postgres requires ORDER BY fields to match DISTINCT fields) — this
    # was why "nearest" and "lowest_price" sometimes silently ignored the requested order.
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

    # Render top matches (AI Top Picks panel)
    ranked = sorted(professionals, key=lambda p: p.ai_match_score(service_type), reverse=True)[:3]
    ai_top_picks = []
    for idx, p in enumerate(ranked):
        card = serialize_professional_card(p, service_type, request, service_type_ids)
        card["is_best"] = idx == 0
        card["ai_match_note"] = build_ai_match_note(p)
        ai_top_picks.append(card)

    # Bottom AI summary banner, e.g.
    # "AI: Mohammed is ideal — highest AC score, 0 cancellations, available today. Avg wait: 22 min."
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

    # Optional diagnostics: ?debug=1
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

    # service_type ids this professional offers -> used to find how many other
    # pros offer the SAME service(s), and to build the AI Top Picks panel.
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
# POST /api/bookings/create/ (Sync Integrated Natively Here)
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

    clash = Booking.objects.filter(
        professional=pro,
        booking_date=booking_date,
        booking_time=booking_time,
        status__in=[Booking.STATUS_PENDING, Booking.STATUS_CONFIRMED],
    ).exists()
    if clash:
        return JsonResponse({"status": "error", "message": "This time slot is no longer available."}, status=409)

    # 1. Save booking in the professional app
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

    # 2. AUTO-SYNC: Mirror record completely into the services app booking table
    from django.utils.timezone import make_aware

    combined_datetime = datetime.combine(booking.booking_date, booking.booking_time)
    if combined_datetime.tzinfo is None:
        combined_datetime = make_aware(combined_datetime)

    ServiceBooking.objects.create(
        booking_number=booking.booking_code,
        user_id=1,  # Standard architectural fallback profile ID map
        service_type=booking.service_type,
        professional_id=booking.professional.id,
        scheduled_at=combined_datetime,
        duration_minutes=45,
        location_name=booking.area,
        address=f"{booking.villa_apartment_no}, {booking.street_name}, {booking.nearest_landmark}".strip(', '),
        status=booking.status.upper(),
        service_fee=booking.service_fee,
        platform_fee=booking.platform_fee,
        vat=booking.vat_amount,
        total_paid=booking.total_amount,
        payment_method=booking.get_payment_method_display()
    )

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