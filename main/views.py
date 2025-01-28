from django.shortcuts import render, get_object_or_404, redirect
from .models import Guest, Room
from django.core.mail import send_mail
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import user_passes_test


def home(request):
    return render(request, 'main/home.html')

def about(request):
    return render(request, 'main/about.html')


def checkin(request):
    if request.method == 'POST':
        phone_number = request.POST.get('phone_number')
        try:
            guest = Guest.objects.get(phone_number=phone_number)
            return render(request, 'main/room_detail.html', {'guest': guest})
        except Guest.DoesNotExist:
            return render(request, 'main/checkin.html', {'error': 'Phone number not found. Please contact the admin.'})
    return render(request, 'main/checkin.html')


def room_detail(request, room_id):
    room = get_object_or_404(Room, id=room_id)
    return render(request, 'main/room_detail.html', {'room': room})


def explore_manchester(request):
    return render(request, 'main/explore_manchester.html')



def contact(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        email = request.POST.get('email')
        message = request.POST.get('message')
        # Send email logic
        send_mail(
            f"Contact Us Message from {name}",
            message,
            email,
            ['easybulb@gmail.com'],
        )
        return render(request, 'main/contact.html', {'success': True})
    return render(request, 'main/contact.html')



@user_passes_test(lambda user: user.is_superuser)
def admin_page(request):
    if request.method == 'POST':
        # Handle form submission
        phone_number = request.POST.get('phone_number')
        room_id = request.POST.get('room')
        try:
            room = Room.objects.get(id=room_id)
            Guest.objects.create(phone_number=phone_number, assigned_room=room)
            return render(request, 'main/admin_page.html', {'success': True})
        except Room.DoesNotExist:
            return render(request, 'main/admin_page.html', {'error': 'Invalid room selected.'})

    rooms = Room.objects.all()
    guests = Guest.objects.all()
    return render(request, 'main/admin_page.html', {'rooms': rooms, 'guests': guests})
