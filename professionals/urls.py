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

from .views import (
    submit_review,
    vendor_reply_review,
    vendor_reviews,
    admin_review_moderation,
    admin_moderate_review,
    professional_reviews_public,
    edit_review,
)
from .views import (
    vendor_analytics,
    admin_analytics,
    admin_kpis,
    admin_send_retention_offer,
)
from .views import (
    vendor_payment_summary,
    vendor_transactions,
    vendor_request_payout,
    vendor_bank_account,
    admin_verify_bank_account,
    vendor_payout_history,
)
from .views import (
    admin_payments_summary,
    admin_customer_payments,
    admin_vendor_payouts,
    admin_platform_revenue,
    admin_refunds,
    admin_payments_export,
)
from .views import (
    vendor_live_map,
    vendor_update_location,
    vendor_credits,
    vendor_upgrade_plan,
    admin_adjust_credits,
)

from .views import (
    vendor_settings_view,
    vendor_settings_update_profile,
    vendor_settings_update_availability,
    vendor_toggle_online_status,
    vendor_settings_update_notifications,
)
from .views import platform_config_view, toggle_payment_gateway, toggle_integration
from professionals import views as pro_views
from .views import (
    admin_vendor_verification_list,
    admin_vendor_verification_profile,
    admin_vendor_verification_approve,
    admin_vendor_verification_reject,
    admin_vendor_verification_request_docs,
    admin_vendor_verification_contact,
)
from .views import (
    admin_credits_plans_summary,
    admin_vendor_credit_detail,
    admin_grant_credits,
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

     # ── NEW review endpoints ─────────────────────────────────────────────────
 
    # USER: submit review (with optional photo upload) for a specific booking
    # POST  /api/professionals/bookings/<booking_id>/review/
    path("bookings/<int:booking_id>/review/", submit_review, name="submit_review"),
 
    # VENDOR: reply to a review
    # PATCH /api/professionals/reviews/<review_id>/reply/
    path("reviews/<int:review_id>/reply/", vendor_reply_review, name="vendor_reply_review"),
 
    # VENDOR: see all own reviews with rating breakdown
    # GET   /api/professionals/vendor/reviews/
    path("vendor/reviews/", vendor_reviews, name="vendor_reviews"),
 
    # ADMIN: moderation queue (AI-flagged reviews)
    # GET   /api/professionals/admin/reviews/moderation/
    path("admin/reviews/moderation/", admin_review_moderation, name="admin_review_moderation"),
 
    # ADMIN: approve or remove a specific review
    # PATCH /api/professionals/admin/reviews/<review_id>/moderate/
    path("admin/reviews/<int:review_id>/moderate/", admin_moderate_review, name="admin_moderate_review"),
 
    # PUBLIC: customer-facing published reviews for a professional
    # GET   /api/professionals/<pk>/reviews/
    path("<int:pk>/reviews/", professional_reviews_public, name="professional_reviews_public"),
    path("bookings/<int:booking_id>/review/edit/", views.edit_review, name="edit_review"),
    path("bookings/<int:booking_id>/review/detail/", views.get_booking_review, name="get_booking_review"),

    # ── Vendor Dashboard (Image 1) ─────────────────────────────────────────
    # GET /api/analytics/vendor/?month=YYYY-MM&ai=on
    path("vendor/", vendor_analytics, name="vendor_analytics"),
 
    # ── Admin Dashboard (Image 2) ──────────────────────────────────────────
    # GET /api/analytics/admin/?month=YYYY-MM&ai=on
    path("admin/", admin_analytics, name="admin_analytics"),
 
    # GET /api/analytics/admin/kpis/?month=YYYY-MM
    path("admin/kpis/", admin_kpis, name="admin_kpis"),
 
    # POST /api/analytics/admin/churn/<professional_id>/retention/
    path(
        "admin/churn/<int:professional_id>/retention/",
        admin_send_retention_offer,
        name="admin_send_retention_offer",
    ),

      # 4 KPI cards + bank account card
    # GET /api/payments/vendor/summary/?month=2026-07
    path("vendor/summary/", vendor_payment_summary, name="vendor_payment_summary"),
 
    # Recent Transactions table (paginated)
    # GET /api/payments/vendor/transactions/?month=2026-07&status=paid&page=1
    path("vendor/transactions/", vendor_transactions, name="vendor_transactions"),
 
    # "Request Payout" button
    # POST /api/payments/vendor/payout/request/
    path("vendor/payout/request/", vendor_request_payout, name="vendor_request_payout"),
 
    # Payout history list
    # GET /api/payments/vendor/payout/history/
    path("vendor/payout/history/", vendor_payout_history, name="vendor_payout_history"),
 
    # Bank account — GET list / POST add-or-update
    # GET  /api/payments/vendor/bank-account/
    # POST /api/payments/vendor/bank-account/
    path("vendor/bank-account/", vendor_bank_account, name="vendor_bank_account"),
 
    # ── Admin ─────────────────────────────────────────────────────────────
 
    # Mark a bank account as verified
    # PATCH /api/payments/admin/bank-account/<id>/verify/
    path(
        "admin/bank-account/<int:account_id>/verify/",
        admin_verify_bank_account,
        name="admin_verify_bank_account",
    ),
    path("admin/payments/summary/", admin_payments_summary, name="admin_payments_summary"),
    path("admin/payments/customer/", admin_customer_payments, name="admin_customer_payments"),
    path("admin/payments/vendor-payouts/", admin_vendor_payouts, name="admin_vendor_payouts"),
    path("admin/payments/platform-revenue/", admin_platform_revenue, name="admin_platform_revenue"),
    path("admin/payments/refunds/", admin_refunds, name="admin_refunds"),
    path("admin/payments/export/", admin_payments_export, name="admin_payments_export"),
    # ── Live Map ──────────────────────────────────────────────────────────────────
# GET  /api/professionals/vendor/live-map/
path("vendor/live-map/",    vendor_live_map,         name="vendor_live_map"),
# PATCH /api/professionals/vendor/location/
path("vendor/location/",    vendor_update_location,  name="vendor_update_location"),

# ── Credits & Plans ───────────────────────────────────────────────────────────
# GET  /api/professionals/vendor/credits/
path("vendor/credits/",             vendor_credits,       name="vendor_credits"),
# POST /api/professionals/vendor/credits/upgrade/
path("vendor/credits/upgrade/",     vendor_upgrade_plan,  name="vendor_upgrade_plan"),
# POST /api/professionals/admin/credits/adjust/
path("admin/credits/adjust/",       admin_adjust_credits, name="admin_adjust_credits"),


    path("vendor/settings/", vendor_settings_view, name="vendor_settings_view"),
    path("vendor/settings/profile/", vendor_settings_update_profile, name="vendor_settings_update_profile"),
    path("vendor/settings/availability/", vendor_settings_update_availability, name="vendor_settings_update_availability"),
    path("vendor/settings/online-status/", vendor_toggle_online_status, name="vendor_toggle_online_status"),
    path("vendor/settings/notifications/", vendor_settings_update_notifications, name="vendor_settings_update_notifications"),

    path("payment-gateways/<int:pk>/", toggle_payment_gateway, name="toggle_payment_gateway"),
    path("integrations/<int:pk>/", toggle_integration, name="toggle_integration"),

    path("platform-settings/", pro_views.platform_config_view, name="platform_config"),
    path("platform-settings/payment-gateways/<int:pk>/", pro_views.toggle_payment_gateway),
    path("platform-settings/integrations/<int:pk>/", pro_views.toggle_integration),

    path("admin/vendor-verification/", admin_vendor_verification_list, name="admin_vendor_verification_list"),
    path("admin/vendor-verification/<int:professional_id>/profile/", admin_vendor_verification_profile, name="admin_vendor_verification_profile"),
    path("admin/vendor-verification/<int:professional_id>/approve/", admin_vendor_verification_approve, name="admin_vendor_verification_approve"),
    path("admin/vendor-verification/<int:professional_id>/reject/", admin_vendor_verification_reject, name="admin_vendor_verification_reject"),
    path("admin/vendor-verification/<int:professional_id>/request-docs/", admin_vendor_verification_request_docs, name="admin_vendor_verification_request_docs"),
    path("admin/vendor-verification/<int:professional_id>/contact/", admin_vendor_verification_contact, name="admin_vendor_verification_contact"),

    path("admin/credits-plans/", admin_credits_plans_summary, name="admin_credits_plans_summary"),
    path("admin/credits-plans/<int:professional_id>/", admin_vendor_credit_detail, name="admin_vendor_credit_detail"),
    path("admin/credits-plans/grant/", admin_grant_credits, name="admin_grant_credits"),
]


