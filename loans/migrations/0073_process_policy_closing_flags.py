from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0072_process_policy_config'),
    ]

    operations = [
        migrations.AddField(
            model_name='loanprocesspolicyconfig',
            name='require_collateral_restriction',
            field=models.BooleanField(
                default=False,
                help_text='Bank-wide: government Collateral Restriction must be verified before disbursement.',
            ),
        ),
        migrations.AddField(
            model_name='loanprocesspolicyconfig',
            name='require_agreement_signatures',
            field=models.BooleanField(
                default=False,
                help_text='Bank-wide: digital loan agreement signatures required before disbursement.',
            ),
        ),
        migrations.AddField(
            model_name='loanprocesspolicyconfig',
            name='require_title_search',
            field=models.BooleanField(
                default=False,
                help_text='Bank-wide: title / ownership search required before disbursement.',
            ),
        ),
        migrations.AddField(
            model_name='loanprocesspolicyconfig',
            name='require_mortgage_registration',
            field=models.BooleanField(
                default=False,
                help_text='Bank-wide: mortgage / restriction registration proof required before disbursement.',
            ),
        ),
        migrations.AddField(
            model_name='loanprocesspolicyconfig',
            name='require_notary_stamp',
            field=models.BooleanField(
                default=False,
                help_text='Bank-wide: notary / stamp-duty receipt required before disbursement.',
            ),
        ),
        migrations.AddField(
            model_name='loanprocesspolicyconfig',
            name='require_own_contribution',
            field=models.BooleanField(
                default=False,
                help_text='Bank-wide: borrower own-contribution / equity required before first disbursement.',
            ),
        ),
        migrations.AddField(
            model_name='loanprocesspolicyconfig',
            name='enable_disbursement_tranches',
            field=models.BooleanField(
                default=True,
                help_text='Allow staged (tranche) disbursement on post-approval.',
            ),
        ),
    ]
