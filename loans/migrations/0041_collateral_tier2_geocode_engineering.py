# Tier 2: declared address geocode cache + engineering QA on collateral submit

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('loans', '0040_identity_match_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='loanrequest',
            name='collateral_engineering_status',
            field=models.CharField(
                blank=True,
                choices=[
                    ('', 'Not applicable'),
                    ('pending_review', 'Pending engineering review'),
                    ('approved', 'Engineering approved'),
                    ('returned', 'Returned for correction'),
                ],
                default='',
                help_text='Engineering QA after collateral submit (when engineering team mode is enabled).',
                max_length=30,
            ),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='collateral_engineering_reviewed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='collateral_engineering_reviewed_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='collateral_engineering_reviews',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='collateral_engineering_return_note',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='declared_address_text',
            field=models.TextField(blank=True, help_text='Cached address text used for geocoding.'),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='declared_address_lat',
            field=models.DecimalField(blank=True, decimal_places=8, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='declared_address_lon',
            field=models.DecimalField(blank=True, decimal_places=8, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='declared_address_geocoded_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='declared_address_source',
            field=models.CharField(
                blank=True,
                help_text='business or home — which Sheet 1 address was geocoded.',
                max_length=20,
            ),
        ),
    ]
