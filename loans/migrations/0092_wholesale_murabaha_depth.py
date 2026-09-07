from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0091_kyc_checklist_and_document_modes'),
    ]

    operations = [
        migrations.AddField(
            model_name='pfiinstitutionprofile',
            name='audited_year',
            field=models.PositiveSmallIntegerField(
                blank=True,
                help_text='Latest audited financial year on the PFI file.',
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='pfiinstitutionprofile',
            name='credit_policy_on_file',
            field=models.BooleanField(
                default=False,
                help_text='PFI credit policy is on this pack.',
            ),
        ),
        migrations.AddField(
            model_name='pfiinstitutionprofile',
            name='on_lending_policy_on_file',
            field=models.BooleanField(
                default=False,
                help_text='On-lending / sub-borrower policy is on this pack.',
            ),
        ),
        migrations.AddField(
            model_name='murabahacontract',
            name='supplier_offer_ref',
            field=models.CharField(
                blank=True,
                help_text='Supplier offer / invoice reference.',
                max_length=80,
            ),
        ),
        migrations.AddField(
            model_name='murabahacontract',
            name='delivery_status',
            field=models.CharField(
                choices=[
                    ('ordered', 'Ordered — goods not yet received'),
                    ('received', 'Received by the bank / customer'),
                    ('sold', 'Sold — cost-plus complete'),
                ],
                default='ordered',
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name='loanrequestdocument',
            name='quality_score',
            field=models.PositiveSmallIntegerField(
                blank=True,
                help_text='Scan quality 0–100 (resolution, blur, OCR readability).',
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='loanrequestdocument',
            name='authenticity_score',
            field=models.PositiveSmallIntegerField(
                blank=True,
                help_text='Composite authenticity 0–100 (quality, identity, reuse, layout).',
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='loanrequestdocument',
            name='perceptual_hash',
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text='Average-hash of the first page/image for near-duplicate warnings.',
                max_length=64,
            ),
        ),
    ]
