from django.db import models

class Room(models.Model):
    name = models.CharField(max_length=100)  # Room name
    video_url = models.URLField()  # Link to the video instructions
    description = models.TextField(blank=True, null=True)  # Optional room description

    def __str__(self):
        return self.name


class Guest(models.Model):
    phone_number = models.CharField(max_length=15, unique=True)  # Unique phone number for guest login
    assigned_room = models.ForeignKey(Room, on_delete=models.CASCADE)  # Relationship to Room model

    def __str__(self):
        return f"Guest: {self.phone_number} - Room: {self.assigned_room.name}"
