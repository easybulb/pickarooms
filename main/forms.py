from django import forms
from django.conf import settings
from .models import Room

class RoomAdminForm(forms.ModelForm):
    class Meta:
        model = Room
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Use text input for Cloudinary URL (works in both DEBUG and production)
        self.fields['image'].widget = forms.TextInput(
            attrs={'placeholder': 'Enter Cloudinary Image URL (e.g., https://res.cloudinary.com/...)'}
        )
        self.fields['image'].required = False
