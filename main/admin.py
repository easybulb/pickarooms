from django.contrib import admin
from django.utils.html import format_html
from django.conf import settings
from .models import Room, Guest, ReviewCSVUpload

class GuestAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'phone_number', 'check_in_date', 'check_out_date', 'assigned_room', 'is_archived')
    list_filter = ('is_archived', 'check_in_date', 'check_out_date', 'assigned_room')
    search_fields = ('full_name', 'phone_number')
    actions = ['mark_as_archived']

    def mark_as_archived(self, request, queryset):
        """Allow manually archiving guests from the admin panel."""
        queryset.update(is_archived=True)
        self.message_user(request, "Selected guests have been archived.")

    mark_as_archived.short_description = "Move selected guests to archive"


class RoomAdmin(admin.ModelAdmin):
    list_display = ('name', 'access_pin', 'video_url', 'image_preview')  # ✅ Show image preview

    search_fields = ('name',)

    def image_preview(self, obj):
        """Display image preview correctly in the admin panel for both local and production."""
        if obj.image:
            image_url = obj.image if not settings.DEBUG else obj.image.url  # ✅ Handle both local and Cloudinary storage
            return format_html('<img src="{}" width="50" height="50" style="border-radius:5px;"/>', image_url)
        return "No Image"

    image_preview.short_description = "Image Preview"


class ReviewCSVUploadAdmin(admin.ModelAdmin):
    list_display = ('uploaded_at',)  # Display only the uploaded time
    readonly_fields = ('data',)  # Make 'data' read-only to prevent errors
    exclude = ('data',)  # Hide the field from the admin form

    def save_model(self, request, obj, form, change):
        """Automatically process CSV and store data in JSON field."""
        obj.save()  # Save the uploaded file first
        obj.save()  # Call save again to trigger CSV processing
        self.message_user(request, "CSV processed and stored as JSON successfully.")


# ✅ Register models (Ensuring Room is not registered twice)
admin.site.register(Room, RoomAdmin)  # ✅ Only keeping ONE instance
admin.site.register(Guest, GuestAdmin)
admin.site.register(ReviewCSVUpload, ReviewCSVUploadAdmin)
