# main/admin.py
from django.contrib import admin
from django.utils.html import format_html
from django.conf import settings
from django import forms
from .models import Room, Guest, ReviewCSVUpload, TTLock, AuditLog, PopularEvent, GuestIDUpload
from .ttlock_utils import TTLockClient
import logging
import random  # Added for randint
from django.contrib import messages  # Added for messages framework

# Set up logging for TTLock interactions
logger = logging.getLogger('main')

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
                    new_pin = str(random.randint(10000, 99999))  # Use random module
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

# ✅ Register models
admin.site.register(Room, RoomAdmin)
admin.site.register(Guest, GuestAdmin)
admin.site.register(ReviewCSVUpload, ReviewCSVUploadAdmin)
admin.site.register(TTLock, TTLockAdmin)
admin.site.register(AuditLog, AuditLogAdmin)
admin.site.register(PopularEvent, PopularEventAdmin)