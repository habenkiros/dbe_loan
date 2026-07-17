# Tier 3: EXIF GPS fields, required movable photo types, dossier-related policy

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('collateral', '0012_alter_collateralfieldauditlog_event_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='buildingimage',
            name='exif_gps_lat',
            field=models.DecimalField(blank=True, decimal_places=8, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name='buildingimage',
            name='exif_gps_lon',
            field=models.DecimalField(blank=True, decimal_places=8, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name='buildingimage',
            name='browser_vs_exif_distance_m',
            field=models.DecimalField(
                blank=True, decimal_places=1, help_text='Distance between browser capture GPS and photo EXIF GPS (metres).',
                max_digits=12, null=True,
            ),
        ),
        migrations.AddField(
            model_name='landvaluationimage',
            name='exif_gps_lat',
            field=models.DecimalField(blank=True, decimal_places=8, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name='landvaluationimage',
            name='exif_gps_lon',
            field=models.DecimalField(blank=True, decimal_places=8, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name='landvaluationimage',
            name='browser_vs_exif_distance_m',
            field=models.DecimalField(
                blank=True, decimal_places=1, help_text='Distance between browser capture GPS and photo EXIF GPS (metres).',
                max_digits=12, null=True,
            ),
        ),
        migrations.AddField(
            model_name='othercollateralitemimage',
            name='exif_gps_lat',
            field=models.DecimalField(blank=True, decimal_places=8, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name='othercollateralitemimage',
            name='exif_gps_lon',
            field=models.DecimalField(blank=True, decimal_places=8, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name='othercollateralitemimage',
            name='browser_vs_exif_distance_m',
            field=models.DecimalField(
                blank=True, decimal_places=1, help_text='Distance between browser capture GPS and photo EXIF GPS (metres).',
                max_digits=12, null=True,
            ),
        ),
        migrations.AddField(
            model_name='collateralpolicyconfig',
            name='require_movable_photo_types',
            field=models.BooleanField(
                default=True,
                help_text='Require plate, full asset, and chassis/serial photos for vehicle/machinery items.',
            ),
        ),
        migrations.AddField(
            model_name='collateralpolicyconfig',
            name='exif_gps_mismatch_warn_m',
            field=models.PositiveIntegerField(
                default=200,
                help_text='Warn when photo EXIF GPS differs from browser GPS by more than this (metres).',
            ),
        ),
        migrations.AddField(
            model_name='collateralpolicyconfig',
            name='block_submit_on_exif_gps_mismatch',
            field=models.BooleanField(
                default=False,
                help_text='If enabled, large EXIF vs browser GPS mismatch blocks collateral submit.',
            ),
        ),
    ]
