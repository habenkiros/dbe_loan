from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0078_sanctions_pep_screening'),
    ]

    operations = [
        migrations.AddField(
            model_name='loancategory',
            name='product_family',
            field=models.CharField(
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
                db_index=True,
                default='general',
                help_text='Lifecycle overlay (project, lease, IFB, …). Appraisal wizard is still MSME or corporate until a family engine exists.',
                max_length=20,
            ),
        ),
        migrations.CreateModel(
            name='FinancingFund',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(max_length=40, unique=True)),
                ('name', models.CharField(max_length=255)),
                ('kind', models.CharField(
                    choices=[
                        ('own_book', 'Own book'),
                        ('government', 'Government / MoF line'),
                        ('donor', 'Donor / DFI line'),
                        ('other', 'Other'),
                    ],
                    db_index=True,
                    default='own_book',
                    max_length=20,
                )),
                ('source_name', models.CharField(
                    blank=True,
                    help_text='e.g. KfW / EU, IFAD, EIB, Ministry of Finance.',
                    max_length=255,
                )),
                ('is_active', models.BooleanField(db_index=True, default=True)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='financing_fund',
            field=models.ForeignKey(
                blank=True,
                help_text='Optional donor / government / own-book window this file is booked against.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='loan_requests',
                to='loans.financingfund',
            ),
        ),
    ]
