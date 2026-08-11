# Generated for online apply source channel on LoanRequest

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0061_loan_category_document_requirements'),
    ]

    operations = [
        migrations.AddField(
            model_name='loanrequest',
            name='source_channel',
            field=models.CharField(
                choices=[
                    ('staff', 'Staff / branch entry'),
                    ('online', 'Applicant digital apply'),
                ],
                db_index=True,
                default='staff',
                help_text='How the application entered the system (staff desk vs applicant portal).',
                max_length=20,
            ),
        ),
    ]
