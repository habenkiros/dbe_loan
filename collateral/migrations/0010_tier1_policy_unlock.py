# Tier 1: policy config, unlock workflow, audit event types

from decimal import Decimal

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('loans', '0040_identity_match_fields'),
        ('collateral', '0009_collateral_governance_audit'),
    ]

    operations = [
        migrations.CreateModel(
            name='CollateralPolicyConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('min_images_per_building', models.PositiveSmallIntegerField(default=5)),
                ('min_images_per_land', models.PositiveSmallIntegerField(default=3)),
                ('min_images_per_other_item', models.PositiveSmallIntegerField(default=3)),
                ('gps_accuracy_weak_threshold_m', models.PositiveIntegerField(default=100, help_text='Above this GPS accuracy (metres), officer attestation is required.')),
                ('photo_max_distance_from_site_m', models.PositiveIntegerField(default=200, help_text='Flag photos farther than this from registered site GPS.')),
                ('block_submit_on_far_photos', models.BooleanField(default=False, help_text='If enabled, photos beyond max distance block collateral submit.')),
                ('block_submit_on_missing_photo_gps', models.BooleanField(default=False, help_text='If enabled, photos without GPS block collateral submit.')),
                ('min_coverage_ratio', models.DecimalField(decimal_places=4, default=Decimal('1.0'), help_text='Minimum collateral value ÷ loan amount (1.0 = 100%). Blocks submit if below.', max_digits=6)),
                ('flag_coverage_below_ratio', models.DecimalField(decimal_places=4, default=Decimal('1.0'), help_text='Advisory warning when coverage is below this ratio.', max_digits=6)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Collateral policy config',
                'verbose_name_plural': 'Collateral policy config',
            },
        ),
        migrations.CreateModel(
            name='CollateralUnlockRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('requested_at', models.DateTimeField(auto_now_add=True)),
                ('reason', models.TextField(help_text='Why collateral must be corrected.')),
                ('status', models.CharField(choices=[('pending', 'Pending review'), ('approved', 'Approved'), ('rejected', 'Rejected')], default='pending', max_length=20)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('review_note', models.TextField(blank=True)),
                ('previous_submitted_at', models.DateTimeField(blank=True, null=True)),
                ('loan_request', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='collateral_unlock_requests', to='loans.loanrequest')),
                ('previous_submitted_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('requested_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='collateral_unlock_requests', to=settings.AUTH_USER_MODEL)),
                ('reviewed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='collateral_unlock_reviews', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-requested_at'],
            },
        ),
        migrations.RunPython(
            lambda apps, schema_editor: apps.get_model('collateral', 'CollateralPolicyConfig').objects.get_or_create(
                defaults={'min_coverage_ratio': Decimal('1.0'), 'flag_coverage_below_ratio': Decimal('1.0')},
            ),
            migrations.RunPython.noop,
        ),
    ]
