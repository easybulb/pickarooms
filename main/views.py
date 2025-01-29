from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.views import LoginView
from django.contrib.auth.decorators import login_required, user_passes_test
from .models import Guest, Room
from django.core.mail import send_mail


def home(request):
    return render(request, 'main/home.html')

def about(request):
    return render(request, 'main/about.html')


def checkin(request):
    if request.method == 'POST':
        phone_number = request.POST.get('phone_number')
        try:
            guest = Guest.objects.get(phone_number=phone_number)
            # Redirect to the guest's assigned room page
            return redirect('room_detail', room_id=guest.assigned_room.id)
        except Guest.DoesNotExist:
            # Return an error message for invalid phone numbers
            return render(request, 'main/checkin.html', {
                'error': "Details not found. Make sure you input the same phone number used in your booking on Booking.com or Airbnb."
            })
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



class AdminLoginView(LoginView):
    template_name = 'main/admin_login.html'

    def get_success_url(self):
        # Redirect to the admin page after login
        return '/admin-page/'

@login_required(login_url='/admin-page/login/')
@user_passes_test(lambda user: user.is_superuser, login_url='/unauthorized/')
def admin_page(request):
    if request.method == 'POST':
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



def unauthorized(request):
    return render(request, 'main/unauthorized.html')

