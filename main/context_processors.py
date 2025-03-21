# main/context_processors.py
from django.conf import settings

def ipgeolocation_api_key(request):
    return {
        'IPGEOLOCATION_API_KEY': settings.IPGEOLOCATION_API_KEY,
    }