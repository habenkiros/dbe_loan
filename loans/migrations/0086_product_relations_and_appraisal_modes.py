from django.db import migrations, models


APPRAISAL_MODE_CHOICES = [
    ('msme', 'MSME / cashflow sheets'),
    ('corporate', 'Corporate / financial statements'),
    ('project', 'Project desk (viability, equity, plant)'),
    ('wholesale', 'Wholesale / PFI institution desk'),
    ('lease', 'Lease / hire-purchase asset desk'),
    ('ifb_murabaha', 'Murabaha cost-plus desk'),
    ('ifb_ijarah', 'Ijarah rental desk'),
    ('idea_equity', 'Idea / quasi-equity desk'),
]


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0085_rehab_sla'),
    ]

    operations = [
        migrations.AlterField(
            model_name='loancategory',
            name='appraisal_mode',
            field=models.CharField(
                choices=APPRAISAL_MODE_CHOICES,
                default='msme',
                help_text='Appraisal modality. MSME/corporate = 7-sheet wizard. Other values use the product desk.',
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name='loanappraisal',
            name='appraisal_mode',
            field=models.CharField(
                choices=APPRAISAL_MODE_CHOICES,
                db_index=True,
                default='msme',
                help_text='Copied from the loan type. Product desks are not the 7-sheet wizard.',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='loancategory',
            name='allowed_funds',
            field=models.ManyToManyField(
                blank=True,
                help_text='Empty = any unrestricted window. Donor lines are usually attached here.',
                related_name='eligible_categories',
                to='loans.financingfund',
            ),
        ),
        migrations.AddField(
            model_name='loancategory',
            name='allowed_collateral',
            field=models.ManyToManyField(
                blank=True,
                help_text='Empty = any collateral type. Lease should be machinery; project land/building.',
                related_name='loan_categories',
                to='loans.collateraltype',
            ),
        ),
    ]
