# Tier 2: movable collateral fields + declared-address policy threshold

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('collateral', '0010_tier1_policy_unlock'),
        ('loans', '0041_collateral_tier2_geocode_engineering'),
    ]

    operations = [
        migrations.AddField(
            model_name='collateralpolicyconfig',
            name='declared_address_max_distance_from_site_m',
            field=models.PositiveIntegerField(
                default=3000,
                help_text='Flag when geocoded declared address is farther than this from field site GPS.',
            ),
        ),
        migrations.AddField(
            model_name='collateralpolicyconfig',
            name='block_submit_on_declared_address_mismatch',
            field=models.BooleanField(
                default=False,
                help_text='If enabled, large declared-address vs site GPS gap blocks collateral submit.',
            ),
        ),
        migrations.AddField(
            model_name='othercollateralitem',
            name='plate_number',
            field=models.CharField(blank=True, help_text='Plate / registration number.', max_length=50),
        ),
        migrations.AddField(
            model_name='othercollateralitem',
            name='chassis_vin',
            field=models.CharField(blank=True, help_text='Chassis or VIN.', max_length=80),
        ),
        migrations.AddField(
            model_name='othercollateralitem',
            name='year_made',
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='othercollateralitem',
            name='make_model',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name='othercollateralitem',
            name='odometer_or_hours',
            field=models.CharField(blank=True, help_text='Odometer (km) or operating hours.', max_length=50),
        ),
        migrations.AddField(
            model_name='othercollateralitem',
            name='condition_grade',
            field=models.CharField(
                blank=True,
                choices=[
                    ('excellent', 'Excellent'),
                    ('good', 'Good'),
                    ('fair', 'Fair'),
                    ('poor', 'Poor'),
                ],
                max_length=20,
            ),
        ),
    ]
