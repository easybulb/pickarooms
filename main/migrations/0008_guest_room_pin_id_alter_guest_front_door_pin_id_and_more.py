# Generated by Django 5.1.5 on 2025-03-05 09:54

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0007_ttlock_remove_room_lock_id_guest_front_door_pin_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='guest',
            name='room_pin_id',
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
        migrations.AlterField(
            model_name='guest',
            name='front_door_pin_id',
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
        migrations.AlterField(
            model_name='guest',
            name='secure_token',
            field=models.CharField(blank=True, max_length=36, unique=True),
        ),
        migrations.AlterField(
            model_name='reviewcsvupload',
            name='data',
            field=models.JSONField(default=list),
        ),
        migrations.AlterField(
            model_name='ttlock',
            name='lock_id',
            field=models.CharField(max_length=100, unique=True),
        ),
        migrations.CreateModel(
            name='TuyaLock',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('device_id', models.CharField(max_length=100, unique=True)),
                ('room', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='tuya_lock', to='main.room')),
            ],
        ),
    ]
