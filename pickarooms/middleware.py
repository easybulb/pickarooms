def restrict_staff_to_custom_admin(get_response):
    def middleware(request):
        if request.path.startswith('/admin/') and request.user.is_staff and not request.user.is_superuser:
            from django.http import HttpResponseForbidden
            return HttpResponseForbidden("Access denied. Use the custom admin page.")
        return get_response(request)
    return middleware
