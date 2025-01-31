from django.db import migrations, models
import uuid

def generate_secure_tokens(apps, schema_editor):
    """Assign a random secure_token to existing guests before applying the UNIQUE constraint."""
    Guest = apps.get_model("main", "Guest")
    for guest in Guest.objects.filter(secure_token="") | Guest.objects.filter(secure_token__isnull=True):
        guest.secure_token = str(uuid.uuid4().hex[:10])  # Generate a unique 10-character token
        guest.save()

class Migration(migrations.Migration):

    dependencies = [
        ('main', '0003_guest_is_archived'),  # Ensure it depends on the correct previous migration
    ]

    operations = [
        # Step 1: Add the new column WITHOUT unique constraint
        migrations.AddField(
            model_name='guest',
            name='secure_token',
            field=models.CharField(max_length=10, default='', blank=True),
        ),

        # Step 2: Populate the field with unique values
        migrations.RunPython(generate_secure_tokens),

        # Step 3: Enforce the UNIQUE constraint after assigning values
        migrations.AlterField(
            model_name='guest',
            name='secure_token',
            field=models.CharField(max_length=10, unique=True, blank=True),
        ),
    ]
