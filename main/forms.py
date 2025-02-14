from django import forms
from django.conf import settings
from .models import Room

class RoomAdminForm(forms.ModelForm):
    class Meta:
        model = Room
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # ✅ If in production, use a text input for Cloudinary URL
        if not settings.DEBUG:
            self.fields['image'].widget = forms.TextInput(attrs={'placeholder': 'Enter Cloudinary URL'})
