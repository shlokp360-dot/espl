"""
Slice 8, step 1 of 2 — the activity master arrives in `masters`.

⚠ NOT ONE ROW MOVES, AND NOT ONE TABLE IS TOUCHED.
    This is `SeparateDatabaseAndState` with an EMPTY database half. Django's
    idea of which app owns the model changes; the database does not know the
    difference. The table is still `projects_activity`, pinned by Meta.db_table
    on the new model, and every foreign key that pointed at it still does.

WHY THE MODEL MOVED
    Saahil, on where the activity master belongs:

        "It's basically the activities that belong in the BOQ are to come from
         a particular master data and the masters material master … is supposed
         to have a reference to an activity."

    It lived in `projects` so that "projects knows about masters, masters knows
    nothing about projects". That held while nothing in masters needed a trade.
    In this slice a material names its home activity and a vendor names the
    trades it serves, so masters needs one — and the choice was to either point
    across apps or admit the row was master data all along.

⚠ THE TABLE NAME IS DELIBERATELY LEFT WRONG.
    Renaming `projects_activity` to `masters_activity` would rewrite a table
    that every BOM line and estimate points at, to tidy a word in a database
    nobody opens. Nothing in the system reads a table name. Two risks were on
    offer and only one of them bought anything, so only one was taken.

⚠ MUST RUN BEFORE projects/0009. That migration deletes the model from the
    projects app's state, and deleting it before it exists here would leave a
    window with no Activity in the graph at all.
"""
from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ("masters", "0005_companyprofile_vendor_default_document_type"),
        # The table, and its rows, must already exist. 0003 seeds the 18 trades.
        ("projects", "0003_seed_activity_master"),
    ]

    # ⚠ Django cannot work out on its own that a model in one app is the same
    #   model that used to be in another. Saying so here is what stops it
    #   generating a CREATE TABLE and a DROP TABLE that would take the data with
    #   it.
    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.CreateModel(
                    name="Activity",
                    fields=[
                        ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                                   serialize=False, verbose_name="ID")),
                        ("abbreviation", models.CharField(
                            help_text="Three capital letters, typed by you. Must be unique — "
                                      "the system checks. Auto-deriving from the name collides "
                                      "(Fabrication vs Fire Fighting).",
                            max_length=3, unique=True,
                            validators=[django.core.validators.RegexValidator(
                                "^[A-Z]{3}$",
                                "Exactly three capital letters, e.g. RCC. It becomes the first "
                                "part of every material code under this activity.")])),
                        ("name", models.CharField(max_length=120, unique=True)),
                        ("rate", models.DecimalField(
                            decimal_places=2, max_digits=10,
                            help_text="Rupees per sqft of built-up area. EX-GST.",
                            validators=[django.core.validators.MinValueValidator(0)])),
                        ("gst_percent", models.DecimalField(decimal_places=2, default=18,
                                                            max_digits=5)),
                        ("basis", models.CharField(
                            blank=True, max_length=300,
                            help_text="Specification assumption shown beside the rate")),
                        ("sort_order", models.PositiveIntegerField(
                            default=0, help_text="Order of work on site")),
                        ("is_active", models.BooleanField(default=True)),
                        ("updated_at", models.DateTimeField(auto_now=True)),
                    ],
                    options={
                        "ordering": ["sort_order", "name"],
                        "verbose_name_plural": "activities",
                        "db_table": "projects_activity",
                    },
                ),
            ],
        ),
    ]
