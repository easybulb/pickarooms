# Generated by Django 5.1.5 on 2025-02-13 13:43

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0003_guest_is_returning'),
    ]

    operations = [
        migrations.AlterField(
            model_name='guest',
            name='phone_number',
            field=models.CharField(blank=True, max_length=15, null=True),
        ),
    ]
