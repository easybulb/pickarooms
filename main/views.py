from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.views import LoginView
from django.contrib.auth.decorators import login_required, user_passes_test
from .models import Guest, Room
from django.core.mail import send_mail
from django.utils.timezone import now
from django.http import Http404


def home(request):
    return render(request, 'main/home.html')

def about(request):
    return render(request, 'main/about.html')




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





from django.http import Http404

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
        full_name = request.POST.get('full_name')
        check_in_date = request.POST.get('check_in_date')
        check_out_date = request.POST.get('check_out_date')
        room_id = request.POST.get('room')
        try:
            room = Room.objects.get(id=room_id)
            # Ensure no duplicate phone numbers are added
            if Guest.objects.filter(phone_number=phone_number).exists():
                error_message = "A guest with this phone number already exists."
                rooms = Room.objects.all()
                guests = Guest.objects.all()
                return render(request, 'main/admin_page.html', {
                    'rooms': rooms,
                    'guests': guests,
                    'error': error_message,
                })

            # Create the guest if no duplicate exists
            Guest.objects.create(
                phone_number=phone_number,
                full_name=full_name,
                check_in_date=check_in_date,
                check_out_date=check_out_date,
                assigned_room=room
            )
            # Redirect to the same page to avoid form resubmission
            return redirect('admin_page')

        except Room.DoesNotExist:
            error_message = "Invalid room selected."
            rooms = Room.objects.all()
            guests = Guest.objects.all()
            return render(request, 'main/admin_page.html', {
                'rooms': rooms,
                'guests': guests,
                'error': error_message,
            })

    # GET request - display the page with existing data
    rooms = Room.objects.all()
    guests = Guest.objects.all()
    return render(request, 'main/admin_page.html', {'rooms': rooms, 'guests': guests})




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
    rooms = Room.objects.all()
    return render(request, 'main/edit_guest.html', {'guest': guest, 'rooms': rooms})


@login_required(login_url='/admin-page/login/')
@user_passes_test(lambda user: user.is_superuser, login_url='/unauthorized/')
def delete_guest(request, guest_id):
    guest = get_object_or_404(Guest, id=guest_id)
    guest.delete()
    return redirect('admin_page')
