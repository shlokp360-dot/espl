"""
Adds Material.is_common — the flag for consumables used across every trade.

Wall plugs, khilli, 1/4 washers, fevicol, hacksaw blades: 22 materials in the
current master are tagged "used in ALL activities". A common material appears in
every activity's dropdown, whatever its home activity is.

WHY A FLAG RATHER THAN A LINK ROW PER ACTIVITY
    Link rows would mean 22 materials x 18 activities = 396 rows, and they would
    be wrong the moment a nineteenth activity is added — none of the 22 would be
    linked to it, so wall plugs would quietly disappear from that trade's list.
    A flag stays true for activities that do not exist yet.

Safe to run on a populated database: the field defaults to False, so every
existing material keeps its current behaviour until the import sets it.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("masters", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="material",
            name="is_common",
            field=models.BooleanField(
                default=False,
                help_text="Used across every trade. Appears in every activity's material list.",
            ),
        ),
        migrations.AlterField(
            model_name="material",
            name="code",
            field=models.CharField(
                max_length=20, unique=True,
                help_text="ACTIVITY-GROUP-SERIAL, e.g. PLM-PL3-014. Generated, never typed.",
            ),
        ),
        migrations.AlterField(
            model_name="material",
            name="subgroup",
            field=models.CharField(
                max_length=6, default="GEN",
                help_text="Carried over from the old code scheme. Not part of the new code.",
            ),
        ),
    ]
