# Generated manually for lockout + MFA + security audit

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0058_agent_conversation_story'),
    ]

    operations = [
        migrations.AddField(
            model_name='customuser',
            name='failed_login_attempts',
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='customuser',
            name='lockout_until',
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='customuser',
            name='mfa_enabled',
            field=models.BooleanField(
                default=False,
                help_text='When True, staff must enter a TOTP code after password login.',
            ),
        ),
        migrations.AddField(
            model_name='customuser',
            name='mfa_secret_encrypted',
            field=models.TextField(
                blank=True,
                default='',
                help_text='Encrypted TOTP shared secret (not plaintext).',
            ),
        ),
        migrations.CreateModel(
            name='IpLoginThrottle',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('ip_address', models.GenericIPAddressField(unique=True)),
                ('failed_attempts', models.PositiveSmallIntegerField(default=0)),
                ('lockout_until', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name='SecurityAuditLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_type', models.CharField(
                    choices=[
                        ('login_success', 'Login success'),
                        ('login_failed', 'Login failed'),
                        ('login_locked', 'Account locked'),
                        ('logout', 'Logout'),
                        ('mfa_challenge', 'MFA challenge issued'),
                        ('mfa_success', 'MFA success'),
                        ('mfa_failed', 'MFA failed'),
                        ('mfa_enrolled', 'MFA enrolled'),
                        ('mfa_disabled', 'MFA disabled'),
                        ('user_created', 'User created'),
                        ('user_updated', 'User updated'),
                        ('user_unlocked', 'User unlocked'),
                    ],
                    db_index=True,
                    max_length=32,
                )),
                ('username', models.CharField(blank=True, db_index=True, default='', max_length=150)),
                ('ip_address', models.GenericIPAddressField(blank=True, null=True)),
                ('user_agent', models.CharField(blank=True, default='', max_length=512)),
                ('detail', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('user', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='security_events',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='securityauditlog',
            index=models.Index(fields=['event_type', '-created_at'], name='loans_secur_event_t_idx'),
        ),
    ]
