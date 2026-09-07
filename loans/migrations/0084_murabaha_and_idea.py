from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('loans', '0083_lease_and_ijarah'),
    ]

    operations = [
        migrations.CreateModel(
            name='MurabahaContract',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('goods_description', models.CharField(blank=True, max_length=255)),
                ('supplier_name', models.CharField(blank=True, max_length=255)),
                ('cost_price', models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True)),
                ('markup_pct', models.DecimalField(
                    blank=True, decimal_places=2,
                    help_text='Export Murabaha uses a lower markup than domestic.',
                    max_digits=6, null=True,
                )),
                ('scope', models.CharField(
                    choices=[('domestic', 'Domestic'), ('export', 'Export — lower markup')],
                    default='domestic',
                    max_length=12,
                )),
                ('selling_price', models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True)),
                ('tenor_months', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('routed_to_ifb_ho', models.BooleanField(
                    default=False,
                    help_text='Project-scale Murabaha is routed to IFB Directorate / HO.',
                )),
                ('notes', models.TextField(blank=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('loan_request', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='murabaha',
                    to='loans.loanrequest',
                )),
                ('updated_by', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='murabaha_contracts_updated',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
        ),
        migrations.CreateModel(
            name='IdeaProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('venture_name', models.CharField(blank=True, max_length=255)),
                ('founded_year', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('implements_in_ethiopia', models.BooleanField(default=True)),
                ('has_ip', models.BooleanField(default=False)),
                ('has_mols_training', models.BooleanField(default=False)),
                ('has_startup_label', models.BooleanField(default=False)),
                ('proposed_dbe_share_pct', models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ('sector', models.CharField(blank=True, max_length=120)),
                ('notes', models.TextField(blank=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('loan_request', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='idea_profile',
                    to='loans.loanrequest',
                )),
                ('updated_by', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='idea_profiles_updated',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
        ),
        migrations.CreateModel(
            name='CapTableEntry',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('holder_name', models.CharField(max_length=255)),
                ('role', models.CharField(
                    choices=[
                        ('founder', 'Founder / promoter'),
                        ('dbe', 'DBE'),
                        ('other', 'Other investor'),
                    ],
                    default='founder',
                    max_length=12,
                )),
                ('share_pct', models.DecimalField(decimal_places=2, max_digits=5)),
                ('note', models.CharField(blank=True, max_length=255)),
                ('profile', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='cap_table',
                    to='loans.ideaprofile',
                )),
            ],
            options={'ordering': ['role', 'id']},
        ),
    ]
