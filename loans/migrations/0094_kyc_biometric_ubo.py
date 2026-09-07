from django.db import migrations, models


def seed_ubo_document_types(apps, schema_editor):
    LoanApplicationDocumentType = apps.get_model('loans', 'LoanApplicationDocumentType')
    rows = [
        ('Director / beneficial owner ID', 12, True),
        ('UBO ownership evidence', 13, False),
        ('Guarantor identity document', 14, True),
    ]
    for name, order, ocr in rows:
        LoanApplicationDocumentType.objects.get_or_create(
            name=name,
            defaults={
                'order': order,
                'is_required': False,
                'enable_ocr_match': ocr,
                'allowed_extensions': 'pdf,jpg,jpeg,png',
                'max_file_size_mb': 10,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0093_auto_20260907_2007'),
    ]

    operations = [
        migrations.AddField(
            model_name='kycparty',
            name='biometric_payload',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='kycparty',
            name='selfie',
            field=models.FileField(
                blank=True,
                help_text='Applicant / party photo evidence. Vendor templates are not stored.',
                null=True,
                upload_to='kyc/selfies/%Y/%m/',
            ),
        ),
        migrations.AlterField(
            model_name='kycparty',
            name='share_percent',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Ownership share for UBO / director.',
                max_digits=6,
                null=True,
            ),
        ),
        migrations.RunPython(seed_ubo_document_types, migrations.RunPython.noop),
    ]
