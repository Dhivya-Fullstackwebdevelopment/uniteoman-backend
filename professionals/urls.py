from django.urls import path
from . import views
from .views import (
    vendor_booking_list,
    admin_all_bookings,
    admin_booking_control_assign,
)

urlpatterns = [
    # Professional List + Filters
    path("", views.professional_list),

    # Professional Details
    path("<int:pk>/", views.professional_detail),

    # Available Slots
    path("<int:pk>/slots/", views.professional_slots),

    # Area List
    path("areas/", views.area_list),

    # Service Types
    path("service-types/", views.service_type_list),

    # Bookings
    path("bookings/create/", views.booking_create),
    path("bookings/<int:pk>/", views.booking_detail),
    path("bookings/<int:pk>/confirm/", views.booking_confirm),
    path("bookings/<int:pk>/cancel/", views.booking_cancel),
    path("bookings/<int:pk>/reschedule/", views.reschedule_booking, name="reschedule_booking_api"),
    path("bookings/<int:pk>/book-again/", views.booking_book_again, name="booking_book_again"),

    # Vendor API
    path("vendor/bookings/", vendor_booking_list, name="vendor_booking_list"),

    # Admin APIs
    path("admin/bookings/", admin_all_bookings, name="admin_all_bookings"),
    path("admin/bookings/assign/", admin_booking_control_assign, name="admin_booking_assign"),
    path("admin/bookings/<int:booking_id>/assign/", admin_booking_control_assign, name="admin_booking_assign_detail"),
]