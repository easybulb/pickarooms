# Generated by Django 5.1.5 on 2025-03-12 19:58

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0014_alter_guest_options'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='guest',
            options={'permissions': [('can_give_access', 'Can give access to doors'), ('view_admin_dashboard', 'Can view the admin dashboard and manage guests')]},
        ),
    ]
