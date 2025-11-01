"""
Views package for the main Django app.

All views are imported here to maintain backward compatibility with urls.py
"""

# Import multi-step check-in views from separate file
from main.checkin_views import (
    checkin_step1,
    checkin_details,
    checkin_parking,
    checkin_confirm,
    checkin_pin_status,
    checkin_error
)

# Alias for backward compatibility
checkin = checkin_step1

# Base utilities
from .base import unauthorized, get_available_rooms

# Public views
from .public import (
    home,
    awards_reviews,
    about,
    explore_manchester,
    contact,
    rebook_guest,
    privacy_policy,
    terms_of_use,
    terms_conditions,
    cookie_policy,
    sitemap,
    how_to_use,
    event_finder,
    price_suggester,
    event_detail,
)

# Guest views
from .guest import (
    checkin_legacy,
    enrich_reservation,
    room_detail,
    report_pin_issue,
)

# Admin dashboard
from .admin_dashboard import (
    AdminLoginView,
    admin_page,
    available_rooms,
    all_reservations,
    delete_reservation,
    bulk_delete_reservations,
    past_guests,
)

# Admin guest management
from .admin_guests import (
    edit_guest,
    edit_reservation,
    manual_checkin_reservation,
    delete_guest,
    manage_checkin_checkout,
    guest_details,
    block_review_messages,
    admin_id_uploads,
)

# Admin room management
from .admin_rooms import (
    room_management,
    edit_room,
    give_access,
)

# Admin user management
from .admin_users import (
    user_management,
    audit_logs,
)

# Enrichment workflow
from .enrichment import (
    xls_upload_page,
    pending_enrichments_page,
    enrichment_logs_page,
    message_templates,
)

# Webhooks
from .webhooks import (
    ttlock_callback,
    sms_reply_handler,
    handle_twilio_sms_webhook,
)

# Export all
__all__ = [
    # Base
    'unauthorized',
    'get_available_rooms',
    # Public
    'home',
    'awards_reviews',
    'about',
    'explore_manchester',
    'contact',
    'rebook_guest',
    'privacy_policy',
    'terms_of_use',
    'terms_conditions',
    'cookie_policy',
    'sitemap',
    'how_to_use',
    'event_finder',
    'price_suggester',
    'event_detail',
    # Guest
    'checkin_legacy',
    'enrich_reservation',
    'room_detail',
    'report_pin_issue',
    # Admin dashboard
    'AdminLoginView',
    'admin_page',
    'available_rooms',
    'all_reservations',
    'delete_reservation',
    'bulk_delete_reservations',
    'past_guests',
    # Admin guests
    'edit_guest',
    'edit_reservation',
    'manual_checkin_reservation',
    'delete_guest',
    'manage_checkin_checkout',
    'guest_details',
    'block_review_messages',
    'admin_id_uploads',
    # Admin rooms
    'room_management',
    'edit_room',
    'give_access',
    # Admin users
    'user_management',
    'audit_logs',
    # Enrichment
    'xls_upload_page',
    'pending_enrichments_page',
    'enrichment_logs_page',
    'message_templates',
    # Webhooks
    'ttlock_callback',
    'sms_reply_handler',
    'handle_twilio_sms_webhook',
]
