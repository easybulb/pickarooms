# Generated by Django 5.1.5 on 2025-03-17 16:48

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0021_guest_email'),
    ]

    operations = [
        migrations.CreateModel(
            name='PopularEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_id', models.CharField(max_length=100, unique=True)),
                ('name', models.CharField(max_length=255)),
                ('date', models.DateField()),
                ('venue', models.CharField(max_length=255)),
                ('ticket_price', models.CharField(max_length=50)),
                ('suggested_price', models.CharField(max_length=50)),
                ('email_sent', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'unique_together': {('name', 'date', 'venue')},
            },
        ),
    ]
