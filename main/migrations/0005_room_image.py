# Generated by Django 5.1.5 on 2025-02-05 09:46

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0004_guest_secure_token'),
    ]

    operations = [
        migrations.AddField(
            model_name='room',
            name='image',
            field=models.ImageField(default='default_room.jpg', upload_to='room_images/'),
        ),
    ]
