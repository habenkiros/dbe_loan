from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('applicant_portal', '0006_dbe_actor_kinds'),
    ]

    operations = [
        migrations.AddField(
            model_name='onlineapplicationdocument',
            name='file_sha256',
            field=models.CharField(blank=True, db_index=True, max_length=64),
        ),
        migrations.AddField(
            model_name='onlineapplicationdocument',
            name='auth_status',
            field=models.CharField(default='pending', max_length=20),
        ),
        migrations.AddField(
            model_name='onlineapplicationdocument',
            name='automated_checks',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='onlineapplicationdocument',
            name='quality_score',
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='onlineapplicationdocument',
            name='authenticity_score',
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
    ]
