# Generated for loan category document packs

from django.db import migrations, models
import django.db.models.deletion


def seed_category_document_packs(apps, schema_editor):
    LoanCategory = apps.get_model('loans', 'LoanCategory')
    LoanApplicationDocumentType = apps.get_model('loans', 'LoanApplicationDocumentType')
    Req = apps.get_model('loans', 'LoanCategoryDocumentRequirement')

    types = list(LoanApplicationDocumentType.objects.order_by('order', 'id'))
    if not types:
        return
    for cat in LoanCategory.objects.all():
        mode = (getattr(cat, 'appraisal_mode', None) or '').strip()
        for dt in types:
            dt_mode = (getattr(dt, 'for_appraisal_mode', None) or '').strip()
            if dt_mode and mode and dt_mode != mode:
                continue
            Req.objects.get_or_create(
                category=cat,
                document_type=dt,
                defaults={
                    'is_required': bool(dt.is_required),
                    'order': int(dt.order or 0),
                },
            )


def unseed_category_document_packs(apps, schema_editor):
    apps.get_model('loans', 'LoanCategoryDocumentRequirement').objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0060_security_audit_event_types'),
    ]

    operations = [
        migrations.CreateModel(
            name='LoanCategoryDocumentRequirement',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('is_required', models.BooleanField(
                    default=True,
                    help_text='If True, this document is required before collateral for this loan type.',
                )),
                ('order', models.PositiveIntegerField(
                    default=0,
                    help_text='Display order within this loan type (lower first).',
                )),
                ('category', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='document_requirements',
                    to='loans.loancategory',
                )),
                ('document_type', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='category_requirements',
                    to='loans.loanapplicationdocumenttype',
                )),
            ],
            options={
                'verbose_name': 'Loan type document requirement',
                'verbose_name_plural': 'Loan type document requirements',
                'ordering': ['order', 'document_type__order', 'document_type__name'],
            },
        ),
        migrations.AddConstraint(
            model_name='loancategorydocumentrequirement',
            constraint=models.UniqueConstraint(
                fields=('category', 'document_type'),
                name='loans_unique_category_document_type',
            ),
        ),
        migrations.RunPython(seed_category_document_packs, unseed_category_document_packs),
    ]
