# Sheet (4) E&S structured checklist items (Excel environmental & social questionnaire)

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0023_sheet3_phase1_phase2_cashflow'),
    ]

    operations = [
        migrations.CreateModel(
            name='AppraisalESChecklistItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('section_key', models.CharField(max_length=40)),
                ('section_label', models.CharField(max_length=120)),
                ('item_key', models.CharField(max_length=80)),
                ('question_text', models.TextField(help_text='Checklist question (from workbook).')),
                (
                    'response_yes_no',
                    models.CharField(
                        blank=True,
                        choices=[('', '—'), ('yes', 'Yes'), ('no', 'No'), ('na', 'N/A')],
                        default='',
                        help_text='Yes / No / N/A where applicable.',
                        max_length=10,
                    ),
                ),
                (
                    'description',
                    models.TextField(
                        blank=True,
                        help_text='Description / elaboration (Excel adjacent column).',
                        null=True,
                    ),
                ),
                (
                    'mitigation',
                    models.TextField(
                        blank=True,
                        help_text='Mitigation or action points.',
                        null=True,
                    ),
                ),
                ('display_order', models.PositiveIntegerField(default=0)),
                (
                    'appraisal',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='es_checklist_items',
                        to='loans.loanappraisal',
                    ),
                ),
            ],
            options={
                'verbose_name': 'E&S checklist item',
                'verbose_name_plural': 'E&S checklist items',
                'ordering': ['display_order', 'id'],
                'unique_together': {('appraisal', 'item_key')},
            },
        ),
    ]
