# Generated by Django 5.1.5 on 2025-03-15 10:57

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0017_auditlog'),
    ]

    operations = [
        migrations.AddField(
            model_name='guest',
            name='id_image',
            field=models.ImageField(blank=True, null=True, upload_to='guest_ids/%Y/%m/%d/'),
        ),
    ]
