from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.views import LoginView
from django.contrib.auth.decorators import login_required, user_passes_test
from .models import Guest, Room
from django.core.mail import send_mail
from django.utils.timezone import now
from django.http import Http404
from django.db.models import Q
from datetime import date
from django.http import JsonResponse


def home(request):
    return render(request, 'main/home.html')

def about(request):
    return render(request, 'main/about.html')

def explore_manchester(request):
    return render(request, 'main/explore_manchester.html')




def checkin(request):
    if request.method == 'POST':
        phone_number = request.POST.get('phone_number')
        try:
            guest = Guest.objects.get(phone_number=phone_number)
            if guest.has_access():
                # Redirect to the guest's assigned room page if they have access
                return redirect('room_detail', room_id=guest.assigned_room.id)
            else:
                # If the guest's access has expired
                return render(request, 'main/checkin.html', {
                    'error': "Access expired. If you need assistance, please contact the admin."
                })
        except Guest.DoesNotExist:
            # If the phone number is not found in the database
            return render(request, 'main/checkin.html', {
                'error': "Details not found. Make sure you input the same phone number used in your booking on Booking.com or Airbnb."
            })
    return render(request, 'main/checkin.html')





def room_detail(request, room_id):
    room = get_object_or_404(Room, id=room_id)
    guests = Guest.objects.filter(assigned_room=room)

    if not guests.exists():
        raise Http404("No guest assigned to this room.")

    if guests.count() > 1:
        return render(request, 'main/room_detail.html', {
            'room': room,
            'error': "Multiple guests are assigned to this room. Please contact the admin for assistance."
        })

    guest = guests.first()
    return render(request, 'main/room_detail.html', {
        'room': room,
        'guest': guest,
        'expiration_message': f"Your access will expire on {guest.check_out_date.strftime('%d %b %Y')} at 11:59 PM.",
    })





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
    error_message = None
    guests = Guest.objects.all()

    # Handle date inputs dynamically
    check_in_date = request.POST.get('check_in_date') or request.GET.get('check_in_date') or None
    check_out_date = request.POST.get('check_out_date') or request.GET.get('check_out_date') or None

    if check_in_date and check_out_date:
        check_in_date = date.fromisoformat(check_in_date)
        check_out_date = date.fromisoformat(check_out_date)
        available_rooms = get_available_rooms(check_in_date, check_out_date)
    else:
        available_rooms = Room.objects.all()  # Show all rooms if no date is selected

    # Handle guest addition
    if request.method == 'POST' and 'phone_number' in request.POST:
        phone_number = request.POST.get('phone_number')
        full_name = request.POST.get('full_name')
        room_id = request.POST.get('room')

        try:
            room = Room.objects.get(id=room_id)
            if Guest.objects.filter(phone_number=phone_number).exists():
                error_message = "A guest with this phone number already exists."
            else:
                Guest.objects.create(
                    phone_number=phone_number,
                    full_name=full_name,
                    check_in_date=check_in_date,
                    check_out_date=check_out_date,
                    assigned_room=room
                )
                return redirect('admin_page')
        except Room.DoesNotExist:
            error_message = "Invalid room selected."

    return render(request, 'main/admin_page.html', {
        'rooms': available_rooms,
        'guests': guests,
        'error': error_message,
        'check_in_date': check_in_date,
        'check_out_date': check_out_date,
    })






def get_available_rooms(check_in_date, check_out_date):
    """Returns rooms that are not assigned for the given date range."""
    # Convert dates if necessary
    check_in_date = date.fromisoformat(str(check_in_date)) if isinstance(check_in_date, str) else check_in_date
    check_out_date = date.fromisoformat(str(check_out_date)) if isinstance(check_out_date, str) else check_out_date

    # Find guests whose bookings overlap with the provided date range
    conflicting_guests = Guest.objects.filter(
        Q(check_in_date__lt=check_out_date) & Q(check_out_date__gt=check_in_date)
    )

    # Get IDs of rooms that are booked during the conflicting date range
    conflicting_rooms = conflicting_guests.values_list('assigned_room', flat=True)

    # Return rooms that are NOT in the list of conflicting rooms
    return Room.objects.exclude(id__in=conflicting_rooms)




from django.http import JsonResponse

@login_required(login_url='/admin-page/login/')
@user_passes_test(lambda user: user.is_superuser, login_url='/unauthorized/')
def available_rooms(request):
    check_in_date = request.GET.get('check_in_date')
    check_out_date = request.GET.get('check_out_date')

    if check_in_date and check_out_date:
        check_in_date = date.fromisoformat(check_in_date)
        check_out_date = date.fromisoformat(check_out_date)
        rooms = get_available_rooms(check_in_date, check_out_date)
        room_list = [{'id': room.id, 'name': room.name} for room in rooms]
        return JsonResponse({'rooms': room_list})
    return JsonResponse({'rooms': []})






def unauthorized(request):
    return render(request, 'main/unauthorized.html')



@login_required(login_url='/admin-page/login/')
@user_passes_test(lambda user: user.is_superuser, login_url='/unauthorized/')
def edit_guest(request, guest_id):
    guest = get_object_or_404(Guest, id=guest_id)

    if request.method == 'POST':
        guest.full_name = request.POST.get('full_name')
        guest.phone_number = request.POST.get('phone_number')
        guest.check_in_date = request.POST.get('check_in_date')
        guest.check_out_date = request.POST.get('check_out_date')
        guest.assigned_room_id = request.POST.get('room')
        guest.save()
        return redirect('admin_page')

    # Include the currently assigned room in the available rooms
    available_rooms = get_available_rooms(guest.check_in_date, guest.check_out_date) | Room.objects.filter(id=guest.assigned_room.id)

    return render(request, 'main/edit_guest.html', {
        'guest': guest,
        'rooms': available_rooms,
    })




@login_required(login_url='/admin-page/login/')
@user_passes_test(lambda user: user.is_superuser, login_url='/unauthorized/')
def delete_guest(request, guest_id):
    guest = get_object_or_404(Guest, id=guest_id)
    guest.delete()
    return redirect('admin_page')
