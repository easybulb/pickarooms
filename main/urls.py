from django.urls import path
from . import views
from django.contrib.auth.views import LogoutView

urlpatterns = [
    path('', views.home, name='home'),
    path('about/', views.about, name='about'),
    path('checkin/', views.checkin, name='checkin'),
    path('room/<int:room_id>/', views.room_detail, name='room_detail'),
    path('explore-manchester/', views.explore_manchester, name='explore_manchester'),
    path('contact/', views.contact, name='contact'),
    path('admin-page/', views.admin_page, name='admin_page'),
    path('admin-page/login/', views.AdminLoginView.as_view(), name='admin_login'),
    path('logout/', LogoutView.as_view(next_page='/'), name='logout'),
    path('unauthorized/', views.unauthorized, name='unauthorized'),
    path('admin-page/edit-guest/<int:guest_id>/', views.edit_guest, name='edit_guest'),
    path('admin-page/delete-guest/<int:guest_id>/', views.delete_guest, name='delete_guest'),
    path('admin-page/available-rooms/', views.available_rooms, name='available_rooms'),
]
