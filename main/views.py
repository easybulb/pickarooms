from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.views import LoginView
from django.contrib.auth.decorators import login_required, user_passes_test
from .models import Guest, Room
from django.core.mail import send_mail
from django.utils.timezone import now, localtime
from datetime import date, datetime, time
from django.http import Http404
from django.db.models import Q
from django.http import JsonResponse
from django_ratelimit.decorators import ratelimit
from django.core.paginator import Paginator


def home(request):
    return render(request, 'main/home.html')

def about(request):
    return render(request, 'main/about.html')

def explore_manchester(request):
    return render(request, 'main/explore_manchester.html')



@ratelimit(key='ip', rate='10/m', method='POST', block=True)
def checkin(request):
    if request.method == 'POST':
        phone_number = request.POST.get('phone_number')
        current_date = localtime(now()).date()

        try:
            guest = Guest.objects.filter(
                phone_number=phone_number
            ).order_by('-check_in_date').first()  # Get the latest booking

            if guest:
                return redirect('room_detail', room_id=guest.assigned_room.id, guest_id=guest.id)  # Pass guest_id
            else:
                return render(request, 'main/checkin.html', {
                    'error': "No reservation found for this phone number."
                })
        except Guest.DoesNotExist:
            return render(request, 'main/checkin.html', {
                'error': "Details not found. Make sure you input the same phone number used in your booking on Booking.com or Airbnb."
            })

    return render(request, 'main/checkin.html')






def room_detail(request, room_id, guest_id):
    room = get_object_or_404(Room, id=room_id)
    guest = get_object_or_404(Guest, id=guest_id)  # Get only the specific guest

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
    
    # Auto-move past guests at 11:00 AM on the checkout date
    now_time = localtime(now())  # Get the current time in the local timezone
    today = now_time.date()
    current_time = now_time.time()
    archive_time = time(11, 0)  # Set the archive time to 11:00 AM

    # Move guests to archive if:
    # 1. Their checkout date is in the past, OR
    # 2. Their checkout date is today AND the current time is past 11:00 AM
    Guest.objects.filter(
        Q(check_out_date__lt=today) | 
        (Q(check_out_date=today) & Q(is_archived=False))
    ).update(is_archived=True)

    # Show only active guests (not archived) and sort by nearest check-in date
    guests = Guest.objects.filter(is_archived=False).order_by('check_in_date')

    check_in_date = request.POST.get('check_in_date') or request.GET.get('check_in_date') or None
    check_out_date = request.POST.get('check_out_date') or request.GET.get('check_out_date') or None

    if check_in_date and check_out_date:
        check_in_date = date.fromisoformat(check_in_date)
        check_out_date = date.fromisoformat(check_out_date)
        available_rooms = get_available_rooms(check_in_date, check_out_date)
    else:
        available_rooms = Room.objects.all()

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






@login_required(login_url='/admin-page/login/')
@user_passes_test(lambda user: user.is_superuser, login_url='/unauthorized/')
def past_guests(request):
    search_query = request.GET.get('search', '')
    
    past_guests = Guest.objects.filter(is_archived=True)

    # Apply search filter if search_query exists
    if search_query:
        past_guests = past_guests.filter(
            Q(full_name__icontains=search_query) |
            Q(phone_number__icontains=search_query) |
            Q(assigned_room__name__icontains=search_query)
        )

    # Sort by the most recent check-out date (descending)
    past_guests = past_guests.order_by('-check_out_date')

    # Paginate results - limit to 50 guests per page
    paginator = Paginator(past_guests, 50)
    page_number = request.GET.get('page')
    paginated_past_guests = paginator.get_page(page_number)

    return render(request, 'main/past_guests.html', {
        'past_guests': paginated_past_guests,
        'search_query': search_query,
    })
