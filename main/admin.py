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



class RoomAdmin(admin.ModelAdmin):
    list_display = ('name', 'access_pin', 'video_url', 'image')   # Show image field in admin
    search_fields = ('name',)


# ✅ Register Room and Guest models
admin.site.register(Room, RoomAdmin)
admin.site.register(Guest, GuestAdmin)
admin.site.register(ReviewCSVUpload)
