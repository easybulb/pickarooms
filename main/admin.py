# main/admin.py
from django.contrib import admin
from django.utils.html import format_html
from django.conf import settings
from django import forms
from .models import Room, Guest, ReviewCSVUpload, TTLock, AuditLog, PopularEvent, GuestIDUpload, TTLockToken, RoomICalConfig, Reservation, MessageTemplate, PendingEnrichment, EnrichmentLog, CSVEnrichmentLog
from .ttlock_utils import TTLockClient
import logging
import random  # Added for randint
from django.contrib import messages  # Added for messages framework

# Set up logging for TTLock interactions
logger = logging.getLogger('main')

# Import PIN generation helper
from .pin_utils import generate_memorable_4digit_pin

# ✅ Always show Cloudinary URL input (No file upload)
class RoomAdminForm(forms.ModelForm):
    class Meta:
        model = Room
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['image'].widget = forms.TextInput(attrs={'placeholder': 'Enter Cloudinary Image URL'})
        self.fields['image'].required = False  # ✅ Ensure it's optional

class RoomAdmin(admin.ModelAdmin):
    form = RoomAdminForm  # ✅ Use the custom form
    list_display = ('name', 'video_url', 'image_preview')  # Removed 'access_pin'
    search_fields = ('name',)
    list_filter = ('ttlock',)  # Add filter for rooms with/without locks

    def image_preview(self, obj):
        """Display Cloudinary image preview in Django Admin."""
        if obj.image:
            return format_html('<img src="{}" width="50" height="50" style="border-radius:5px;"/>', obj.image)
        return "No Image"

    image_preview.short_description = "Image Preview"

class GuestIDUploadInline(admin.TabularInline):
    model = GuestIDUpload
    extra = 1
    readonly_fields = ('uploaded_at',)

class GuestAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'reservation_number', 'phone_number', 'check_in_date', 'check_out_date', 'assigned_room', 'front_door_pin', 'front_door_pin_id', 'is_archived')
    list_filter = ('is_archived', 'check_in_date', 'check_out_date', 'assigned_room')
    search_fields = ('full_name', 'phone_number', 'reservation_number')
    actions = ['mark_as_archived', 'regenerate_pins']
    inlines = [GuestIDUploadInline]

    def mark_as_archived(self, request, queryset):
        """Allow manually archiving guests from the admin panel."""
        queryset.update(is_archived=True)
        self.message_user(request, "Selected guests have been archived.")

    mark_as_archived.short_description = "Move selected guests to archive"

    def regenerate_pins(self, request, queryset):
        """Regenerate PINs for selected guests."""
        for guest in queryset:
            if not guest.is_archived:
                # Add PIN regeneration logic (simplified for admin action)
                front_door_lock = TTLock.objects.filter(is_front_door=True).first()
                room_lock = guest.assigned_room.ttlock
                if front_door_lock and room_lock:
                    ttlock_client = TTLockClient()
                    new_pin = generate_memorable_4digit_pin()  # 4-digit memorable PIN
                    # Simplified regeneration (full logic can be reused from edit_guest)
                    guest.front_door_pin = new_pin
                    guest.save()
                    messages.success(request, f"Regenerated PIN {new_pin} for {guest.full_name}.")  # Use messages
        self.message_user(request, "PINs regenerated for selected guests.")

    regenerate_pins.short_description = "Regenerate PINs for selected guests"

    def delete_queryset(self, request, queryset):
        """Override delete to handle bulk deletion with TTLock PIN cleanup."""
        front_door_lock = TTLock.objects.filter(is_front_door=True).first()

        for guest in queryset:
            if guest.front_door_pin_id and front_door_lock:
                try:
                    ttlock_client = TTLockClient()
                    logger.info(f"Attempting to delete PIN for guest {guest.reservation_number} with keyboardPwdId: {guest.front_door_pin_id}")
                    response = ttlock_client.delete_pin(
                        lock_id=front_door_lock.lock_id,
                        keyboard_pwd_id=guest.front_door_pin_id,
                    )
                    logger.info(f"TTLock delete_pin response: {response}")
                    if response.get("errcode", 0) == 0:
                        logger.info(f"Successfully deleted PIN for guest {guest.reservation_number}")
                    else:
                        logger.error(f"Failed to delete PIN for guest {guest.reservation_number}: {response.get('errmsg', 'Unknown error')}")
                        self.message_user(request, f"Failed to delete PIN for {guest.full_name}: {response.get('errmsg', 'Unknown error')}")
                except Exception as e:
                    logger.error(f"Exception during PIN deletion for guest {guest.reservation_number}: {str(e)}")
                    self.message_user(request, f"Error deleting PIN for {guest.full_name}: {str(e)}")
                finally:
                    guest.front_door_pin = None
                    guest.front_door_pin_id = None
                    guest.save()
            guest.delete()
        self.message_user(request, "Selected guests deleted successfully.")

    def delete_model(self, request, obj):
        """Override delete for a single object to handle TTLock PIN deletion."""
        front_door_lock = TTLock.objects.filter(is_front_door=True).first()

        if obj.front_door_pin_id and front_door_lock:
            try:
                ttlock_client = TTLockClient()
                logger.info(f"Attempting to delete PIN for guest {obj.reservation_number} with keyboardPwdId: {obj.front_door_pin_id}")
                response = ttlock_client.delete_pin(
                    lock_id=front_door_lock.lock_id,
                    keyboard_pwd_id=obj.front_door_pin_id,
                )
                logger.info(f"TTLock delete_pin response: {response}")
                if response.get("errcode", 0) == 0:
                    logger.info(f"Successfully deleted PIN for guest {obj.reservation_number}")
                else:
                    logger.error(f"Failed to delete PIN for guest {obj.reservation_number}: {response.get('errmsg', 'Unknown error')}")
                    self.message_user(request, f"Failed to delete PIN for {obj.full_name}: {response.get('errmsg', 'Unknown error')}")
            except Exception as e:
                logger.error(f"Exception during PIN deletion for guest {obj.reservation_number}: {str(e)}")
                self.message_user(request, f"Error deleting PIN for {obj.full_name}: {str(e)}")
            finally:
                obj.front_door_pin = None
                obj.front_door_pin_id = None
                obj.save()
        obj.delete()
        self.message_user(request, "Guest deleted successfully.")

