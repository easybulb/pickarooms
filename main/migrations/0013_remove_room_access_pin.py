# Generated by Django 5.1.5 on 2025-03-12 07:08

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0012_guest_room_pin_id_room_ttlock'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='room',
            name='access_pin',
        ),
    ]
