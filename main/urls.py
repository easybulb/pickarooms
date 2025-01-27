from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('checkin/', views.checkin, name='checkin'),
    path('room/<int:room_id>/', views.room_detail, name='room_detail'),
    path('explore-manchester/', views.explore_manchester, name='explore_manchester'),
    path('contact/', views.contact, name='contact'),
]
