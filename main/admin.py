from django.contrib import admin
from django.utils.html import format_html
from django.conf import settings
from django import forms
from .models import Room, Guest, ReviewCSVUpload


# ✅ Custom Form to Handle File Upload in Local and Cloudinary URL in Production
class RoomAdminForm(forms.ModelForm):
    class Meta:
        model = Room
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # ✅ If in production, use text input for Cloudinary URL instead of file upload
        if not settings.DEBUG:
            self.fields['image'].widget = forms.TextInput(attrs={'placeholder': 'Enter Cloudinary URL'})
            self.fields['image'].required = False  # ✅ Ensure it's not required


class RoomAdmin(admin.ModelAdmin):
    form = RoomAdminForm  # ✅ Use the custom form

    list_display = ('name', 'access_pin', 'video_url', 'image_preview')
    search_fields = ('name',)

    def image_preview(self, obj):
        """Display image preview correctly in Django Admin for both local and production."""
        if obj.image:
            # ✅ If it's a Cloudinary URL (Production), use it directly
            if isinstance(obj.image, str) and obj.image.startswith("http"):
                image_url = obj.image
            else:
                # ✅ If it's a local file (Development), get the media URL
                image_url = obj.image.url
            return format_html('<img src="{}" width="50" height="50" style="border-radius:5px;"/>', image_url)
        return "No Image"

    image_preview.short_description = "Image Preview"


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


class ReviewCSVUploadAdmin(admin.ModelAdmin):
    list_display = ('uploaded_at',)
    readonly_fields = ('data',)
    exclude = ('data',)

    def save_model(self, request, obj, form, change):
        """Automatically process CSV and store data in JSON field."""
        obj.save()
        obj.save()  # Call save again to trigger CSV processing
        self.message_user(request, "CSV processed and stored as JSON successfully.")


# ✅ Register models (Ensuring Room is not registered twice)
admin.site.register(Room, RoomAdmin)
admin.site.register(Guest, GuestAdmin)
admin.site.register(ReviewCSVUpload, ReviewCSVUploadAdmin)
