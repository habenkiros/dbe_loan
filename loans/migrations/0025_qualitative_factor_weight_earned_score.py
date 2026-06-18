# Sheet (2) – add Excel “Weight / Earned score” detail columns

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0024_appraisal_es_checklist'),
    ]

    operations = [
        migrations.AddField(
            model_name='appraisalqualitativefactor',
            name='weight',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Excel weight / maximum score for this factor.',
                max_digits=8,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='appraisalqualitativefactor',
            name='earned_score',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Excel earned score based on selected rating.',
                max_digits=8,
                null=True,
            ),
        ),
    ]

