from django.urls import path
from . import views

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
]