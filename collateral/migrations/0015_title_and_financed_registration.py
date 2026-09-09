from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('collateral', '0014_dossier_exported_event'),
    ]

    operations = [
        migrations.AddField(
            model_name='building',
            name='owner_kind',
            field=models.CharField(
                choices=[
                    ('borrower', 'Borrower / applicant'),
                    ('third_party', 'Third party (guarantor / family)'),
                    ('bank', 'Bank holds title (financed / lease)'),
                ],
                default='borrower',
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name='building',
            name='owner_name',
            field=models.CharField(
                blank=True,
                help_text='Leave blank when the borrower owns it — applicant name is used.',
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name='building',
            name='title_reference',
            field=models.CharField(
                blank=True,
                help_text='Deed, plot, libretto, plate book, or supplier invoice reference.',
                max_length=80,
            ),
        ),
        migrations.AddField(
            model_name='building',
            name='title_office',
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name='landvaluation',
            name='owner_kind',
            field=models.CharField(
                choices=[
                    ('borrower', 'Borrower / applicant'),
                    ('third_party', 'Third party (guarantor / family)'),
                    ('bank', 'Bank holds title (financed / lease)'),
                ],
                default='borrower',
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name='landvaluation',
            name='owner_name',
            field=models.CharField(
                blank=True,
                help_text='Leave blank when the borrower owns it — applicant name is used.',
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name='landvaluation',
            name='title_reference',
            field=models.CharField(
                blank=True,
                help_text='Deed, plot, libretto, plate book, or supplier invoice reference.',
                max_length=80,
            ),
        ),
        migrations.AddField(
            model_name='landvaluation',
            name='title_office',
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name='othercollateralitem',
            name='owner_kind',
            field=models.CharField(
                choices=[
                    ('borrower', 'Borrower / applicant'),
                    ('third_party', 'Third party (guarantor / family)'),
                    ('bank', 'Bank holds title (financed / lease)'),
                ],
                default='borrower',
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name='othercollateralitem',
            name='owner_name',
            field=models.CharField(
                blank=True,
                help_text='Leave blank when the borrower owns it — applicant name is used.',
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name='othercollateralitem',
            name='title_reference',
            field=models.CharField(
                blank=True,
                help_text='Deed, plot, libretto, plate book, or supplier invoice reference.',
                max_length=80,
            ),
        ),
        migrations.AddField(
            model_name='othercollateralitem',
            name='title_office',
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name='othercollateralitem',
            name='acquisition_status',
            field=models.CharField(
                choices=[
                    ('owned', 'Already owned — on site now'),
                    ('to_be_purchased', 'To be purchased with this loan'),
                ],
                default='owned',
                help_text='Financed assets are registered before delivery — plate/serial wait until on site.',
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name='othercollateralitemimage',
            name='photo_type',
            field=models.CharField(
                blank=True,
                choices=[
                    ('plate', 'Plate / registration'),
                    ('asset', 'Full asset'),
                    ('serial_label', 'Serial / chassis label'),
                    ('offer', 'Supplier offer / invoice'),
                    ('other', 'Other'),
                ],
                default='other',
                max_length=20,
            ),
        ),
    ]
