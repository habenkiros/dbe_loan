# Generated manually — document new security audit event types

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0059_security_mfa_lockout_audit'),
    ]

    operations = [
        migrations.AlterField(
            model_name='securityauditlog',
            name='event_type',
            field=models.CharField(
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
                    ('password_reset_requested', 'Password reset requested'),
                    ('password_reset_completed', 'Password reset completed'),
                    ('password_changed', 'Password changed'),
                    ('audit_exported', 'Security audit exported'),
                    ('session_timeout', 'Session idle timeout'),
                ],
                db_index=True,
                max_length=32,
            ),
        ),
    ]
