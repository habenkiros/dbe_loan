# Generated migration for OtherCollateralItem

from decimal import Decimal
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('collateral', '0001_initial'),
        ('loans', '0006_region_district_city_queue_approved'),  # LoanRequest
    ]

    operations = [
        migrations.CreateModel(
            name='OtherCollateralItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(help_text='e.g. Toyota Pickup, Tractor, Machinery', max_length=255)),
                ('estimated_value', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=20)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('loan_request', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='other_collateral_items', to='loans.loanrequest')),
            ],
            options={
                'ordering': ['loan_request', 'name'],
            },
        ),
    ]
