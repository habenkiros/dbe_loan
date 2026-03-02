# Allow unit prices and valuation at SubWork level (when no SubSubWork)

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('collateral', '0004_alter_subworkunitprice_options'),
    ]

    operations = [
        # SubWorkUnitPrice: add sub_work, make sub_sub_work nullable, new unique_together
        migrations.AddField(
            model_name='subworkunitprice',
            name='sub_work',
            field=models.ForeignKey(
                blank=True,
                help_text='Set when there is no sub-sub work; leave blank if sub_sub_work is set.',
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to='collateral.subwork',
            ),
        ),
        migrations.AlterUniqueTogether(
            name='subworkunitprice',
            unique_together=set(),
        ),
        migrations.AlterField(
            model_name='subworkunitprice',
            name='sub_sub_work',
            field=models.ForeignKey(
                blank=True,
                help_text='Set for sub-sub work level; leave blank to use sub_work only.',
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to='collateral.subsubwork',
            ),
        ),
        migrations.AlterUniqueTogether(
            name='subworkunitprice',
            unique_together={('city', 'sub_work', 'sub_sub_work')},
        ),
        # BuildingValuation: add sub_work, make sub_sub_work nullable, new unique_together
        migrations.AddField(
            model_name='buildingvaluation',
            name='sub_work',
            field=models.ForeignKey(
                blank=True,
                help_text='Set when there is no sub-sub work; leave blank if sub_sub_work is set.',
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to='collateral.subwork',
            ),
        ),
        migrations.AlterUniqueTogether(
            name='buildingvaluation',
            unique_together=set(),
        ),
        migrations.AlterField(
            model_name='buildingvaluation',
            name='sub_sub_work',
            field=models.ForeignKey(
                blank=True,
                help_text='Set for sub-sub work level; leave blank to use sub_work only.',
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to='collateral.subsubwork',
            ),
        ),
        migrations.AlterUniqueTogether(
            name='buildingvaluation',
            unique_together={('building', 'sub_work', 'sub_sub_work')},
        ),
    ]
