import uuid
from decimal import Decimal

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('loans', '0062_loanrequest_source_channel'),
    ]

    operations = [
        migrations.CreateModel(
            name='ApplicantAccount',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('public_id', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('full_name', models.CharField(max_length=255)),
                ('phone_number', models.CharField(db_index=True, max_length=30, unique=True)),
                ('email', models.EmailField(blank=True, max_length=254)),
                ('password_hash', models.CharField(max_length=128)),
                ('is_active', models.BooleanField(db_index=True, default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('last_login_at', models.DateTimeField(blank=True, null=True)),
                ('preferred_branch', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='applicant_accounts', to='loans.branch',
                )),
            ],
            options={
                'verbose_name': 'Applicant portal account',
                'verbose_name_plural': 'Applicant portal accounts',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='OnlineApplication',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('public_id', models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, unique=True)),
                ('status', models.CharField(
                    choices=[
                        ('draft', 'Application details'),
                        ('documents', 'Documents'),
                        ('payment', 'Processing fee'),
                        ('submitted', 'Submitted'),
                        ('cancelled', 'Cancelled'),
                    ],
                    db_index=True, default='draft', max_length=20,
                )),
                ('applicant_name', models.CharField(blank=True, max_length=255)),
                ('phone_number', models.CharField(blank=True, max_length=30)),
                ('email', models.EmailField(blank=True, max_length=254)),
                ('customer_number', models.CharField(blank=True, max_length=50)),
                ('customer_history', models.CharField(
                    blank=True, choices=[('new', 'New customer'), ('existing', 'Existing customer')],
                    default='new', max_length=50,
                )),
                ('amount_requested', models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True)),
                ('reason', models.TextField(blank=True)),
                ('processing_fee_amount', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=12)),
                ('payment_status', models.CharField(
                    choices=[('unpaid', 'Unpaid'), ('paid', 'Paid'), ('waived', 'Waived')],
                    db_index=True, default='unpaid', max_length=20,
                )),
                ('payment_reference', models.CharField(blank=True, max_length=64)),
                ('payment_paid_at', models.DateTimeField(blank=True, null=True)),
                ('payment_method', models.CharField(blank=True, max_length=40)),
                ('queue_id', models.CharField(blank=True, db_index=True, help_text='Loan request id issued on submit (e.g. HK-000000001).', max_length=22)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('submitted_at', models.DateTimeField(blank=True, null=True)),
                ('applicant', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='applications', to='applicant_portal.applicantaccount',
                )),
                ('branch', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                    related_name='online_applications', to='loans.branch',
                )),
                ('category', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                    related_name='online_applications', to='loans.loancategory',
                )),
                ('collateral', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                    related_name='online_applications', to='loans.collateraltype',
                )),
                ('loan_request', models.OneToOneField(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='online_application', to='loans.loanrequest',
                )),
            ],
            options={
                'ordering': ['-updated_at'],
            },
        ),
        migrations.CreateModel(
            name='OnlineApplicationDocument',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('file', models.FileField(upload_to='online_apply_docs/%Y/%m/')),
                ('original_filename', models.CharField(blank=True, max_length=255)),
                ('file_size', models.PositiveIntegerField(blank=True, null=True)),
                ('uploaded_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('application', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='documents', to='applicant_portal.onlineapplication',
                )),
                ('document_type', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='online_documents', to='loans.loanapplicationdocumenttype',
                )),
            ],
            options={
                'ordering': ['document_type__order', 'document_type__name', '-uploaded_at'],
            },
        ),
        migrations.AddIndex(
            model_name='onlineapplication',
            index=models.Index(fields=['applicant', 'status'], name='applicant_p_applica_b0c7d3_idx'),
        ),
        migrations.AddConstraint(
            model_name='onlineapplicationdocument',
            constraint=models.UniqueConstraint(
                fields=('application', 'document_type'),
                name='applicant_portal_unique_app_doc_type',
            ),
        ),
    ]
