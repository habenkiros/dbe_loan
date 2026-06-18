# Per document-type authentication / upload rules

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0034_document_notification_kinds'),
    ]

    operations = [
        migrations.AddField(
            model_name='loanapplicationdocumenttype',
            name='allowed_extensions',
            field=models.CharField(
                blank=True,
                help_text='Comma-separated (e.g. pdf,jpg,png). Leave blank to use bank-wide default.',
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name='loanapplicationdocumenttype',
            name='auth_notes',
            field=models.CharField(
                blank=True,
                help_text='Optional hint shown to branch manager at upload (e.g. “Clear scan of both sides”).',
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name='loanapplicationdocumenttype',
            name='enable_external_id',
            field=models.BooleanField(
                default=False,
                help_text='Run external / core banking ID verification when TIN is on Sheet 1.',
            ),
        ),
        migrations.AddField(
            model_name='loanapplicationdocumenttype',
            name='enable_llm_check',
            field=models.BooleanField(
                default=False,
                help_text='Run LLM plausibility check on extracted text (e.g. bank statements).',
            ),
        ),
        migrations.AddField(
            model_name='loanapplicationdocumenttype',
            name='enable_ocr_match',
            field=models.BooleanField(
                default=False,
                help_text='Run OCR and match applicant name / TIN from Sheet 1 (recommended for ID, license).',
            ),
        ),
        migrations.AddField(
            model_name='loanapplicationdocumenttype',
            name='max_file_size_mb',
            field=models.PositiveIntegerField(
                blank=True,
                help_text='Max upload size for this document type. Leave blank to use bank-wide default.',
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='loanapplicationdocumenttype',
            name='require_officer_verification',
            field=models.BooleanField(
                default=False,
                help_text='If checked, officer must manually verify — auto-pass is not enough for collateral.',
            ),
        ),
    ]
