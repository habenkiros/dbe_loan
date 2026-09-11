from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0095_project_comfar_feasibility'),
    ]

    operations = [
        migrations.AddField(
            model_name='documentauthenticationpolicy',
            name='require_verified_documents_for_committee',
            field=models.BooleanField(
                default=True,
                help_text=(
                    'Required document types must be uploaded and authenticated before committee '
                    'submission (all product families with a checklist).'
                ),
            ),
        ),
    ]
