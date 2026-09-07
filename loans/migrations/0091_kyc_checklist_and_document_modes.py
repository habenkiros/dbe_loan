from django.db import migrations, models


APPRAISAL_MODE_CHOICES = [
    ('', 'All modes'),
    ('msme', 'MSME / cashflow sheets'),
    ('corporate', 'Corporate / financial statements'),
    ('project', 'Project desk (viability, equity, plant)'),
    ('wholesale', 'Wholesale / PFI institution desk'),
    ('lease', 'Lease / hire-purchase asset desk'),
    ('ifb_murabaha', 'Murabaha cost-plus desk'),
    ('ifb_ijarah', 'Ijarah rental desk'),
    ('idea_equity', 'Idea / quasi-equity desk'),
    ('consumer', 'Consumer / HRM scorecard'),
]

UNIQUE_PACK_MODES = {
    'Feasibility / business plan': 'project',
    'Site / land evidence': 'project',
    'Promoter equity evidence': 'project',
    'Implementation schedule': 'project',
    'E&S screening note': 'project',
    'Goods specification': 'ifb_murabaha',
    'Supplier offer / invoice': 'ifb_murabaha',
    'Cost sheet (cost + markup)': 'ifb_murabaha',
    'NBE / license certificate': 'wholesale',
    'Audited financial statements': 'wholesale',
    'ESMS policy': 'wholesale',
    'On-lending / credit policy': 'wholesale',
    'PAR / NPL report': 'wholesale',
    'Start-up label / IP / MoLS evidence': 'idea_equity',
    'Cap table': 'idea_equity',
    'Business model note': 'idea_equity',
    'National ID / employment letter': 'consumer',
    'Salary evidence (3 months)': 'consumer',
    'Employer confirmation': 'consumer',
}


def stamp_document_modes(apps, schema_editor):
    LoanApplicationDocumentType = apps.get_model('loans', 'LoanApplicationDocumentType')
    for name, mode in UNIQUE_PACK_MODES.items():
        LoanApplicationDocumentType.objects.filter(name=name, for_appraisal_mode='').update(
            for_appraisal_mode=mode,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0090_spine_pend_crm_consumer'),
    ]

    operations = [
        migrations.AddField(
            model_name='creditdeskscreening',
            name='checklist',
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text='Required KYC ticks for this desk, e.g. {"identity_docs": true}.',
            ),
        ),
        migrations.AddField(
            model_name='creditdeskscreening',
            name='findings',
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text='Identity / sanctions snapshot captured when the pack is cleared.',
            ),
        ),
        migrations.AlterField(
            model_name='loanapplicationdocumenttype',
            name='for_appraisal_mode',
            field=models.CharField(
                blank=True,
                choices=APPRAISAL_MODE_CHOICES,
                default='',
                help_text='Limit this document type to one appraisal desk (blank = every product).',
                max_length=20,
            ),
        ),
        migrations.RunPython(stamp_document_modes, migrations.RunPython.noop),
    ]
