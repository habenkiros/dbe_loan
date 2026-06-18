# Official reference sample file per document type (Path B validation)

from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0038_document_extraction_mappings'),
    ]

    operations = [
        migrations.AddField(
            model_name='loanapplicationdocumenttype',
            name='reference_min_similarity',
            field=models.DecimalField(
                decimal_places=3,
                default=Decimal('0.080'),
                help_text='Minimum text similarity (0–1) vs reference sample. Lower = more lenient for scans.',
                max_digits=4,
            ),
        ),
        migrations.AddField(
            model_name='loanapplicationdocumenttype',
            name='reference_sample',
            field=models.FileField(
                blank=True,
                help_text='Official blank/sample PDF or image — system learns validation phrases from this file.',
                null=True,
                upload_to='document_type_samples/%Y/%m/',
            ),
        ),
        migrations.AddField(
            model_name='loanapplicationdocumenttype',
            name='reference_sample_analyzed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='loanapplicationdocumenttype',
            name='reference_sample_profile',
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text='Auto-generated OCR profile from reference_sample (phrases, mappings, similarity).',
            ),
        ),
        migrations.AddField(
            model_name='loanapplicationdocumenttype',
            name='use_reference_sample_validation',
            field=models.BooleanField(
                default=True,
                help_text='Compare uploads to the analyzed reference sample (in addition to manual phrases).',
            ),
        ),
    ]