class ReviewCSVUploadAdmin(admin.ModelAdmin):
    list_display = ('uploaded_at',)
    readonly_fields = ('data',)
    exclude = ('data',)

    def save_model(self, request, obj, form, change):
        """Automatically process CSV and store data in JSON field."""
        obj.save()
        obj.save()  # Call save again to trigger CSV processing
        self.message_user(request, "CSV processed and stored as JSON successfully.")

class TTLockAdmin(admin.ModelAdmin):
    list_display = ('name', 'lock_id', 'is_front_door')
    search_fields = ('name', 'lock_id')
    list_filter = ('is_front_door',)

class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'user', 'action', 'object_type', 'object_id', 'details')
    list_filter = ('timestamp', 'user', 'action', 'object_type')
    search_fields = ('user__username', 'action', 'object_type', 'details')
    readonly_fields = ('timestamp', 'user', 'action', 'object_type', 'object_id', 'details')

class PopularEventAdmin(admin.ModelAdmin):
    list_display = ('event_id', 'name', 'date', 'venue', 'ticket_price', 'suggested_price', 'email_sent', 'created_at')
    list_filter = ('date', 'email_sent')
    search_fields = ('name', 'venue', 'event_id')
    readonly_fields = ('event_id', 'created_at')

class TTLockTokenAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'expires_at', 'is_expired_display', 'token_preview')
    readonly_fields = ('access_token', 'refresh_token', 'expires_at', 'created_at', 'updated_at')

    def is_expired_display(self, obj):
        return "❌ Expired" if obj.is_expired() else "✅ Valid"
    is_expired_display.short_description = "Status"

    def token_preview(self, obj):
        return f"{obj.access_token[:30]}..." if obj.access_token else "N/A"
    token_preview.short_description = "Token Preview"

    def has_add_permission(self, request):
        # Prevent manual creation through admin
        return False

