# Add dossier_exported audit event type

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('collateral', '0013_tier3_dossier_exif_photo_types'),
    ]

    operations = [
        migrations.AlterField(
            model_name='collateralfieldauditlog',
            name='event_type',
            field=models.CharField(
                choices=[
                    ('site_gps_marked', 'Site GPS marked'),
                    ('photo_uploaded', 'Photo uploaded'),
                    ('photo_deleted', 'Photo deleted'),
                    ('boq_saved', 'BOQ quantities saved'),
                    ('valuation_edited', 'Valuation row edited'),
                    ('valuation_deleted', 'Valuation row deleted'),
                    ('collateral_submitted', 'Collateral submitted'),
                    ('weak_gps_attested', 'Weak GPS attested'),
                    ('unlock_requested', 'Unlock requested'),
                    ('unlock_approved', 'Unlock approved'),
                    ('unlock_rejected', 'Unlock rejected'),
                    ('engineering_approved', 'Engineering approved'),
                    ('engineering_returned', 'Engineering returned'),
                    ('dossier_exported', 'Dossier exported'),
                ],
                max_length=40,
            ),
        ),
    ]
