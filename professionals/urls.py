from django.urls import path
from . import views
from .views import (
    vendor_booking_list,
    vendor_my_services,
    admin_all_bookings,
    admin_booking_control_assign,
    vendor_services_pricing,
    vendor_update_service_price,
    vendor_toggle_service_status,
    # vendor_add_service,
    vendor_ai_pricing_suggestions,
    vendor_service_areas,
    vendor_remove_service_area,
    professional_working_areas,
    vendor_service_categories,
    vendor_add_or_edit_service
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

    path("<int:pk>/services/", views.professional_services_by_id, name="professional_services_by_id"),
    path("bookings/<int:booking_id>/available-professionals/", views.booking_available_professionals, name="booking_available_professionals"),
    # Vendor API
    path("vendor/bookings/", vendor_booking_list, name="vendor_booking_list"),
    path("vendor/services/", vendor_my_services, name="vendor_my_services"),
    path("vendor/services-pricing/", vendor_services_pricing, name="vendor_services_pricing"),
    # path("vendor/services/add/", vendor_add_service, name="vendor_add_service"),
    path("vendor/services/<int:offering_id>/price/", vendor_update_service_price, name="vendor_update_price"),
    path("vendor/services/<int:offering_id>/status/", vendor_toggle_service_status, name="vendor_toggle_status"),
    path("vendor/services/ai-pricing/", vendor_ai_pricing_suggestions, name="vendor_ai_pricing"),
    path("vendor/areas/", vendor_service_areas, name="vendor_service_areas"),
    path("vendor/areas/<str:area_name>/", vendor_remove_service_area, name="vendor_remove_area"),
    path("<int:pk>/working-areas/", professional_working_areas, name="professional_working_areas"),
    path("vendor/services/categories/", vendor_service_categories, name="vendor_service_categories"),
    path("vendor/services/add/", vendor_add_or_edit_service, name="vendor_add_service"),
    path("vendor/services/<int:offering_id>/edit/", vendor_add_or_edit_service, name="vendor_edit_service"),


    # Admin APIs
    path("admin/bookings/", admin_all_bookings, name="admin_all_bookings"),
    path("admin/bookings/assign/", admin_booking_control_assign, name="admin_booking_assign"),
    path("admin/bookings/<int:booking_id>/assign/", admin_booking_control_assign, name="admin_booking_assign_detail"),
]