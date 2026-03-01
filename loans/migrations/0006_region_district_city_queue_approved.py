# Generated migration: Region, Zone, City, District; Zone->District rename; queue_approved

from django.db import migrations, models
import django.db.models.deletion


def copy_zone_to_district(apps, schema_editor):
    """Create District from each Zone; set Branch, LoanRequest, CustomUser.district."""
    Zone = apps.get_model("loans", "Zone")
    District = apps.get_model("loans", "District")
    Branch = apps.get_model("loans", "Branch")
    LoanRequest = apps.get_model("loans", "LoanRequest")
    CustomUser = apps.get_model("loans", "CustomUser")

    for zone in Zone.objects.all():
        district, _ = District.objects.get_or_create(name=zone.name)
        Branch.objects.filter(zone_id=zone.id).update(district_id=district.id)
        LoanRequest.objects.filter(zone_id=zone.id).update(district_id=district.id)
        CustomUser.objects.filter(zone_id=zone.id).update(district_id=district.id)


def noop_reverse(apps, schema_editor):
    """Reverse not supported (would require Zone data from District)."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("loans", "0005_alter_customuser_role"),
    ]

    operations = [
        migrations.CreateModel(
            name="Region",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255)),
            ],
        ),
        migrations.CreateModel(
            name="District",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255)),
            ],
        ),
        migrations.AddField(
            model_name="branch",
            name="district",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to="loans.district"),
        ),
        migrations.AddField(
            model_name="loanrequest",
            name="district",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to="loans.district"),
        ),
        migrations.AddField(
            model_name="loanrequest",
            name="queue_approved",
            field=models.BooleanField(default=False, help_text="When True, loan is eligible for collateral valuation workflow."),
        ),
        migrations.AddField(
            model_name="customuser",
            name="district",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="loans.district"),
        ),
        migrations.RunPython(copy_zone_to_district, noop_reverse),
        migrations.RemoveField(model_name="branch", name="zone"),
        migrations.RemoveField(model_name="loanrequest", name="zone"),
        migrations.RemoveField(model_name="customuser", name="zone"),
        migrations.AlterField(
            model_name="branch",
            name="district",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="loans.district"),
        ),
        migrations.AlterField(
            model_name="loanrequest",
            name="district",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to="loans.district"),
        ),
        migrations.DeleteModel(name="Zone"),
        migrations.CreateModel(
            name="Zone",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255)),
                ("region", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="loans.region")),
            ],
            options={
                "unique_together": {("region", "name")},
            },
        ),
        migrations.CreateModel(
            name="City",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255)),
                ("zone", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="loans.zone")),
            ],
            options={
                "verbose_name_plural": "Cities",
                "unique_together": {("zone", "name")},
            },
        ),
    ]
