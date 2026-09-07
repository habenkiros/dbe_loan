from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('loans', '0084_murabaha_and_idea'),
    ]

    operations = [
        migrations.CreateModel(
            name='RehabCase',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('stage', models.CharField(
                    choices=[
                        ('watchlist', 'Watchlist'),
                        ('restructure', 'Restructure'),
                        ('technical_assistance', 'Technical assistance'),
                        ('recover', 'Recover'),
                        ('foreclosure', 'Foreclosure (last)'),
                        ('closed', 'Closed'),
                    ],
                    db_index=True,
                    default='watchlist',
                    max_length=24,
                )),
                ('note', models.TextField(blank=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('loan_request', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='rehab',
                    to='loans.loanrequest',
                )),
                ('updated_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='rehab_cases_updated',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
        ),
        migrations.CreateModel(
            name='RehabEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('from_stage', models.CharField(blank=True, max_length=24)),
                ('to_stage', models.CharField(max_length=24)),
                ('note', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('case', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='events',
                    to='loans.rehabcase',
                )),
                ('recorded_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='rehab_events',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'ordering': ['-created_at', '-id'],
            },
        ),
        migrations.CreateModel(
            name='InsurancePolicy',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(
                    choices=[
                        ('asset', 'Asset / machinery'),
                        ('project', 'Project / works'),
                        ('life', 'Life / credit life'),
                    ],
                    default='asset',
                    max_length=16,
                )),
                ('insurer', models.CharField(max_length=255)),
                ('policy_number', models.CharField(blank=True, max_length=80)),
                ('dbe_co_beneficiary', models.BooleanField(default=True)),
                ('starts_on', models.DateField(blank=True, null=True)),
                ('expires_on', models.DateField(blank=True, null=True)),
                ('note', models.CharField(blank=True, max_length=400)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('loan_request', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='insurance_policies',
                    to='loans.loanrequest',
                )),
                ('recorded_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='insurance_policies_recorded',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'ordering': ['expires_on', 'id'],
            },
        ),
        migrations.CreateModel(
            name='RevaluationDiary',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('due_on', models.DateField()),
                ('completed_on', models.DateField(blank=True, null=True)),
                ('note', models.CharField(blank=True, max_length=400)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('loan_request', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='revaluations',
                    to='loans.loanrequest',
                )),
                ('recorded_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='revaluations_recorded',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'ordering': ['due_on', 'id'],
            },
        ),
        migrations.CreateModel(
            name='LoanAppeal',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('level', models.CharField(
                    choices=[('president', 'President'), ('board', 'Board')],
                    default='president',
                    max_length=16,
                )),
                ('status', models.CharField(
                    choices=[
                        ('open', 'Open'),
                        ('upheld', 'Upheld'),
                        ('dismissed', 'Dismissed'),
                    ],
                    db_index=True,
                    default='open',
                    max_length=12,
                )),
                ('grounds', models.TextField()),
                ('decision_note', models.TextField(blank=True)),
                ('filed_at', models.DateTimeField(auto_now_add=True)),
                ('decided_at', models.DateTimeField(blank=True, null=True)),
                ('loan_request', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='appeals',
                    to='loans.loanrequest',
                )),
                ('filed_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='appeals_filed',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('decided_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='appeals_decided',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'ordering': ['-filed_at', '-id'],
            },
        ),
    ]
