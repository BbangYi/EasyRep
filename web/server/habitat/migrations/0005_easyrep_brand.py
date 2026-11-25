from django.db import migrations, models


def rename_legacy_brand(apps, schema_editor):
    alias = schema_editor.connection.alias
    apps.get_model("habitat", "Organization").objects.using(alias).filter(name__iexact="HabitatOS").update(name="EasyRep")
    apps.get_model("habitat", "SiteSettings").objects.using(alias).filter(title__iexact="HabitatOS").update(title="EasyRep")


class Migration(migrations.Migration):
    dependencies = [("habitat", "0004_sensorless_care")]

    operations = [
        migrations.SeparateDatabaseAndState(state_operations=[
            migrations.AlterField(model_name="organization", name="name", field=models.CharField(default="EasyRep", max_length=80)),
            migrations.AlterField(model_name="sitesettings", name="title", field=models.CharField(default="EasyRep", max_length=60, verbose_name="사이트 이름")),
        ]),
        # Keep names on code rollback; never overwrite a later user rename.
        migrations.RunPython(rename_legacy_brand, migrations.RunPython.noop),
    ]
