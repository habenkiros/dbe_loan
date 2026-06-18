# Field extraction mappings from documents into appraisal sheets

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0037_document_content_validation'),
    ]

    operations = [
        migrations.AddField(
            model_name='loanapplicationdocumenttype',
            name='content_extraction_mappings',
            field=models.TextField(
                blank=True,
                help_text=(
                    'Auto-fill appraisal fields from this document — one per line: '
                    'field_name=Label in document, or field_name=regex:pattern. '
                    'Example: tin_number=TIN  business_name=Business Name'
                ),
            ),
        ),
    ]
