"""
Management command to set up TTLock locks in the database
Usage: python manage.py setup_locks
"""

from django.core.management.base import BaseCommand
from main.models import TTLock, Room


class Command(BaseCommand):
    help = 'Set up TTLock locks and link them to rooms'

    def handle(self, *args, **options):
        self.stdout.write('=' * 60)
        self.stdout.write('TTLock Setup - Creating Locks and Linking to Rooms')
        self.stdout.write('=' * 60)
        self.stdout.write('')

        # Lock data from your TTLock account
        locks_data = [
            {
                'lock_id': 21169056,
                'name': 'S534_2c9ede',
                'room_name': 'Room 3',
                'is_front_door': False
            },
            {
                'lock_id': 21168756,
                'name': 'S534_4d0ba4',
                'room_name': 'Room 2',
                'is_front_door': False
            },
            {
                'lock_id': 21168210,
                'name': 'S534_95ecef',
                'room_name': 'Room 1',
                'is_front_door': False
            },
            {
                'lock_id': 21167666,
                'name': 'S534_2f7754',
                'room_name': 'Room 4',
                'is_front_door': False
            },
            {
                'lock_id': 18159702,
                'name': 'LL609_1e607e',
                'room_name': 'Front Door',
                'is_front_door': True
            },
        ]

        created_locks = 0
        updated_locks = 0
        linked_rooms = 0

        # Step 1: Create or update TTLock entries
        self.stdout.write('Step 1: Creating/Updating TTLock entries...')
        self.stdout.write('')

        for lock_data in locks_data:
            lock, created = TTLock.objects.update_or_create(
                lock_id=lock_data['lock_id'],
                defaults={
                    'name': lock_data['name'],
                    'is_front_door': lock_data['is_front_door']
                }
            )
            
            if created:
                created_locks += 1
                self.stdout.write(self.style.SUCCESS(
                    f"✓ Created: {lock.name} (ID: {lock.lock_id}) - "
                    f"{'Front Door' if lock.is_front_door else 'Room Lock'}"
                ))
            else:
                updated_locks += 1
                self.stdout.write(self.style.WARNING(
                    f"⟳ Updated: {lock.name} (ID: {lock.lock_id}) - "
                    f"{'Front Door' if lock.is_front_door else 'Room Lock'}"
                ))

        self.stdout.write('')
        self.stdout.write('Step 2: Linking locks to rooms...')
        self.stdout.write('')

        # Step 2: Link locks to rooms (except Front Door)
        for lock_data in locks_data:
            if lock_data['is_front_door']:
                continue  # Skip front door
            
            # Find or create the room
            room_name = lock_data['room_name']
            
            try:
                room = Room.objects.get(name=room_name)
                lock = TTLock.objects.get(lock_id=lock_data['lock_id'])
                
                # Link the lock to the room
                if room.ttlock != lock:
                    room.ttlock = lock
                    room.save()
                    linked_rooms += 1
                    self.stdout.write(self.style.SUCCESS(
                        f"✓ Linked: {room.name} → {lock.name} (ID: {lock.lock_id})"
                    ))
                else:
                    self.stdout.write(
                        f"  Already linked: {room.name} → {lock.name}"
                    )
                
            except Room.DoesNotExist:
                self.stdout.write(self.style.ERROR(
                    f"✗ Room '{room_name}' does not exist. Please create it first."
                ))
                self.stdout.write(
                    f"  You can create it at: /admin/main/room/add/"
                )

        # Summary
        self.stdout.write('')
        self.stdout.write('=' * 60)
        self.stdout.write(self.style.SUCCESS('SETUP COMPLETE!'))
        self.stdout.write('=' * 60)
        self.stdout.write('')
        self.stdout.write(f'TTLocks Created: {created_locks}')
        self.stdout.write(f'TTLocks Updated: {updated_locks}')
        self.stdout.write(f'Rooms Linked: {linked_rooms}')
        self.stdout.write('')
        
        # Show front door status
        front_door = TTLock.objects.filter(is_front_door=True).first()
        if front_door:
            self.stdout.write(self.style.SUCCESS(
                f'Front Door Lock: {front_door.name} (ID: {front_door.lock_id})'
            ))
        
        self.stdout.write('')
        self.stdout.write('Next steps:')
        self.stdout.write('1. Visit: /room-management/ to verify locks')
        self.stdout.write('2. Visit: /admin-page/give-access/ to test lock access')
        self.stdout.write('3. If rooms don\'t exist, create them at: /admin/main/room/add/')
        self.stdout.write('')
        self.stdout.write('=' * 60)
