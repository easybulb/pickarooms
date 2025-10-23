# main/urls.py
from django.urls import path
from . import views
from django.contrib.auth.views import LogoutView
from .views import (
    privacy_policy, terms_of_use, terms_conditions,
    cookie_policy, sitemap
)
from .views import how_to_use
from .views import report_pin_issue
from main.views import ttlock_callback

urlpatterns = [
    path('', views.home, name='home'),
    path('about/', views.about, name='about'),
    path('checkin/', views.checkin, name='checkin'),
    path('enrich-reservation/', views.enrich_reservation, name='enrich_reservation'),
    path('room/<str:room_token>/', views.room_detail, name='room_detail'),
    path("report_pin_issue/", report_pin_issue, name="report_pin_issue"),
    path("rebook/", views.rebook_guest, name="rebook_guest"),
    path('explore-manchester/', views.explore_manchester, name='explore_manchester'),
    path('contact/', views.contact, name='contact'),
    path('admin-page/', views.admin_page, name='admin_page'),
    path('admin-page/login/', views.AdminLoginView.as_view(), name='admin_login'),
    path('logout/', LogoutView.as_view(next_page='/'), name='logout'),
    path('unauthorized/', views.unauthorized, name='unauthorized'),
    path('admin-page/edit-guest/<int:guest_id>/', views.edit_guest, name='edit_guest'),
    path('admin-page/edit-reservation/<int:reservation_id>/', views.edit_reservation, name='edit_reservation'),
    path('admin-page/manual-checkin/<int:reservation_id>/', views.manual_checkin_reservation, name='manual_checkin_reservation'),
    path('admin-page/manage-checkin-checkout/<int:guest_id>/', views.manage_checkin_checkout, name='manage_checkin_checkout'),
    path('admin-page/delete-guest/<int:guest_id>/', views.delete_guest, name='delete_guest'),
    path('admin-page/available-rooms/', views.available_rooms, name='available_rooms'),
    path('admin-page/give-access/', views.give_access, name='give_access'),
    path('admin-page/user-management/', views.user_management, name='user_management'),
    path('room-management/', views.room_management, name='room_management'),
    path('edit-room/<int:room_id>/', views.edit_room, name='edit_room'),
    path('admin-page/past-guests/', views.past_guests, name='past_guests'),
    path('admin-page/all-reservations/', views.all_reservations, name='all_reservations'),
    path('admin-page/delete-reservation/<int:reservation_id>/', views.delete_reservation, name='delete_reservation'),
    path('admin-page/bulk-delete-reservations/', views.bulk_delete_reservations, name='bulk_delete_reservations'),
    path('admin-page/message-templates/', views.message_templates, name='message_templates'),
    path('privacy-policy/', privacy_policy, name='privacy_policy'),
    path('terms-of-use/', terms_of_use, name='terms_of_use'),
    path('terms-and-conditions/', terms_conditions, name='terms_conditions'),
    path('cookie-policy/', cookie_policy, name='cookie_policy'),
    path('sitemap/', sitemap, name='sitemap'),
    path('how-to-use/', how_to_use, name='how_to_use'),
    path('awards_reviews/', views.awards_reviews, name='awards_reviews'),
    path('sms-reply/', views.sms_reply_handler, name='sms_reply_handler'),
    path('api/callback', ttlock_callback, name='ttlock_callback'),
    path('audit-logs/', views.audit_logs, name='audit_logs'),
    path('admin-page/guest-details/<int:guest_id>/', views.guest_details, name='guest_details'),
    path('block-review-messages/', views.block_review_messages, name='block_review_messages'),
    path('event-finder/', views.event_finder, name='event_finder'),
    path('price-suggester/', views.price_suggester, name='price_suggester'),

    # Email Enrichment System URLs
    path('webhooks/twilio/sms/', views.handle_twilio_sms_webhook, name='twilio_sms_webhook'),
    path('admin-page/pending-enrichments/', views.pending_enrichments_page, name='pending_enrichments_page'),
    path('admin-page/xls-upload/', views.xls_upload_page, name='xls_upload_page'),
    path('admin-page/enrichment-logs/', views.enrichment_logs_page, name='enrichment_logs_page'),
]