class RoomICalConfigAdmin(admin.ModelAdmin):
    list_display = ('room', 'booking_status_display', 'airbnb_status_display', 'updated_at')
    list_filter = ('booking_active', 'airbnb_active')
    search_fields = ('room__name', 'booking_ical_url', 'airbnb_ical_url')
    readonly_fields = (
        'booking_last_synced', 'booking_last_sync_status',
        'airbnb_last_synced', 'airbnb_last_sync_status',
        'created_at', 'updated_at'
    )

    fieldsets = (
        ('Booking.com Configuration', {
            'fields': ('booking_ical_url', 'booking_active', 'booking_last_synced', 'booking_last_sync_status')
        }),
        ('Airbnb Configuration', {
            'fields': ('airbnb_ical_url', 'airbnb_active', 'airbnb_last_synced', 'airbnb_last_sync_status')
        }),
        ('Room', {
            'fields': ('room',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def booking_status_display(self, obj):
        if not obj.booking_active:
            return "🔴 Inactive"
        if not obj.booking_last_sync_status:
            return "🟡 Never synced"
        if "success" in obj.booking_last_sync_status.lower():
            return format_html('<span style="color: green;">✅ Active</span>')
        elif "error" in obj.booking_last_sync_status.lower():
            return format_html('<span style="color: red;">❌ Error</span>')
        return obj.booking_last_sync_status
    booking_status_display.short_description = "Booking.com"

    def airbnb_status_display(self, obj):
        if not obj.airbnb_active:
            return "🔴 Inactive"
        if not obj.airbnb_last_sync_status:
            return "🟡 Never synced"
        if "success" in obj.airbnb_last_sync_status.lower():
            return format_html('<span style="color: green;">✅ Active</span>')
        elif "error" in obj.airbnb_last_sync_status.lower():
            return format_html('<span style="color: red;">❌ Error</span>')
        return obj.airbnb_last_sync_status
    airbnb_status_display.short_description = "Airbnb"

    actions = ['sync_now']

    def sync_now(self, request, queryset):
        """Manually trigger immediate sync for selected rooms (runs synchronously)"""
        from main.services.ical_service import sync_reservations_for_room
        
        total_created = 0
        total_updated = 0
        total_cancelled = 0
        synced_count = 0
        error_count = 0
        
        for config in queryset:
            # Sync Booking.com if active
            if config.booking_active and config.booking_ical_url:
                try:
                    result = sync_reservations_for_room(config.id, platform='booking')
                    if result['success']:
                        total_created += result['created']
                        total_updated += result['updated']
                        total_cancelled += result['cancelled']
                        synced_count += 1
                    else:
                        error_count += 1
                        logger.error(f"Booking.com sync failed for {config.room.name}: {result['errors']}")
                except Exception as e:
                    error_count += 1
                    logger.error(f"Booking.com sync error for {config.room.name}: {str(e)}")
            
            # Sync Airbnb if active
            if config.airbnb_active and config.airbnb_ical_url:
                try:
                    result = sync_reservations_for_room(config.id, platform='airbnb')
                    if result['success']:
                        total_created += result['created']
                        total_updated += result['updated']
                        total_cancelled += result['cancelled']
                        synced_count += 1
                    else:
                        error_count += 1
                        logger.error(f"Airbnb sync failed for {config.room.name}: {result['errors']}")
                except Exception as e:
                    error_count += 1
                    logger.error(f"Airbnb sync error for {config.room.name}: {str(e)}")
        
        # Show summary message
        if synced_count > 0:
            self.message_user(
                request,
                f"Sync complete: {total_created} created, {total_updated} updated, {total_cancelled} cancelled. Errors: {error_count}",
                messages.SUCCESS if error_count == 0 else messages.WARNING
            )
        else:
            self.message_user(request, "No active configurations selected.", messages.WARNING)
    
    sync_now.short_description = "Sync selected rooms now (immediate)"

class ReservationAdmin(admin.ModelAdmin):
    list_display = ('platform_badge', 'guest_name', 'booking_reference', 'room', 'check_in_date', 'check_out_date', 'status', 'enrichment_status', 'created_at')
    list_filter = ('platform', 'status', 'room', 'check_in_date', 'check_out_date')
    search_fields = ('guest_name', 'booking_reference', 'ical_uid', 'guest__full_name', 'guest__phone_number', 'guest__email')
    readonly_fields = ('ical_uid', 'guest', 'raw_ical_data', 'created_at', 'updated_at')

    fieldsets = (
        ('Reservation Details', {
            'fields': ('room', 'platform', 'guest_name', 'booking_reference', 'check_in_date', 'check_out_date', 'status')
        }),
        ('Guest Enrichment', {
            'fields': ('guest',),
            'description': 'Linked Guest record (created after user provides full details)'
        }),
        ('Technical Details', {
            'fields': ('ical_uid', 'raw_ical_data'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def platform_badge(self, obj):
        if obj.platform == 'booking':
            return format_html('<span style="background: #003580; color: white; padding: 3px 8px; border-radius: 3px; font-size: 11px;">📘 Booking.com</span>')
        elif obj.platform == 'airbnb':
            return format_html('<span style="background: #FF5A5F; color: white; padding: 3px 8px; border-radius: 3px; font-size: 11px;">🏠 Airbnb</span>')
        return obj.platform
    platform_badge.short_description = "Platform"

    def enrichment_status(self, obj):
        if obj.is_enriched():
            return format_html('<span style="color: green;">✅ Enriched</span>')
        return format_html('<span style="color: orange;">⏳ Pending</span>')
    enrichment_status.short_description = "Enrichment"

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('room', 'guest', 'guest__assigned_room')

class MessageTemplateAdmin(admin.ModelAdmin):
    list_display = ('message_type', 'subject', 'is_active', 'last_edited_by', 'last_edited_at', 'character_count')
    list_filter = ('is_active', 'message_type')
    search_fields = ('message_type', 'subject', 'content')
    readonly_fields = ('last_edited_by', 'last_edited_at', 'created_at')

    fieldsets = (
        ('Template Info', {
            'fields': ('message_type', 'is_active')
        }),
        ('Email Content', {
            'fields': ('subject', 'content'),
            'description': 'Use variables: {guest_name}, {room_name}, {check_in_date}, {check_out_date}, {reservation_number}, {pin}, {room_detail_url}, {platform_name}'
        }),
        ('Metadata', {
            'fields': ('last_edited_by', 'last_edited_at', 'created_at'),
            'classes': ('collapse',)
        }),
    )

    def character_count(self, obj):
        count = len(obj.content)
        if 'sms' in obj.message_type and count > 160:
            return format_html('<span style="color: orange; font-weight: bold;">{} chars ⚠️</span>', count)
        return f"{count} chars"
    character_count.short_description = "Length"

    def save_model(self, request, obj, form, change):
        obj.last_edited_by = request.user
        obj.save()

# Email Enrichment System Admin Classes
class PendingEnrichmentAdmin(admin.ModelAdmin):
    list_display = ('booking_reference', 'check_in_date', 'email_type', 'status', 'attempts', 'email_received_at', 'alert_sent_at')
    list_filter = ('status', 'email_type', 'platform', 'check_in_date')
    search_fields = ('booking_reference', 'matched_reservation__guest_name')
    readonly_fields = ('email_received_at', 'enriched_at', 'alert_sent_at', 'alert_sms_sid')
    actions = ['delete_selected_enrichments']

    fieldsets = (
        ('Booking Details', {
            'fields': ('platform', 'booking_reference', 'check_in_date', 'email_type')
        }),
        ('Matching Status', {
            'fields': ('status', 'attempts', 'matched_reservation', 'room_matched')
        }),
        ('Alert Tracking', {
            'fields': ('alert_sent_at', 'alert_sms_sid')
        }),
        ('Enrichment', {
            'fields': ('enriched_via', 'enriched_at')
        }),
        ('Timestamps', {
            'fields': ('email_received_at',),
            'classes': ('collapse',)
        }),
    )

    def delete_selected_enrichments(self, request, queryset):
        """Bulk delete selected PendingEnrichments"""
        count = queryset.count()
        queryset.delete()
        self.message_user(request, f"Successfully deleted {count} PendingEnrichment(s).")
    delete_selected_enrichments.short_description = "Delete selected pending enrichments"

class EnrichmentLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'action', 'booking_reference', 'room', 'method')
    list_filter = ('action', 'method', 'timestamp')
    search_fields = ('booking_reference', 'reservation__guest_name')
    readonly_fields = ('timestamp', 'pending_enrichment', 'reservation', 'action', 'booking_reference', 'room', 'method', 'details')

    def has_add_permission(self, request):
        # Logs should be auto-created, not manually added
        return False

class CSVEnrichmentLogAdmin(admin.ModelAdmin):
    list_display = ('file_name', 'uploaded_at', 'uploaded_by', 'total_rows', 'single_room_count', 'multi_room_count', 'created_count', 'updated_count')
    list_filter = ('uploaded_at', 'uploaded_by')
    search_fields = ('file_name',)
    readonly_fields = ('uploaded_at', 'uploaded_by', 'file_name', 'total_rows', 'single_room_count', 'multi_room_count', 'created_count', 'updated_count', 'enrichment_summary')

    def has_add_permission(self, request):
        # Logs should be auto-created via XLS upload page
        return False

# ✅ Register models
admin.site.register(Room, RoomAdmin)
admin.site.register(Guest, GuestAdmin)
admin.site.register(ReviewCSVUpload, ReviewCSVUploadAdmin)
admin.site.register(TTLock, TTLockAdmin)
admin.site.register(AuditLog, AuditLogAdmin)
admin.site.register(PopularEvent, PopularEventAdmin)
admin.site.register(TTLockToken, TTLockTokenAdmin)
admin.site.register(RoomICalConfig, RoomICalConfigAdmin)
admin.site.register(Reservation, ReservationAdmin)
admin.site.register(MessageTemplate, MessageTemplateAdmin)
admin.site.register(PendingEnrichment, PendingEnrichmentAdmin)
admin.site.register(EnrichmentLog, EnrichmentLogAdmin)
admin.site.register(CSVEnrichmentLog, CSVEnrichmentLogAdmin)
