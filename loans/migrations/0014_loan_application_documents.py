# Loan application document types and loan request documents

from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0013_alter_collateralestimationconfig_mode'),
    ]

    operations = [
        migrations.CreateModel(
            name='LoanApplicationDocumentType',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
                ('order', models.PositiveIntegerField(default=0, help_text='Display order (lower first).')),
                ('is_required', models.BooleanField(default=True, help_text='If True, this document type is required for loan application.')),
            ],
            options={
                'verbose_name': 'Loan application document type',
                'verbose_name_plural': 'Loan application document types',
                'ordering': ['order', 'name'],
            },
        ),
        migrations.CreateModel(
            name='LoanRequestDocument',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('file', models.FileField(upload_to='loan_application_docs/%Y/%m/')),
                ('uploaded_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('document_type', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='documents', to='loans.loanapplicationdocumenttype')),
                ('loan_request', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='application_documents', to='loans.loanrequest')),
            ],
            options={
                'verbose_name': 'Loan request document',
                'verbose_name_plural': 'Loan request documents',
                'ordering': ['document_type__order', 'document_type__name', 'uploaded_at'],
            },
        ),
    ]
