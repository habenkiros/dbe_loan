# Generated for portal settings, lockout, and auth audit

from decimal import Decimal

from django.db import migrations, models
import django.db.models.deletion


def seed_portal_settings(apps, schema_editor):
    Settings = apps.get_model('applicant_portal', 'ApplicantPortalSettings')
    if not Settings.objects.exists():
        Settings.objects.create(
            pk=1,
            enabled=True,
            processing_fee_etb=Decimal('50.00'),
            min_password_length=10,
            require_uppercase=True,
            require_lowercase=True,
            require_digit=True,
            require_special=True,
            max_failed_logins=5,
            lockout_minutes=15,
            register_rate_limit_per_hour=8,
            session_idle_minutes=30,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('applicant_portal', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='ApplicantPortalSettings',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('enabled', models.BooleanField(default=True, help_text='If off, the public apply site shows a closed message.')),
                ('processing_fee_etb', models.DecimalField(decimal_places=2, default=Decimal('50.00'), help_text='Application processing fee in ETB (demo pay amount).', max_digits=12)),
                ('min_password_length', models.PositiveSmallIntegerField(default=10, help_text='Minimum password length for applicants.')),
                ('require_uppercase', models.BooleanField(default=True)),
                ('require_lowercase', models.BooleanField(default=True)),
                ('require_digit', models.BooleanField(default=True)),
                ('require_special', models.BooleanField(default=True, help_text='Require a non-letter, non-digit character.')),
                ('max_failed_logins', models.PositiveSmallIntegerField(default=5, help_text='Failed login attempts before temporary lockout.')),
                ('lockout_minutes', models.PositiveSmallIntegerField(default=15, help_text='Account/IP lockout duration in minutes.')),
                ('register_rate_limit_per_hour', models.PositiveSmallIntegerField(default=8, help_text='Max registration attempts per IP address per hour.')),
                ('session_idle_minutes', models.PositiveSmallIntegerField(default=30, help_text='Sign applicants out after this many minutes of inactivity.')),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Applicant portal settings',
                'verbose_name_plural': 'Applicant portal settings',
            },
        ),
        migrations.CreateModel(
            name='ApplicantIpThrottle',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('ip_address', models.GenericIPAddressField(unique=True)),
                ('failed_login_attempts', models.PositiveSmallIntegerField(default=0)),
                ('lockout_until', models.DateTimeField(blank=True, null=True)),
                ('register_count', models.PositiveSmallIntegerField(default=0)),
                ('register_window_start', models.DateTimeField(blank=True, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Applicant IP throttle',
                'verbose_name_plural': 'Applicant IP throttles',
            },
        ),
        migrations.CreateModel(
            name='ApplicantAuthEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_type', models.CharField(choices=[('register', 'Registered'), ('login_success', 'Login success'), ('login_failed', 'Login failed'), ('login_locked', 'Login locked'), ('logout', 'Logout'), ('password_changed', 'Password changed'), ('session_timeout', 'Session idle timeout')], db_index=True, max_length=32)),
                ('phone_number', models.CharField(blank=True, db_index=True, max_length=30)),
                ('ip_address', models.GenericIPAddressField(blank=True, null=True)),
                ('user_agent', models.CharField(blank=True, default='', max_length=512)),
                ('detail', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('account', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='auth_events', to='applicant_portal.applicantaccount')),
            ],
            options={
                'verbose_name': 'Applicant auth event',
                'verbose_name_plural': 'Applicant auth events',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddField(
            model_name='applicantaccount',
            name='failed_login_attempts',
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='applicantaccount',
            name='last_login_ip',
            field=models.GenericIPAddressField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='applicantaccount',
            name='locked_until',
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='applicantaccount',
            name='password_changed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(seed_portal_settings, migrations.RunPython.noop),
    ]
