# Generated initial migration for collateral app

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('loans', '0006_region_district_city_queue_approved'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='MainWork',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
                ('order', models.PositiveIntegerField(default=0, help_text='Display order')),
            ],
            options={
                'ordering': ['order', 'name'],
            },
        ),
        migrations.CreateModel(
            name='SubWork',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
                ('order', models.PositiveIntegerField(default=0)),
                ('main_work', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='collateral.mainwork')),
            ],
            options={
                'ordering': ['main_work', 'order', 'name'],
                'unique_together': {('main_work', 'name')},
            },
        ),
        migrations.CreateModel(
            name='SubSubWork',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
                ('unit_measure', models.CharField(blank=True, help_text='e.g. m², m³', max_length=50)),
                ('order', models.PositiveIntegerField(default=0)),
                ('sub_work', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='collateral.subwork')),
            ],
            options={
                'ordering': ['sub_work', 'order', 'name'],
                'unique_together': {('sub_work', 'name')},
            },
        ),
        migrations.CreateModel(
            name='SubWorkUnitPrice',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('unit_price', models.DecimalField(decimal_places=2, max_digits=20)),
                ('effective_from', models.DateField(blank=True, null=True)),
                ('effective_to', models.DateField(blank=True, null=True)),
                ('city', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='loans.city')),
                ('sub_work', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='collateral.subwork')),
            ],
            options={
                'verbose_name_plural': 'SubWork unit prices',
                'unique_together': {('sub_work', 'city')},
            },
        ),
        migrations.CreateModel(
            name='Building',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(help_text='Building label/name', max_length=255)),
                ('construction_type', models.CharField(blank=True, max_length=100)),
                ('floors', models.PositiveIntegerField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('city', models.ForeignKey(blank=True, help_text='City/Woreda for unit price', null=True, on_delete=django.db.models.deletion.SET_NULL, to='loans.city')),
                ('loan_request', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='loans.loanrequest')),
            ],
            options={
                'ordering': ['loan_request', 'name'],
            },
        ),
        migrations.CreateModel(
            name='BuildingValuation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('quantity', models.DecimalField(decimal_places=4, default=0, max_digits=20)),
                ('unit_price', models.DecimalField(decimal_places=2, default=0, max_digits=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('building', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='collateral.building')),
                ('quantity_entered_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='collateral_quantity_entries', to=settings.AUTH_USER_MODEL)),
                ('sub_sub_work', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='collateral.subsubwork')),
                ('unit_price_entered_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='collateral_unit_price_entries', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'unique_together': {('building', 'sub_sub_work')},
            },
        ),
        migrations.CreateModel(
            name='BuildingImage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('image', models.ImageField(upload_to='collateral/building/%Y/%m/')),
                ('caption', models.CharField(blank=True, max_length=255)),
                ('captured_at', models.DateTimeField(blank=True, null=True)),
                ('gps_lat', models.DecimalField(blank=True, decimal_places=8, max_digits=12, null=True)),
                ('gps_lon', models.DecimalField(blank=True, decimal_places=8, max_digits=12, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('building', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='collateral.building')),
                ('uploaded_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='LandValuation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('land_size_sqm', models.DecimalField(blank=True, decimal_places=4, max_digits=20, null=True)),
                ('unit_price_per_sqm', models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('loan_request', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='land_valuation', to='loans.loanrequest')),
            ],
        ),
    ]
