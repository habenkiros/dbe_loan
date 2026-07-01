# Identity match fields: compare loan data vs document OCR text

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0039_reference_sample_document_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='loanapplicationdocumenttype',
            name='identity_match_fields',
            field=models.CharField(
                blank=True,
                default='applicant_name,phone_number,tin_number',
                help_text='Comma-separated fields to verify in the document: applicant_name, phone_number, tin_number, business_name.',
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name='loanapplicationdocumenttype',
            name='identity_match_strict',
            field=models.BooleanField(
                default=False,
                help_text='If checked, reject upload when identity fields do not match (otherwise flag for officer review).',
            ),
        ),
        migrations.AlterField(
            model_name='loanapplicationdocumenttype',
            name='enable_ocr_match',
            field=models.BooleanField(
                default=False,
                help_text='Match applicant name, phone, TIN, business name from the loan against OCR text in the upload.',
            ),
        ),
    ]
