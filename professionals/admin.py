from django.contrib import admin
from .models import Professional, ProfessionalServiceType, Review, Booking

@admin.register(Professional)
class ProfessionalAdmin(admin.ModelAdmin):
    list_display = ('name', 'specialty', 'governorate', 'area', 'rating', 'jobs_done', 'is_active')
    list_filter = ('is_active', 'governorate', 'area')
    search_fields = ('name', 'specialty', 'area', 'phone')

@admin.register(ProfessionalServiceType)
class ProfessionalServiceTypeAdmin(admin.ModelAdmin):
    list_display = ('professional', 'service_type', 'price', 'is_active')
    list_filter = ('is_active', 'service_type')
    search_fields = ('professional__name', 'service_type__type_name')

@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ('professional', 'reviewer_name', 'rating', 'created_at')
    list_filter = ('rating',)
    search_fields = ('professional__name', 'reviewer_name', 'comment')

@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ('booking_code', 'user_name', 'user_email', 'professional', 'booking_date', 'booking_time', 'status', 'total_amount')
    list_filter = ('status', 'payment_method', 'booking_date')
    search_fields = ('booking_code', 'user_name', 'user_email', 'user_mobile')
    readonly_fields = ('booking_code', 'created_at', 'updated_at')