from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0047_es_signoff_help_text'),
    ]

    operations = [
        migrations.AddField(
            model_name='loanappraisal',
            name='banking_behavior',
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text='Account transaction metrics for banking pillar (turnover, NSF, stability, …).',
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='loanappraisal',
            name='banking_refreshed_at',
            field=models.DateTimeField(
                blank=True,
                help_text='When banking_behavior was last refreshed from core banking / mock.',
                null=True,
            ),
        ),
    ]
