"""
Management command to set up Rooms and TTLock locks
Usage: python manage.py setup_rooms_and_locks
"""

from django.core.management.base import BaseCommand
from main.models import TTLock, Room


class Command(BaseCommand):
    help = 'Set up Rooms and TTLock locks with proper linking'

    def handle(self, *args, **options):
        self.stdout.write('=' * 60)
        self.stdout.write('Complete Setup - Rooms and TTLock Locks')
        self.stdout.write('=' * 60)
        self.stdout.write('')

        # Complete setup data
        setup_data = [
            {
                'lock_id': 21168210,
                'lock_name': 'S534_95ecef',
                'room_name': 'Room 1',
                'is_front_door': False,
                'video_url': 'https://www.youtube.com/watch?v=example1',
                'description': 'Comfortable single room with modern amenities',
                'image': 'https://res.cloudinary.com/your-cloud/image/upload/room1.jpg'
            },
            {
                'lock_id': 21168756,
                'lock_name': 'S534_4d0ba4',
                'room_name': 'Room 2',
                'is_front_door': False,
                'video_url': 'https://www.youtube.com/watch?v=example2',
                'description': 'Spacious double room with ensuite bathroom',
                'image': 'https://res.cloudinary.com/your-cloud/image/upload/room2.jpg'
            },
            {
                'lock_id': 21169056,
                'lock_name': 'S534_2c9ede',
                'room_name': 'Room 3',
                'is_front_door': False,
                'video_url': 'https://www.youtube.com/watch?v=example3',
                'description': 'Cozy room with city views',
                'image': 'https://res.cloudinary.com/your-cloud/image/upload/room3.jpg'
            },
            {
                'lock_id': 21167666,
                'lock_name': 'S534_2f7754',
                'room_name': 'Room 4',
                'is_front_door': False,
                'video_url': 'https://www.youtube.com/watch?v=example4',
                'description': 'Premium room with king-size bed',
                'image': 'https://res.cloudinary.com/your-cloud/image/upload/room4.jpg'
            },
            {
                'lock_id': 18159702,
                'lock_name': 'LL609_1e607e',
                'room_name': None,  # Front door doesn't need a room
                'is_front_door': True,
                'video_url': None,
                'description': None,
                'image': None
            },
        ]

        created_locks = 0
        updated_locks = 0
        created_rooms = 0
        updated_rooms = 0

        # Step 1: Create or update TTLock entries
        self.stdout.write('Step 1: Setting up TTLock entries...')
        self.stdout.write('')

        all_locks = {}
        
        for data in setup_data:
            lock, created = TTLock.objects.update_or_create(
                lock_id=data['lock_id'],
                defaults={
                    'name': data['lock_name'],
                    'is_front_door': data['is_front_door']
                }
            )
            
            all_locks[data['lock_id']] = lock
            
            if created:
                created_locks += 1
                status = '[CREATED]'
                style = self.style.SUCCESS
            else:
                updated_locks += 1
                status = '[UPDATED]'
                style = self.style.WARNING
            
            lock_type = 'FRONT DOOR' if lock.is_front_door else 'ROOM LOCK'
            self.stdout.write(style(
                f"{status}: {lock.name} (ID: {lock.lock_id}) - {lock_type}"
            ))

        # Step 2: Create or update Room entries (except front door)
        self.stdout.write('')
        self.stdout.write('Step 2: Setting up Rooms and linking to locks...')
        self.stdout.write('')

        for data in setup_data:
            if data['is_front_door']:
                continue  # Skip front door
            
            room_name = data['room_name']
            lock = all_locks[data['lock_id']]
            
            # Create or update room
            room, created = Room.objects.update_or_create(
                name=room_name,
                defaults={
                    'ttlock': lock,
                    'video_url': data['video_url'],
                    'description': data['description'],
                    'image': data['image']
                }
            )
            
            if created:
                created_rooms += 1
                status = '[CREATED]'
                style = self.style.SUCCESS
            else:
                updated_rooms += 1
                status = '[UPDATED]'
                style = self.style.WARNING
            
            self.stdout.write(style(
                f"{status}: {room.name} -> Linked to {lock.name} (ID: {lock.lock_id})"
            ))

        # Summary
        self.stdout.write('')
        self.stdout.write('=' * 60)
        self.stdout.write(self.style.SUCCESS('[SUCCESS] SETUP COMPLETE!'))
        self.stdout.write('=' * 60)
        self.stdout.write('')
        
        self.stdout.write('Summary:')
        self.stdout.write(f'  TTLocks Created: {created_locks}')
        self.stdout.write(f'  TTLocks Updated: {updated_locks}')
        self.stdout.write(f'  Rooms Created: {created_rooms}')
        self.stdout.write(f'  Rooms Updated: {updated_rooms}')
        self.stdout.write('')
        
        # Show configuration
        self.stdout.write('Configuration:')
        front_door = TTLock.objects.filter(is_front_door=True).first()
        if front_door:
            self.stdout.write(self.style.SUCCESS(
                f'  Front Door: {front_door.name} (ID: {front_door.lock_id})'
            ))
        
        room_locks = TTLock.objects.filter(is_front_door=False).count()
        rooms = Room.objects.count()
        self.stdout.write(f'  Room Locks: {room_locks}')
        self.stdout.write(f'  Rooms: {rooms}')
        self.stdout.write('')
        
        # Next steps
        self.stdout.write('=' * 60)
        self.stdout.write('Next Steps:')
        self.stdout.write('=' * 60)
        self.stdout.write('')
        self.stdout.write('1. Visit Room Management:')
        self.stdout.write('   https://kqlc2mbd-8000.uks1.devtunnels.ms/room-management/')
        self.stdout.write('')
        self.stdout.write('2. Test Lock Access:')
        self.stdout.write('   https://kqlc2mbd-8000.uks1.devtunnels.ms/admin-page/give-access/')
        self.stdout.write('')
        self.stdout.write('3. Admin Interface:')
        self.stdout.write('   http://localhost:8000/admin/main/ttlock/')
        self.stdout.write('   http://localhost:8000/admin/main/room/')
        self.stdout.write('')
        self.stdout.write('=' * 60)
        self.stdout.write(self.style.SUCCESS('Ready for testing!'))
        self.stdout.write('=' * 60)
