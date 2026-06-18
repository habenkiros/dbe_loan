# Wider qualitative rating; credit history status includes None

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0021_auto_20260319_1434'),
    ]

    operations = [
        migrations.AlterField(
            model_name='appraisalqualitativefactor',
            name='rating',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AlterField(
            model_name='appraisalcredithistoryentry',
            name='status',
            field=models.CharField(
                blank=True,
                choices=[
                    ('regular', 'Regular'),
                    ('settled_on_time', 'Settled on time'),
                    ('settled_late', 'Settled late'),
                    ('irregular', 'Irregular'),
                    ('defaulted', 'Defaulted'),
                    ('none', 'None'),
                ],
                max_length=30,
                null=True,
            ),
        ),
    ]
