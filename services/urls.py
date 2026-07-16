from django.urls import path
from .views import (
    service_list, 
    my_bookings, 
    track_booking, 
    rate_booking, 
    booking_receipt, 
    download_receipt_pdf
)

urlpatterns = [
    path("", service_list, name="service_list"),
    path("bookings/", my_bookings, name="my_bookings_list"),
    path("bookings/<int:booking_id>/track/", track_booking, name="track_booking_live"),
    path("bookings/<int:booking_id>/rate/", rate_booking, name="rate_booking_review"),
    path("bookings/<int:booking_id>/receipt/", booking_receipt, name="booking_receipt_data"),
    path("bookings/<int:booking_id>/receipt/pdf/", download_receipt_pdf, name="download_receipt_pdf_file"),
]