from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.views import LoginView
from django.contrib.auth.decorators import login_required, user_passes_test
from .models import Guest, Room, ReviewCSVUpload
from django.core.mail import send_mail
from django.utils.timezone import now, localtime
from datetime import date, datetime, time
from django.http import Http404
from django.db.models import Q
from django.http import JsonResponse
from django_ratelimit.decorators import ratelimit
from django.core.paginator import Paginator
from django.conf import settings
from django.contrib import messages
import pandas as pd
import random

def home(request):
    # Fetch the latest uploaded CSV file
    latest_file = ReviewCSVUpload.objects.last()
    
    if latest_file:
        file_path = latest_file.file.path  # Get the actual file path
        reviews_df = pd.read_csv(file_path)

        # Filter reviews that have a comment and a score of 9 or 10
        filtered_reviews = reviews_df[
            (reviews_df["Review score"] >= 9) & 
            (reviews_df["Positive review"].notna()) & 
            (reviews_df["Positive review"].str.strip() != "")
        ]

        # Separate 10/10 reviews from 9/10 reviews
        perfect_reviews = filtered_reviews[filtered_reviews["Review score"] == 10]
        good_reviews = filtered_reviews[filtered_reviews["Review score"] == 9]

        # Shuffle the reviews to make selection random
        perfect_reviews = perfect_reviews.sample(frac=1).reset_index(drop=True)  # Shuffle perfect reviews
        good_reviews = good_reviews.sample(frac=1).reset_index(drop=True)  # Shuffle good reviews

        # Select up to 3 random 10/10 reviews first, then fill the rest with 9/10 reviews up to 5
        selected_reviews = pd.concat([perfect_reviews.head(3), good_reviews.head(2)]).sample(frac=1).reset_index(drop=True)

        # Convert to dictionary format for template rendering
        latest_reviews = selected_reviews[["Guest name", "Positive review", "Review score"]].rename(
            columns={"Guest name": "author", "Positive review": "text", "Review score": "score"}
        ).to_dict(orient="records")
    else:
        latest_reviews = []  # Empty list if no CSV has been uploaded

    return render(request, "main/home.html", {"latest_reviews": latest_reviews})



def about(request):
    return render(request, 'main/about.html')

def explore_manchester(request):
    return render(request, 'main/explore_manchester.html')



@ratelimit(key='ip', rate='10/m', method='POST', block=True)
def checkin(request):
    if request.method == 'POST':
        phone_number = request.POST.get('phone_number')

        try:
            guest = Guest.objects.filter(phone_number=phone_number).order_by('-check_in_date').first()

            if guest:
                # Store phone number in session for security
                request.session['phone_number'] = phone_number
                return redirect('room_detail', room_token=guest.secure_token)
            else:
                return render(request, 'main/checkin.html', {'error': "No reservation found. Please enter the same phone number used in your Booking.com reservation."})

        except Guest.DoesNotExist:
            return render(request, 'main/checkin.html', {'error': "Details not found. Make sure you input the correct phone number."})

    return render(request, 'main/checkin.html')






