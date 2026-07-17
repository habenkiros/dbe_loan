from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0044_appraisal_credit_scorecard'),
    ]

    operations = [
        migrations.AddField(
            model_name='loanrequestbasicinfo',
            name='field_sources',
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text='Per-field provenance: registration, document, banking, manual, or default.',
            ),
        ),
    ]
