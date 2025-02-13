from django.contrib import admin
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



from django.utils.html import format_html

class RoomAdmin(admin.ModelAdmin):
    list_display = ('name', 'access_pin', 'video_url', 'image_preview')  # ✅ Show image preview

    search_fields = ('name',)

    def image_preview(self, obj):
        """Display image preview in the admin panel."""
        if obj.image:
            return format_html('<img src="{}" width="50" height="50" style="border-radius:5px;"/>', obj.image.url)
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


# ✅ Register Room and Guest models
admin.site.register(Room, RoomAdmin)
admin.site.register(Guest, GuestAdmin)
admin.site.register(ReviewCSVUpload, ReviewCSVUploadAdmin)
