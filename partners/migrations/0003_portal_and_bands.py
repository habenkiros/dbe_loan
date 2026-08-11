# Portal credentials + market price bands

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('partners', '0002_market_actors'),
        ('collateral', '0014_dossier_exported_event'),
        ('loans', '0058_agent_conversation_story'),
    ]

    operations = [
        migrations.AddField(
            model_name='marketactor',
            name='portal_enabled',
            field=models.BooleanField(default=False, help_text='If on, this actor can log into /market-portal/ separately from loan staff.'),
        ),
        migrations.AddField(
            model_name='marketactor',
            name='portal_password',
            field=models.CharField(blank=True, help_text='Hashed portal password (Django make_password).', max_length=128),
        ),
        migrations.AddField(
            model_name='marketactor',
            name='portal_username',
            field=models.CharField(blank=True, help_text='Login for dealer portal (often phone). Blank = portal off.', max_length=64, null=True, unique=True),
        ),
        migrations.CreateModel(
            name='MarketPriceBand',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('asset_class', models.CharField(choices=[('building', 'Building / construction item'), ('land', 'Land (ETB/m²)'), ('vehicle', 'Vehicle'), ('machinery', 'Machinery'), ('other', 'Other')], db_index=True, default='building', max_length=20)),
                ('item_key', models.CharField(blank=True, db_index=True, help_text='Normalized item label key when no sub_work / sub_sub_work.', max_length=255)),
                ('unit', models.CharField(blank=True, max_length=40)),
                ('sample_count', models.PositiveIntegerField(default=0)),
                ('median_price', models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True)),
                ('p25_price', models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True)),
                ('p75_price', models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True)),
                ('min_price', models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True)),
                ('max_price', models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True)),
                ('last_observed_at', models.DateField(blank=True, null=True)),
                ('window_days', models.PositiveIntegerField(default=90)),
                ('computed_at', models.DateTimeField(auto_now=True)),
                ('city', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='market_price_bands', to='loans.city')),
                ('sub_sub_work', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='market_price_bands', to='collateral.subsubwork')),
                ('sub_work', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='market_price_bands', to='collateral.subwork')),
            ],
            options={'ordering': ['city_id', 'asset_class', 'item_key']},
        ),
        migrations.AddIndex(
            model_name='marketpriceband',
            index=models.Index(fields=['city', 'sub_work', 'sub_sub_work'], name='partners_ma_city_sw_idx'),
        ),
        migrations.AddIndex(
            model_name='marketpriceband',
            index=models.Index(fields=['city', 'item_key'], name='partners_ma_city_item_idx'),
        ),
        migrations.AddConstraint(
            model_name='marketpriceband',
            constraint=models.UniqueConstraint(fields=('city', 'asset_class', 'sub_work', 'sub_sub_work', 'item_key', 'unit'), name='partners_unique_market_price_band'),
        ),
    ]
