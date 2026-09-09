from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('collateral', '0015_title_and_financed_registration'),
    ]

    operations = [
        migrations.AddField(
            model_name='building',
            name='site_gps_source',
            field=models.CharField(
                blank=True,
                choices=[('device', 'Device GPS'), ('manual', 'Manual latitude / longitude')],
                default='',
                help_text='How the site pin was set — device capture or officer-entered coordinates.',
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name='landvaluation',
            name='site_gps_source',
            field=models.CharField(
                blank=True,
                choices=[('device', 'Device GPS'), ('manual', 'Manual latitude / longitude')],
                default='',
                help_text='How the site pin was set — device capture or officer-entered coordinates.',
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name='othercollateralitem',
            name='site_gps_source',
            field=models.CharField(
                blank=True,
                choices=[('device', 'Device GPS'), ('manual', 'Manual latitude / longitude')],
                default='',
                help_text='Optional inspection/yard pin only — not the asset identity for vehicles.',
                max_length=16,
            ),
        ),
    ]
