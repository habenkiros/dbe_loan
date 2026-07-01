# Building site GPS + photo metadata for field visits

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('collateral', '0006_alter_subworkunitprice_options'),
    ]

    operations = [
        migrations.AddField(
            model_name='building',
            name='site_captured_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='building',
            name='site_gps_accuracy_m',
            field=models.DecimalField(
                blank=True, decimal_places=2, max_digits=10, null=True,
                help_text='GPS accuracy in metres when site was marked.',
            ),
        ),
        migrations.AddField(
            model_name='building',
            name='site_gps_lat',
            field=models.DecimalField(
                blank=True, decimal_places=8, max_digits=12, null=True,
                help_text='GPS latitude captured at the building site.',
            ),
        ),
        migrations.AddField(
            model_name='building',
            name='site_gps_lon',
            field=models.DecimalField(
                blank=True, decimal_places=8, max_digits=12, null=True,
                help_text='GPS longitude captured at the building site.',
            ),
        ),
        migrations.AddField(
            model_name='buildingimage',
            name='gps_accuracy_m',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name='buildingimage',
            name='photo_type',
            field=models.CharField(
                blank=True,
                choices=[
                    ('front', 'Front / facade'),
                    ('side', 'Side'),
                    ('rear', 'Rear'),
                    ('roof', 'Roof'),
                    ('interior', 'Interior'),
                    ('other', 'Other'),
                ],
                default='other',
                max_length=20,
            ),
        ),
    ]
