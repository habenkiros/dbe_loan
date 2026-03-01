# Unit price per SubSubWork; order 1.1 / 1.1.1 for SubWork / SubSubWork

from decimal import Decimal
import django.db.models.deletion
from django.db import migrations, models


def set_sub_sub_work_from_sub_work(apps, schema_editor):
    """For existing SubWorkUnitPrice rows, set sub_sub_work to first SubSubWork of that sub_work."""
    SubWorkUnitPrice = apps.get_model('collateral', 'SubWorkUnitPrice')
    SubSubWork = apps.get_model('collateral', 'SubSubWork')
    for price in SubWorkUnitPrice.objects.filter(sub_sub_work__isnull=True):
        first = SubSubWork.objects.filter(sub_work_id=price.sub_work_id).order_by('order', 'name').first()
        if first:
            price.sub_sub_work_id = first.id
            price.save()


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('collateral', '0002_add_other_collateral_item'),
    ]

    operations = [
        migrations.AlterField(
            model_name='subwork',
            name='order',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('0'),
                help_text='Order number e.g. 1.1, 1.2 (related to main work)',
                max_digits=6,
            ),
        ),
        migrations.AlterField(
            model_name='subsubwork',
            name='order',
            field=models.CharField(
                default='0',
                help_text='Order number e.g. 1.1.1, 1.1.2 (related to sub work)',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='subworkunitprice',
            name='sub_sub_work',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='+',
                to='collateral.subsubwork',
            ),
        ),
        migrations.RunPython(set_sub_sub_work_from_sub_work, noop),
        migrations.AlterUniqueTogether(
            name='subworkunitprice',
            unique_together=set(),
        ),
        migrations.RemoveField(
            model_name='subworkunitprice',
            name='sub_work',
        ),
        migrations.AlterField(
            model_name='subworkunitprice',
            name='sub_sub_work',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                to='collateral.subsubwork',
            ),
        ),
        migrations.AlterUniqueTogether(
            name='subworkunitprice',
            unique_together={('sub_sub_work', 'city')},
        ),
    ]
