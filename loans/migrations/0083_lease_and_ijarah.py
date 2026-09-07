from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('loans', '0082_fund_and_wholesale'),
    ]

    operations = [
        migrations.CreateModel(
            name='LeaseAssetProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('supplier_name', models.CharField(blank=True, max_length=255)),
                ('supplier_invoice_ref', models.CharField(blank=True, max_length=80)),
                ('is_new_goods', models.BooleanField(default=True, help_text='DBE lease is new capital goods only.')),
                ('asset_description', models.CharField(blank=True, max_length=255)),
                ('make_model', models.CharField(blank=True, max_length=255)),
                ('serial_number', models.CharField(blank=True, max_length=80)),
                ('asset_price', models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True)),
                ('price_checked', models.BooleanField(default=False)),
                ('price_check_note', models.CharField(blank=True, max_length=400)),
                ('ancillary_amount', models.DecimalField(
                    blank=True, decimal_places=2,
                    help_text='Insurance, transport, install — at most 15% of asset price.',
                    max_digits=20, null=True,
                )),
                ('lessee_contribution', models.DecimalField(
                    blank=True, decimal_places=2,
                    help_text='Lessee own contribution — at least 20% of asset price.',
                    max_digits=20, null=True,
                )),
                ('other_bank_wc_name', models.CharField(blank=True, max_length=255)),
                ('other_bank_wc_amount', models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True)),
                ('commissioning_date', models.DateField(blank=True, null=True)),
                ('delivery_date', models.DateField(blank=True, null=True)),
                ('commencement_date', models.DateField(
                    blank=True, help_text='Timing follows delivery / commencement, not approval day.',
                    null=True,
                )),
                ('insurance_in_force', models.BooleanField(default=False)),
                ('insurance_policy', models.CharField(blank=True, max_length=80)),
                ('insurance_expiry', models.DateField(blank=True, null=True)),
                ('location', models.CharField(blank=True, max_length=255)),
                ('gps_lat', models.DecimalField(blank=True, decimal_places=8, max_digits=12, null=True)),
                ('gps_lon', models.DecimalField(blank=True, decimal_places=8, max_digits=12, null=True)),
                ('residual_value', models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True)),
                ('bank_holds_title', models.BooleanField(default=True)),
                ('asset_status', models.CharField(
                    choices=[
                        ('on_lease', 'On lease — bank holds title'),
                        ('buyout', 'Buyout / title passed'),
                        ('expansion', 'Expansion after two good years'),
                    ],
                    default='on_lease',
                    max_length=16,
                )),
                ('monthly_rent', models.DecimalField(
                    blank=True, decimal_places=2,
                    help_text='Ijarah rental — not hire-purchase interest.',
                    max_digits=20, null=True,
                )),
                ('rent_term_months', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('notes', models.TextField(blank=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('loan_request', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='lease_asset',
                    to='loans.loanrequest',
                )),
                ('updated_by', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='lease_assets_updated',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
        ),
        migrations.CreateModel(
            name='IjarahRentLine',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('period_number', models.PositiveSmallIntegerField()),
                ('due_date', models.DateField(blank=True, null=True)),
                ('rent_amount', models.DecimalField(decimal_places=2, max_digits=20)),
                ('profile', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='rent_lines',
                    to='loans.leaseassetprofile',
                )),
            ],
            options={
                'ordering': ['period_number', 'id'],
                'unique_together': {('profile', 'period_number')},
            },
        ),
        migrations.CreateModel(
            name='ShariaReview',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(
                    choices=[('ijarah', 'Ijarah'), ('murabaha', 'Murabaha')],
                    default='ijarah',
                    max_length=16,
                )),
                ('status', models.CharField(
                    choices=[
                        ('pending', 'Pending'),
                        ('cleared', 'Cleared'),
                        ('returned', 'Returned'),
                    ],
                    db_index=True,
                    default='pending',
                    max_length=12,
                )),
                ('note', models.TextField(blank=True)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('loan_request', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='sharia_reviews',
                    to='loans.loanrequest',
                )),
                ('reviewed_by', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='sharia_reviews',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={'ordering': ['-created_at', '-id']},
        ),
    ]
