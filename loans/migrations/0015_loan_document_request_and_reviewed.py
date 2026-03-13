# Loan document requests (officer/engineer) and documents_reviewed on LoanRequest

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0014_loan_application_documents'),
    ]

    operations = [
        migrations.AddField(
            model_name='loanrequest',
            name='documents_reviewed_at',
            field=models.DateTimeField(blank=True, help_text='When the assigned loan officer or engineer marked documents reviewed and proceeded to collateral.', null=True),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='documents_reviewed_by',
            field=models.ForeignKey(blank=True, help_text='Loan officer or engineer who reviewed documents and proceeded to collateral estimation.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='loan_requests_documents_reviewed', to=settings.AUTH_USER_MODEL),
        ),
        migrations.CreateModel(
            name='LoanDocumentRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('requested_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('document_type', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='loan_requests_requested', to='loans.loanapplicationdocumenttype')),
                ('loan_request', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='document_requests', to='loans.loanrequest')),
                ('requested_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='document_requests_made', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Loan document request',
                'verbose_name_plural': 'Loan document requests',
                'ordering': ['-requested_at'],
                'unique_together': {('loan_request', 'document_type')},
            },
        ),
    ]