def room_detail(request, room_token):
    phone_number = request.session.get('phone_number', None)  # Retrieve from session
    guest = get_object_or_404(Guest, secure_token=room_token)

    # Ensure only the correct guest can access their own room details
    if not phone_number or guest.phone_number != phone_number:
        return redirect('unauthorized')  # Redirect unauthorized users

    room = guest.assigned_room
    return render(request, 'main/room_detail.html', {
        'room': room,
        'guest': guest,
        'expiration_message': f"Your access will expire on {guest.check_out_date.strftime('%d %b %Y')} at 11:59 PM.",
        'MEDIA_URL': settings.MEDIA_URL,
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





from django.contrib import messages  # Import Django messages

@login_required(login_url='/admin-page/login/')
@user_passes_test(lambda user: user.is_superuser, login_url='/unauthorized/')
def admin_page(request):
    """Admin Dashboard to manage guests, rooms, and assignments."""
    
    # Auto-move past guests to archive at 11:00 AM on the checkout date
    now_time = localtime(now())  # Get local timezone time
    today = now_time.date()
    current_time = now_time.time()
    archive_time = time(11, 0)  # Archive guests at 11:00 AM

    # Archive guests whose checkout date has passed or is today after 11 AM
    Guest.objects.filter(
        Q(check_out_date__lt=today) | 
        (Q(check_out_date=today) & Q(is_archived=False))
    ).update(is_archived=True)

    # Show only active (non-archived) guests sorted by check-in date
    guests = Guest.objects.filter(is_archived=False).order_by('check_in_date')

    # Get check-in and check-out dates from the request
    check_in_date = request.POST.get('check_in_date') or request.GET.get('check_in_date') or None
    check_out_date = request.POST.get('check_out_date') or request.GET.get('check_out_date') or None

    # Fetch available rooms based on date selection
    if check_in_date and check_out_date:
        check_in_date = date.fromisoformat(check_in_date)
        check_out_date = date.fromisoformat(check_out_date)
        available_rooms = get_available_rooms(check_in_date, check_out_date)
    else:
        available_rooms = Room.objects.all()

    # Handle guest addition
    if request.method == 'POST' and 'phone_number' in request.POST:
        phone_number = request.POST.get('phone_number')
        full_name = request.POST.get('full_name')
        room_id = request.POST.get('room')

        try:
            room = Room.objects.get(id=room_id)
            existing_guest = Guest.objects.filter(phone_number=phone_number).first()

            if existing_guest:
                # ✅ If the guest is archived, reactivate & update details
                if existing_guest.is_archived:
                    existing_guest.is_archived = False
                    existing_guest.assigned_room = room
                    existing_guest.check_in_date = check_in_date
                    existing_guest.check_out_date = check_out_date
                    existing_guest.save()

                    messages.success(request, "Guest reactivated and assigned to room successfully!")
                    return redirect('admin_page')

                else:
                    messages.error(request, "A guest with this phone number is already checked in.")
            else:
                # ✅ If no existing guest, create a new one
                Guest.objects.create(
                    phone_number=phone_number,
                    full_name=full_name,
                    check_in_date=check_in_date,
                    check_out_date=check_out_date,
                    assigned_room=room
                )

                messages.success(request, "Guest added successfully!")
                return redirect('admin_page')

        except Room.DoesNotExist:
            messages.error(request, "Invalid room selected.")

    return render(request, 'main/admin_page.html', {
        'rooms': available_rooms,
        'guests': guests,
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

        # ✅ Add success message
        messages.success(request, f"Guest {guest.full_name} updated successfully.")

        return redirect('admin_page')

    # Get available rooms for selected check-in and check-out dates
    available_rooms = get_available_rooms(guest.check_in_date, guest.check_out_date) | Room.objects.filter(id=guest.assigned_room.id)

    return render(request, 'main/edit_guest.html', {
        'guest': guest,
        'rooms': available_rooms,
    })




@login_required(login_url='/admin-page/login/')
@user_passes_test(lambda user: user.is_superuser, login_url='/unauthorized/')
def delete_guest(request, guest_id):
    guest = get_object_or_404(Guest, id=guest_id)
    guest_name = guest.full_name  # Store guest name for message before deletion
    guest.delete()

    # ✅ Add success message
    messages.success(request, f"Guest {guest_name} deleted successfully.")

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



def privacy_policy(request):
    return render(request, 'main/privacy_policy.html')

def terms_of_use(request):
    return render(request, 'main/terms_of_use.html')

def terms_conditions(request):
    return render(request, 'main/terms_conditions.html')

def cookie_policy(request):
    return render(request, 'main/cookie_policy.html')

def sitemap(request):
    return render(request, 'main/sitemap.html')

def how_to_use(request):
    return render(request, 'main/how_to_use.html')



def awards_reviews(request):
    # Fetch the latest uploaded CSV file
    latest_file = ReviewCSVUpload.objects.last()
    
    if latest_file:
        file_path = latest_file.file.path  # Get the actual file path
        reviews_df = pd.read_csv(file_path)

        # Filter reviews with a score of 9 or 10 AND ensure the positive review column is not empty
        filtered_reviews = reviews_df[(reviews_df["Review score"] >= 9) & (reviews_df["Positive review"].notna()) & (reviews_df["Positive review"].str.strip() != "")]

        # Select up to 10 best reviews based on the score
        filtered_reviews = filtered_reviews.sort_values(by="Review score", ascending=False).head(20)

        # Convert to dictionary format for template rendering
        all_reviews = filtered_reviews[["Guest name", "Positive review", "Review score"]].rename(
            columns={"Guest name": "author", "Positive review": "text", "Review score": "score"}
        ).to_dict(orient="records")
    else:
        all_reviews = []  # Empty list if no CSV has been uploaded

    return render(request, "main/awards_reviews.html", {"all_reviews": all_reviews})

