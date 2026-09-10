"""
The units of measure become a master table instead of a hardcoded list.

WHY, AND WHY IT REVERSES AN EARLIER DECISION
    They were hardcoded on purpose: a fixed list cannot drift, and two spellings
    of one unit let two people record the same thing differently until "hours"
    never totals correctly.

    That reasoning held right up until the unit became a dropdown in a
    spreadsheet somebody else fills in. Saahil: "UOM master is needed as Uom is
    a drop down in excel, so how will that change in case there are future new
    uoms?" A missing unit is then not an inconvenience — their row is rejected
    and they can do nothing but telephone you.

⚠ MATERIALS ARE NOT TOUCHED. `Material.uom` stays the text "Bag". This table is
    what that text is CHECKED against, not what it points at. Nothing that
    prints changes and no row of the 705 is rewritten. `choices` comes off the
    field, though — leaving it there would mean a migration every time somebody
    added a unit, which is the friction this whole table exists to remove.

⚠ THE TEN UNUSED UNITS ARRIVE INACTIVE, NOT ABSENT.
    Measured on the real database: 18 of the 28 are in use, and Bottle, Day,
    Drum, Job, MT, Month, Rft, Set, Ton and Tractor are used by nothing at all.
    Saahil asked to "trim down the true excel master". Trimming means
    deactivating: they drop out of every dropdown while nothing that might
    reference them breaks, and turning one back on is a tick rather than a
    deployment.

⚠ THE ALIASES COME ACROSS TOO. HRS, HR and HOURS all mean Hour. That table is
    what stopped one unit arriving twice under two spellings, and if the master
    is editable while the aliases are not, the drift comes straight back the
    first time a spreadsheet says "Hrs".
"""
from django.db import migrations, models


# Everything the hardcoded list held, with the spelt-out name where the code is
# not obvious, and the aliases that used to live in UOM_ALIASES.
UNITS = [
    ("Nos", "Number of pieces", "NOS., NO, PCS, PIECE"),
    ("Set", "", ""),
    ("Pair", "", ""),
    ("Bag", "", "BAGS"),
    ("Packet", "", ""),
    ("Box", "", "BOXES"),
    ("Tin", "", ""),
    ("Bottle", "", ""),
    ("Bundle", "", ""),
    ("Drum", "", ""),
    ("Kg", "Kilogram", ""),
    ("Ton", "Tonne", "TONNE, TONNES"),
    ("MT", "Metric tonne", ""),
    ("Litre", "", "LTR, LTRS"),
    ("Metre", "", "MTR, MTS, M"),
    ("Rft", "Running foot", ""),
    ("Sqft", "Square foot", "SQ FT, SQFT, SQ.FT"),
    ("Sqm", "Square metre", ""),
    ("Cum", "Cubic metre", "CMT, CU M"),
    ("Tractor", "Tractor load", ""),
    ("Trip", "", ""),
    ("Job", "", ""),
    ("Hour", "", "HRS, HR, HOURS"),
    ("Day", "", ""),
    ("Month", "", ""),
    ("Lumpsum", "A single agreed amount", ""),
    ("House", "", ""),
    ("KW", "Kilowatt", ""),
]


def seed(apps, schema_editor):
    """
    Build the master, then deactivate anything no material actually uses.

    ⚠ WHAT IS IN USE IS READ FROM THE DATA, NOT FROM A LIST WRITTEN HERE. A
      hardcoded "these ten are unused" would be wrong the moment somebody's
      database differs from the one it was measured on — which is every
      database except Saahil's.
    """
    Unit = apps.get_model("masters", "UnitOfMeasure")
    Material = apps.get_model("masters", "Material")

    used = set(Material.objects.exclude(uom="").values_list("uom", flat=True).distinct())

    for order, (code, name, aliases) in enumerate(UNITS, start=1):
        Unit.objects.update_or_create(
            code=code,
            defaults={"name": name, "aliases": aliases, "sort_order": order,
                      "is_active": code in used or not used},
        )

    # A unit already on a material but not in the list above — impossible on
    # Saahil's data, possible on somebody else's. Carried in, active, rather
    # than left to fail validation later.
    for code in used - {code for code, _n, _a in UNITS}:
        Unit.objects.update_or_create(
            code=code, defaults={"sort_order": 900, "is_active": True})


def unseed(apps, schema_editor):
    apps.get_model("masters", "UnitOfMeasure").objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [("masters", "0007_vendor_group_and_activity_columns")]

    operations = [
        migrations.CreateModel(
            name="UnitOfMeasure",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("code", models.CharField(
                    max_length=20, unique=True,
                    help_text='What is stored on the material and printed on a document — '
                              '"Bag", "Cum".')),
                ("name", models.CharField(
                    blank=True, max_length=60,
                    help_text="Spelt out, if the code is not obvious. Cum → cubic metre.")),
                ("aliases", models.CharField(
                    blank=True, max_length=200,
                    help_text="Other spellings a spreadsheet might use, comma separated. "
                              "HRS, HR, HOURS all mean Hour.")),
                ("is_active", models.BooleanField(
                    default=True,
                    help_text="Off takes it out of every dropdown. Nothing already using it "
                              "breaks.")),
                ("sort_order", models.PositiveIntegerField(default=0)),
            ],
            options={
                "ordering": ["sort_order", "code"],
                "verbose_name": "unit of measure",
                "verbose_name_plural": "units of measure",
            },
        ),
        # ⚠ `choices` comes off the field. The values are unchanged; only Django's
        #   idea of what is permitted moves, from the model to the places data
        #   actually enters. Otherwise adding a unit means a migration.
        migrations.AlterField(
            model_name="material",
            name="uom",
            field=models.CharField(max_length=20),
        ),
        migrations.RunPython(seed, unseed),
    ]
