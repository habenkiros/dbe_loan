# Land + other collateral field visit (GPS, photos)

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('collateral', '0007_field_visit_gps'),
    ]

    operations = [
        migrations.AddField(
            model_name='landvaluation',
            name='site_captured_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='landvaluation',
            name='site_gps_accuracy_m',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name='landvaluation',
            name='site_gps_lat',
            field=models.DecimalField(blank=True, decimal_places=8, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name='landvaluation',
            name='site_gps_lon',
            field=models.DecimalField(blank=True, decimal_places=8, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name='othercollateralitem',
            name='site_captured_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='othercollateralitem',
            name='site_gps_accuracy_m',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name='othercollateralitem',
            name='site_gps_lat',
            field=models.DecimalField(blank=True, decimal_places=8, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name='othercollateralitem',
            name='site_gps_lon',
            field=models.DecimalField(blank=True, decimal_places=8, max_digits=12, null=True),
        ),
        migrations.CreateModel(
            name='LandValuationImage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('image', models.ImageField(upload_to='collateral/land/%Y/%m/')),
                ('caption', models.CharField(blank=True, max_length=255)),
                ('photo_type', models.CharField(blank=True, choices=[('plot', 'Plot / overview'), ('boundary', 'Boundary / corners'), ('title_deed', 'Title / certificate'), ('other', 'Other')], default='other', max_length=20)),
                ('captured_at', models.DateTimeField(blank=True, null=True)),
                ('gps_lat', models.DecimalField(blank=True, decimal_places=8, max_digits=12, null=True)),
                ('gps_lon', models.DecimalField(blank=True, decimal_places=8, max_digits=12, null=True)),
                ('gps_accuracy_m', models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('land_valuation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='images', to='collateral.landvaluation')),
                ('uploaded_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='OtherCollateralItemImage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('image', models.ImageField(upload_to='collateral/other/%Y/%m/')),
                ('caption', models.CharField(blank=True, max_length=255)),
                ('photo_type', models.CharField(blank=True, choices=[('plate', 'Plate / registration'), ('asset', 'Full asset'), ('serial_label', 'Serial / chassis label'), ('other', 'Other')], default='other', max_length=20)),
                ('captured_at', models.DateTimeField(blank=True, null=True)),
                ('gps_lat', models.DecimalField(blank=True, decimal_places=8, max_digits=12, null=True)),
                ('gps_lon', models.DecimalField(blank=True, decimal_places=8, max_digits=12, null=True)),
                ('gps_accuracy_m', models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('item', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='images', to='collateral.othercollateralitem')),
                ('uploaded_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
