# Generated by Django 5.1.5 on 2025-02-05 11:44

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0005_room_image'),
    ]

    operations = [
        migrations.AddField(
            model_name='room',
            name='access_pin',
            field=models.CharField(blank=True, max_length=10, null=True),
        ),
    ]
