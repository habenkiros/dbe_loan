# Generated manually — external-only market portal flexibility

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('partners', '0003_portal_and_bands'),
    ]

    operations = [
        migrations.AlterField(
            model_name='marketactor',
            name='branch',
            field=models.ForeignKey(
                blank=True,
                help_text='Optional branch tag; portal self-register may leave blank.',
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='market_actors',
                to='loans.branch',
            ),
        ),
        migrations.AlterField(
            model_name='marketobservation',
            name='branch',
            field=models.ForeignKey(
                blank=True,
                help_text='Optional; mirrors actor.branch when set.',
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='market_observations',
                to='loans.branch',
            ),
        ),
    ]
