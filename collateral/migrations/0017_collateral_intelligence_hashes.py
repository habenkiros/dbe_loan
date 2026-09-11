from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('collateral', '0016_site_gps_source_manual'),
    ]

    operations = [
        migrations.AddField(
            model_name='buildingimage',
            name='content_sha256',
            field=models.CharField(blank=True, db_index=True, max_length=64),
        ),
        migrations.AddField(
            model_name='buildingimage',
            name='perceptual_hash',
            field=models.CharField(blank=True, db_index=True, max_length=64),
        ),
        migrations.AddField(
            model_name='buildingimage',
            name='photo_type_suggested',
            field=models.CharField(
                blank=True,
                help_text='Assistive suggested type at upload (officer may override).',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='landvaluationimage',
            name='content_sha256',
            field=models.CharField(blank=True, db_index=True, max_length=64),
        ),
        migrations.AddField(
            model_name='landvaluationimage',
            name='perceptual_hash',
            field=models.CharField(blank=True, db_index=True, max_length=64),
        ),
        migrations.AddField(
            model_name='landvaluationimage',
            name='photo_type_suggested',
            field=models.CharField(
                blank=True,
                help_text='Assistive suggested type at upload (officer may override).',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='othercollateralitemimage',
            name='content_sha256',
            field=models.CharField(blank=True, db_index=True, max_length=64),
        ),
        migrations.AddField(
            model_name='othercollateralitemimage',
            name='perceptual_hash',
            field=models.CharField(blank=True, db_index=True, max_length=64),
        ),
        migrations.AddField(
            model_name='othercollateralitemimage',
            name='photo_type_suggested',
            field=models.CharField(
                blank=True,
                help_text='Assistive suggested type at upload (officer may override).',
                max_length=20,
            ),
        ),
    ]
