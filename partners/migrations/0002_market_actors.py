# Phase 1 market actors: replace unused CRM tables with market intelligence models.

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('partners', '0001_initial'),
        ('collateral', '0014_dossier_exported_event'),
        ('loans', '0058_agent_conversation_story'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.DeleteModel(name='PartnerActivity'),
        migrations.DeleteModel(name='Partner'),
        migrations.CreateModel(
            name='MarketActor',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
                ('actor_kind', models.CharField(choices=[('dealer', 'Dealer / shop'), ('broker', 'Broker'), ('sales_person', 'Sales person'), ('supplier', 'Supplier'), ('cooperative', 'Cooperative / SACCO'), ('other', 'Other')], db_index=True, default='dealer', max_length=30)),
                ('phone_number', models.CharField(blank=True, max_length=30)),
                ('contact_person', models.CharField(blank=True, max_length=120)),
                ('address', models.CharField(blank=True, max_length=500)),
                ('product_focus', models.CharField(choices=[('building_materials', 'Building materials / construction'), ('land', 'Land / plots'), ('vehicle', 'Vehicles'), ('machinery', 'Machinery / equipment'), ('other', 'Other movable'), ('mixed', 'Mixed')], db_index=True, default='building_materials', max_length=30)),
                ('product_lines', models.CharField(blank=True, help_text='e.g. cement, HCB, steel, solar.', max_length=255)),
                ('trust_status', models.CharField(choices=[('pending', 'Pending'), ('trusted', 'Trusted'), ('suspended', 'Suspended')], db_index=True, default='pending', max_length=20)),
                ('is_active', models.BooleanField(db_index=True, default=True)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('branch', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='market_actors', to='loans.branch')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='market_actors_created', to=settings.AUTH_USER_MODEL)),
                ('primary_city', models.ForeignKey(blank=True, help_text='Main woreda/city this actor operates in.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='market_actors', to='loans.city')),
            ],
            options={'ordering': ['name']},
        ),
        migrations.CreateModel(
            name='MarketObservation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('asset_class', models.CharField(choices=[('building', 'Building / construction item'), ('land', 'Land (ETB/m²)'), ('vehicle', 'Vehicle'), ('machinery', 'Machinery'), ('other', 'Other')], db_index=True, default='building', max_length=20)),
                ('item_label', models.CharField(help_text='Free-text item name if not linked to catalog (e.g. cement 50kg bag).', max_length=255)),
                ('unit', models.CharField(blank=True, help_text='e.g. bag, m², m³, piece', max_length=40)),
                ('unit_price_etb', models.DecimalField(decimal_places=2, max_digits=20)),
                ('quantity', models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ('condition', models.CharField(choices=[('new', 'New'), ('used', 'Used'), ('na', 'N/A')], default='na', max_length=10)),
                ('observed_at', models.DateField(db_index=True, default=django.utils.timezone.localdate)),
                ('channel', models.CharField(choices=[('staff', 'Staff quote proxy'), ('portal', 'Dealer portal'), ('invite', 'Invite link'), ('import', 'Excel / bulk import'), ('sms', 'SMS / USSD')], db_index=True, default='staff', max_length=20)),
                ('status', models.CharField(choices=[('active', 'Active'), ('pending', 'Pending review'), ('rejected', 'Rejected')], db_index=True, default='active', max_length=20)),
                ('notes', models.TextField(blank=True)),
                ('site_lat', models.DecimalField(blank=True, decimal_places=7, max_digits=10, null=True)),
                ('site_lon', models.DecimalField(blank=True, decimal_places=7, max_digits=10, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('branch', models.ForeignKey(help_text='Denormalized for filtering; mirrors actor.branch.', on_delete=django.db.models.deletion.PROTECT, related_name='market_observations', to='loans.branch')),
                ('city', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='market_observations', to='loans.city')),
                ('market_actor', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='observations', to='partners.marketactor')),
                ('recorded_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='market_observations_recorded', to=settings.AUTH_USER_MODEL)),
                ('sub_sub_work', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='market_observations', to='collateral.subsubwork')),
                ('sub_work', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='market_observations', to='collateral.subwork')),
            ],
            options={
                'verbose_name': 'market observation',
                'verbose_name_plural': 'market observations',
                'ordering': ['-observed_at', '-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='marketobservation',
            index=models.Index(fields=['branch', 'observed_at'], name='partners_ma_branch__obsdate_idx'),
        ),
        migrations.AddIndex(
            model_name='marketobservation',
            index=models.Index(fields=['city', 'asset_class', 'observed_at'], name='partners_ma_city_asset_idx'),
        ),
        migrations.AddIndex(
            model_name='marketobservation',
            index=models.Index(fields=['status', 'observed_at'], name='partners_ma_status_date_idx'),
        ),
        migrations.AddIndex(
            model_name='marketobservation',
            index=models.Index(fields=['market_actor', 'observed_at'], name='partners_ma_actor_date_idx'),
        ),
        migrations.AddIndex(
            model_name='marketactor',
            index=models.Index(fields=['branch', 'is_active', 'name'], name='partners_ma_br_active_idx'),
        ),
        migrations.AddIndex(
            model_name='marketactor',
            index=models.Index(fields=['branch', 'actor_kind'], name='partners_ma_br_kind_idx'),
        ),
        migrations.AddIndex(
            model_name='marketactor',
            index=models.Index(fields=['trust_status', 'product_focus'], name='partners_ma_trust_focus_idx'),
        ),
        migrations.AddConstraint(
            model_name='marketactor',
            constraint=models.UniqueConstraint(fields=('branch', 'name'), name='partners_unique_actor_name_per_branch'),
        ),
    ]
