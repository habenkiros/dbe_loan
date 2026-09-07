from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('applicant_portal', '0005_alter_applicantportalsettings_require_customer_lookup'),
    ]

    operations = [
        migrations.AddField(
            model_name='applicantaccount',
            name='actor_kind',
            field=models.CharField(
                choices=[
                    ('person', 'Customer (MSME / retail)'),
                    ('institution', 'Institution (bank / MFI / PFI)'),
                    ('promoter', 'Project / idea promoter'),
                ],
                db_index=True,
                default='person',
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name='applicantaccount',
            name='institution_name',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name='applicantaccount',
            name='license_number',
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AlterField(
            model_name='applicantaccount',
            name='customer_number',
            field=models.CharField(
                db_index=True,
                help_text='CBS customer ID for persons. Generated portal ID for institutions / promoters.',
                max_length=50,
                unique=True,
            ),
        ),
    ]
