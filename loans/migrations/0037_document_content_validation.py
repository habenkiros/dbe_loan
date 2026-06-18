# Content validation sample phrases per document type

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0036_manager_queue_approval_fix'),
    ]

    operations = [
        migrations.AddField(
            model_name='loanapplicationdocumenttype',
            name='content_validation_min_matches',
            field=models.PositiveSmallIntegerField(
                default=1,
                help_text='Minimum number of sample phrases that must appear in the upload.',
            ),
        ),
        migrations.AddField(
            model_name='loanapplicationdocumenttype',
            name='content_validation_sample',
            field=models.TextField(
                blank=True,
                help_text=(
                    'Expected phrases or sample text for this document type — one phrase per line. '
                    'Uploaded files are scanned (PDF/image/DOCX) and must contain enough matching phrases.'
                ),
            ),
        ),
        migrations.AddField(
            model_name='loanapplicationdocumenttype',
            name='content_validation_strict',
            field=models.BooleanField(
                default=True,
                help_text='If checked, uploads that fail content validation are rejected before save.',
            ),
        ),
    ]
