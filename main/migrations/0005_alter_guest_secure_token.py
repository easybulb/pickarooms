# Generated by Django 5.1.5 on 2025-01-31 21:32

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0004_guest_secure_token'),
    ]

    operations = [
        migrations.AlterField(
            model_name='guest',
            name='secure_token',
            field=models.CharField(blank=True, max_length=10),
        ),
    ]
