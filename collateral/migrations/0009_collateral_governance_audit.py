# Governance: audit trail, GPS attestation, weak GPS fields

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('loans', '0040_identity_match_fields'),
        ('collateral', '0008_land_other_field_visit'),
    ]

    operations = [
        migrations.AddField(
            model_name='building',
            name='site_gps_attestation_note',
            field=models.TextField(blank=True, help_text='Officer explanation when GPS accuracy exceeds policy threshold.'),
        ),
        migrations.AddField(
            model_name='building',
            name='site_gps_weak_acknowledged',
            field=models.BooleanField(default=False, help_text='Officer attested location when GPS was weak or unavailable.'),
        ),
        migrations.AddField(
            model_name='buildingimage',
            name='gps_attestation_note',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='buildingimage',
            name='gps_weak_acknowledged',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='landvaluation',
            name='site_gps_attestation_note',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='landvaluation',
            name='site_gps_weak_acknowledged',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='landvaluationimage',
            name='gps_attestation_note',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='landvaluationimage',
            name='gps_weak_acknowledged',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='othercollateralitem',
            name='site_gps_attestation_note',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='othercollateralitem',
            name='site_gps_weak_acknowledged',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='othercollateralitemimage',
            name='gps_attestation_note',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='othercollateralitemimage',
            name='gps_weak_acknowledged',
            field=models.BooleanField(default=False),
        ),
        migrations.CreateModel(
            name='CollateralFieldAuditLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_type', models.CharField(choices=[('site_gps_marked', 'Site GPS marked'), ('photo_uploaded', 'Photo uploaded'), ('photo_deleted', 'Photo deleted'), ('boq_saved', 'BOQ quantities saved'), ('valuation_edited', 'Valuation row edited'), ('valuation_deleted', 'Valuation row deleted'), ('collateral_submitted', 'Collateral submitted'), ('weak_gps_attested', 'Weak GPS attested')], max_length=40)),
                ('subject_type', models.CharField(blank=True, max_length=40)),
                ('subject_id', models.PositiveIntegerField(blank=True, null=True)),
                ('payload', models.JSONField(blank=True, default=dict)),
                ('performed_at', models.DateTimeField(auto_now_add=True)),
                ('loan_request', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='collateral_audit_logs', to='loans.loanrequest')),
                ('performed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='collateral_audit_events', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Collateral field audit log',
                'verbose_name_plural': 'Collateral field audit logs',
                'ordering': ['-performed_at'],
            },
        ),
    ]
