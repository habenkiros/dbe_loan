import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def seed_financed_and_lock_modes(apps, schema_editor):
    CollateralType = apps.get_model('loans', 'CollateralType')
    LoanCategory = apps.get_model('loans', 'LoanCategory')
    for name in (
        'Financed machinery / plant (from this loan)',
        'Financed vehicle (from this loan)',
    ):
        obj, created = CollateralType.objects.get_or_create(
            name=name, defaults={'kind': 'financed'},
        )
        if not created and obj.kind != 'financed':
            obj.kind = 'financed'
            obj.save(update_fields=['kind'])
    lock = {
        'project': 'project',
        'lease': 'lease',
        'wholesale': 'wholesale',
        'ifb_murabaha': 'ifb_murabaha',
        'ifb_ijarah': 'ifb_ijarah',
        'idea_equity': 'idea_equity',
        'consumer': 'msme',
        'external_fund': 'msme',
    }
    for cat in LoanCategory.objects.all():
        want = lock.get(cat.product_family)
        if want and cat.appraisal_mode != want:
            cat.appraisal_mode = want
            cat.save(update_fields=['appraisal_mode'])


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('loans', '0087_dbe_prototyping_desks'),
    ]

    operations = [
        migrations.AlterField(
            model_name='collateraltype',
            name='kind',
            field=models.CharField(
                blank=True,
                choices=[
                    ('building', 'Building / house (BOQ)'),
                    ('land', 'Land (size × price)'),
                    ('movable', 'Vehicle / machinery / other movable (already owned)'),
                    ('mixed', 'Mixed (sum engines that apply)'),
                    ('financed', 'Financed by this loan (machinery / vehicle / plant to be bought)'),
                ],
                db_index=True,
                default='',
                help_text='Which estimation engine(s) this type uses. Blank infers from the name. Mixed sums building + land + movable that have data.',
                max_length=20,
            ),
        ),
        migrations.CreateModel(
            name='CreditDeskScreening',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('stage', models.CharField(
                    choices=[('kyc', 'Document screening & KYC')],
                    db_index=True, default='kyc', max_length=16,
                )),
                ('desk', models.CharField(
                    choices=[
                        ('scan_admin', 'Scanning / Admin'),
                        ('crm', 'CRM — financial / KYC'),
                        ('engineering', 'Engineering — technical pack'),
                        ('legal', 'Legal — legal pack'),
                    ],
                    db_index=True, max_length=16,
                )),
                ('status', models.CharField(
                    choices=[
                        ('pending', 'Pending'),
                        ('cleared', 'Cleared'),
                        ('returned', 'Returned'),
                    ],
                    db_index=True, default='pending', max_length=12,
                )),
                ('note', models.TextField(blank=True)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('loan_request', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='desk_screenings',
                    to='loans.loanrequest',
                )),
                ('reviewed_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='credit_desk_screenings',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'ordering': ['desk', 'id'],
                'unique_together': {('loan_request', 'stage', 'desk')},
            },
        ),
        migrations.RunPython(seed_financed_and_lock_modes, migrations.RunPython.noop),
    ]
