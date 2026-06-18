# Document workflow notification kinds (CharField values; choices metadata only)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0033_committee_notifications_return_gate'),
    ]

    operations = [
        migrations.AlterField(
            model_name='loannotification',
            name='kind',
            field=models.CharField(
                choices=[
                    ('vote_needed', 'Vote needed'),
                    ('level_advanced', 'Advanced to next level'),
                    ('committee_approved', 'Committee approved'),
                    ('committee_declined', 'Committee declined'),
                    ('returned_to_officer', 'Returned to loan officer'),
                    ('document_uploaded', 'Document uploaded'),
                    ('document_needs_review', 'Document needs review'),
                    ('document_verified', 'Document verified'),
                    ('document_rejected', 'Document rejected'),
                    ('document_requested', 'Document requested'),
                ],
                max_length=30,
            ),
        ),
    ]
