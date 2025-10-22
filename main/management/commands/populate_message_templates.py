"""
Management command to populate default message templates for iCal guests
Run with: python manage.py populate_message_templates
"""

from django.core.management.base import BaseCommand
from main.models import MessageTemplate


class Command(BaseCommand):
    help = 'Populate default message templates for iCal guest communications'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Populating default message templates...'))

        templates = [
            # Welcome Messages
            {
                'message_type': 'ical_welcome_email',
                'subject': 'Welcome to Pickarooms!',
                'content': (
                    "Dear {guest_name},\n\n"
                    "Welcome to Pickarooms! We're excited to have you.\n\n"
                    "Check-In Date: {check_in_date}\n"
                    "Assigned Room: {room_name}\n\n"
                    "Please visit {room_detail_url} to complete your check-in and obtain your unique PIN for the doors. "
                    "The webapp provides all the details you need for a seamless stay, including your check-in guide and room information.\n\n"
                    "Property address is 8 Rylance Street M11 3NP, UK\n\n"
                    "Best regards,\nThe Pickarooms Team"
                ),
                'is_active': True,
            },
            {
                'message_type': 'ical_welcome_sms',
                'subject': '',
                'content': (
                    "Welcome to Pickarooms! Check-in on {check_in_date} for {room_name}. "
                    "Visit {room_detail_url} to get your PIN and enjoy a breeze with all stay details! "
                    "Property address is 8 Rylance Street M11 3NP, UK"
                ),
                'is_active': True,
            },

            # Update Messages
            {
                'message_type': 'ical_update_email',
                'subject': 'Pickarooms Reservation Updated',
                'content': (
                    "Dear {guest_name},\n\n"
                    "Your reservation at Pickarooms has been updated and a new access PIN generated. Here are your updated details:\n\n"
                    "Check-In Date: {check_in_date}\n"
                    "Check-Out Date: {check_out_date}\n"
                    "Assigned Room: {room_name}\n\n"
                    "Please visit {room_detail_url} to access your room details, including your new PIN. "
                    "The webapp provides all the information you need for a seamless stay.\n\n"
                    "Property address is 8 Rylance Street M11 3NP, UK\n\n"
                    "Best regards,\nThe Pickarooms Team"
                ),
                'is_active': True,
            },
            {
                'message_type': 'ical_update_sms',
                'subject': '',
                'content': (
                    "Pickarooms: Your reservation has been updated and a new access PIN generated for you. "
                    "Check-in on {check_in_date}, Check-out on {check_out_date}, Room: {room_name}. "
                    "Visit {room_detail_url} for details and your PIN."
                ),
                'is_active': True,
            },

            # Cancellation Messages
            {
                'message_type': 'ical_cancellation_email',
                'subject': 'Pickarooms Reservation Cancelled',
                'content': (
                    "Dear {guest_name},\n\n"
                    "Your reservation at Pickarooms has been cancelled.\n"
                    "Check-In Date: {check_in_date}\n"
                    "Assigned Room: {room_name}\n\n"
                    "If this was a mistake, please contact us at easybulb@gmail.com.\n\n"
                    "Best regards,\nThe Pickarooms Team"
                ),
                'is_active': True,
            },
            {
                'message_type': 'ical_cancellation_sms',
                'subject': '',
                'content': (
                    "Pickarooms: Your reservation on {check_in_date} for {room_name} has been cancelled. "
                    "Contact us if needed."
                ),
                'is_active': True,
            },

            # Post-Stay Messages (Review Requests)
            {
                'message_type': 'ical_post_stay_email',
                'subject': 'Thank You for Staying at Pickarooms!',
                'content': (
                    "Dear {guest_name},\n\n"
                    "Thank you for staying with us at Pickarooms! We hope you enjoyed your time at {room_name}.\n\n"
                    "We'd love to welcome you back for your next visit. When {platform_name} prompts you, please leave us a review to share your experience—it means the world to us!\n\n"
                    "Best regards,\nThe Pickarooms Team"
                ),
                'is_active': True,
            },
            {
                'message_type': 'ical_post_stay_sms',
                'subject': '',
                'content': (
                    "Thank you for staying at Pickarooms! We'd love you back. "
                    "Please leave a review on {platform_name} when prompted!"
                ),
                'is_active': True,
            },
        ]

        created_count = 0
        updated_count = 0

        for template_data in templates:
            template, created = MessageTemplate.objects.update_or_create(
                message_type=template_data['message_type'],
                defaults={
                    'subject': template_data['subject'],
                    'content': template_data['content'],
                    'is_active': template_data['is_active'],
                }
            )

            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f'  + Created: {template.get_message_type_display()}'))
            else:
                updated_count += 1
                self.stdout.write(self.style.WARNING(f'  * Updated: {template.get_message_type_display()}'))

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'Successfully populated {created_count} new templates and updated {updated_count} existing templates'))
        self.stdout.write(self.style.SUCCESS('Message templates are now ready for use!'))
