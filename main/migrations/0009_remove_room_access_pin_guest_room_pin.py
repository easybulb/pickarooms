# Generated by Django 5.1.5 on 2025-03-05 16:02

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0008_guest_room_pin_id_alter_guest_front_door_pin_id_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='room',
            name='access_pin',
        ),
        migrations.AddField(
            model_name='guest',
            name='room_pin',
            field=models.CharField(blank=True, max_length=10, null=True),
        ),
    ]
