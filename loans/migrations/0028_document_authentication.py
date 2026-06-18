# Document authentication: policy singleton + verification fields on uploads

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def seed_document_auth_policy(apps, schema_editor):
    Policy = apps.get_model('loans', 'DocumentAuthenticationPolicy')
    if not Policy.objects.exists():
        Policy.objects.create()


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('loans', '0027_sheet_completeness_policy'),
    ]

    operations = [
        migrations.CreateModel(
            name='DocumentAuthenticationPolicy',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                (
                    'allowed_extensions',
                    models.CharField(
                        default='pdf,jpg,jpeg,png,doc,docx',
                        help_text='Comma-separated allowed file extensions (no dots).',
                        max_length=255,
                    ),
                ),
                (
                    'max_file_size_mb',
                    models.PositiveIntegerField(
                        default=15,
                        help_text='Maximum upload size per file in megabytes.',
                    ),
                ),
                (
                    'require_verified_documents_for_collateral',
                    models.BooleanField(
                        default=True,
                        help_text='Require each required document type to be verified or auto-passed before collateral.',
                    ),
                ),
            ],
            options={
                'verbose_name': 'Document authentication policy',
                'verbose_name_plural': 'Document authentication policy',
            },
        ),
        migrations.RunPython(seed_document_auth_policy, migrations.RunPython.noop),
        migrations.AddField(
            model_name='loanrequestdocument',
            name='auth_notes',
            field=models.TextField(blank=True, help_text='Officer notes on authenticity review.'),
        ),
        migrations.AddField(
            model_name='loanrequestdocument',
            name='auth_status',
            field=models.CharField(
                choices=[
                    ('pending', 'Pending checks'),
                    ('auto_passed', 'Auto-passed (integrity OK)'),
                    ('needs_review', 'Needs manual review'),
                    ('verified', 'Verified authentic'),
                    ('rejected', 'Rejected / not authentic'),
                ],
                default='pending',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='loanrequestdocument',
            name='auth_verdict',
            field=models.CharField(
                blank=True,
                choices=[
                    ('authentic', 'Authentic'),
                    ('suspicious', 'Suspicious'),
                    ('not_authentic', 'Not authentic'),
                    ('inconclusive', 'Inconclusive'),
                ],
                max_length=20,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='loanrequestdocument',
            name='automated_checks',
            field=models.JSONField(blank=True, default=dict, help_text='Automated integrity check results (JSON).'),
        ),
        migrations.AddField(
            model_name='loanrequestdocument',
            name='authenticated_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='loanrequestdocument',
            name='authenticated_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='loan_documents_authenticated',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='loanrequestdocument',
            name='file_sha256',
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text='SHA-256 fingerprint for integrity and duplicate detection.',
                max_length=64,
            ),
        ),
        migrations.AddField(
            model_name='loanrequestdocument',
            name='file_size',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='loanrequestdocument',
            name='original_filename',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name='loanrequestdocument',
            name='uploaded_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='loan_documents_uploaded',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
