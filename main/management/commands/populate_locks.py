# main/management/commands/populate_locks.py
from django.core.management.base import BaseCommand
from main.models import TTLock, Room

class Command(BaseCommand):
    help = 'Populates TTLock entries and associates them with Rooms'

    def handle(self, *args, **options):
        # Create TTLock entries
        ttlock_data = [
            {"name": "Front Door", "lock_id": 18159702},
            {"name": "Room 1", "lock_id": 21168210},
            {"name": "Room 2", "lock_id": 21168756},
            {"name": "Room 3", "lock_id": 21169056},
            {"name": "Room 4", "lock_id": 21167666},
        ]

        for data in ttlock_data:
            TTLock.objects.get_or_create(lock_id=data["lock_id"], defaults={"name": data["name"]})

        # Associate TTLock with Rooms (only for room-specific locks)
        room_locks = {
            "Room 1": 21168210,
            "Room 2": 21168756,
            "Room 3": 21169056,
            "Room 4": 21167666,
        }

        for room_name, lock_id in room_locks.items():
            room = Room.objects.get(name=room_name)
            ttlock = TTLock.objects.get(lock_id=lock_id)
            room.ttlock = ttlock
            room.save()

        self.stdout.write(self.style.SUCCESS('Successfully populated TTLock entries and associations'))