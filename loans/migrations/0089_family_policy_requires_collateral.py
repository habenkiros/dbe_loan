from django.db import migrations, models


def seed_policies_and_flags(apps, schema_editor):
    LoanCategory = apps.get_model('loans', 'LoanCategory')
    ProductFamilyPolicy = apps.get_model('loans', 'ProductFamilyPolicy')
    CollateralType = apps.get_model('loans', 'CollateralType')
    families = [
        ('general', 'General (MSME / corporate)', 'msme', True),
        ('project', 'Project financing', 'project', True),
        ('lease', 'Lease financing', 'lease', True),
        ('wholesale', 'Wholesale / PFI facility', 'wholesale', False),
        ('consumer', 'Consumer (housing / vehicle)', 'msme', True),
        ('ifb_murabaha', 'IFB — Murabaha', 'ifb_murabaha', True),
        ('ifb_ijarah', 'IFB — Ijarah', 'ifb_ijarah', True),
        ('external_fund', 'External fund window', 'msme', True),
        ('idea_equity', 'Idea / quasi-equity', 'idea_equity', False),
    ]
    kind_map = {
        'general': ('building', 'land', 'movable', 'mixed'),
        'external_fund': ('building', 'land', 'movable', 'mixed'),
        'project': ('building', 'land', 'mixed', 'financed'),
        'lease': ('financed',),
        'ifb_ijarah': ('financed',),
        'ifb_murabaha': ('financed', 'movable'),
        'consumer': ('building', 'financed'),
        'wholesale': (),
        'idea_equity': (),
    }
    for family, name, mode, needs in families:
        row, _ = ProductFamilyPolicy.objects.get_or_create(
            family=family,
            defaults={
                'name': name,
                'default_appraisal_mode': mode,
                'requires_collateral': needs,
            },
        )
        kinds = kind_map.get(family) or ()
        if kinds and not row.default_collateral.exists():
            types = CollateralType.objects.filter(kind__in=list(kinds))
            if types.exists():
                row.default_collateral.set(types)
    LoanCategory.objects.filter(
        product_family__in=['wholesale', 'idea_equity'],
        requires_collateral__isnull=True,
    ).update(requires_collateral=False)


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0088_family_collateral_kyc'),
    ]

    operations = [
        migrations.AddField(
            model_name='loancategory',
            name='requires_collateral',
            field=models.BooleanField(
                blank=True,
                default=None,
                help_text='Blank = use the family default. Off = unsecured. On = matching collateral types required.',
                null=True,
            ),
        ),
        migrations.CreateModel(
            name='ProductFamilyPolicy',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('family', models.CharField(
                    choices=[
                        ('general', 'General (MSME / corporate)'),
                        ('project', 'Project financing'),
                        ('lease', 'Lease financing'),
                        ('wholesale', 'Wholesale / PFI facility'),
                        ('consumer', 'Consumer (housing / vehicle)'),
                        ('ifb_murabaha', 'IFB — Murabaha'),
                        ('ifb_ijarah', 'IFB — Ijarah'),
                        ('external_fund', 'External fund window'),
                        ('idea_equity', 'Idea / quasi-equity'),
                    ],
                    db_index=True, max_length=20, unique=True,
                )),
                ('name', models.CharField(blank=True, max_length=120)),
                ('default_appraisal_mode', models.CharField(
                    choices=[
                        ('msme', 'MSME / cashflow sheets'),
                        ('corporate', 'Corporate / financial statements'),
                        ('project', 'Project desk (viability, equity, plant)'),
                        ('wholesale', 'Wholesale / PFI institution desk'),
                        ('lease', 'Lease / hire-purchase asset desk'),
                        ('ifb_murabaha', 'Murabaha cost-plus desk'),
                        ('ifb_ijarah', 'Ijarah rental desk'),
                        ('idea_equity', 'Idea / quasi-equity desk'),
                    ],
                    default='msme',
                    help_text='Pre-selected when a loan type uses this family. Can still be changed per category.',
                    max_length=20,
                )),
                ('requires_collateral', models.BooleanField(
                    default=True,
                    help_text='Default for new loan types in this family. Uncheck for unsecured products.',
                )),
                ('notes', models.TextField(blank=True)),
                ('default_collateral', models.ManyToManyField(
                    blank=True,
                    help_text='Suggested security types when the family requires collateral.',
                    related_name='family_policies',
                    to='loans.collateraltype',
                )),
            ],
            options={
                'verbose_name': 'Product family default',
                'verbose_name_plural': 'Product family defaults',
                'ordering': ['family'],
            },
        ),
        migrations.RunPython(seed_policies_and_flags, migrations.RunPython.noop),
    ]
