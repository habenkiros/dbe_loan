from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0094_kyc_biometric_ubo'),
    ]

    operations = [
        migrations.AddField(
            model_name='projectcashflowyear',
            name='revenue',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Sales / operating revenue for the year.',
                max_digits=20,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='projectcashflowyear',
            name='operating_cost',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Operating costs (materials, labour, overheads).',
                max_digits=20,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='projectcashflowyear',
            name='capacity_pct',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Capacity utilization % (100 = full). Used for break-even.',
                max_digits=6,
                null=True,
            ),
        ),
    ]
