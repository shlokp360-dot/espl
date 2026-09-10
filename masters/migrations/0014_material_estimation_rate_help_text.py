"""
Wording only. `help_text` said the estimation rate drives the BOQ; it does not.

The BOQ is built from `Activity.rate` — rupees per sqft of built-up area. This
field is what a BOM line PLANS at when nobody has typed a project-specific rate,
and it is the benchmark purchase variance is measured against. Saahil spotted the
old sentence on the downloaded material master sheet.

⚠ NO SCHEMA CHANGE AND NO DATA CHANGE. Django requires a migration for a
  `help_text` edit because the field's deconstruction changes, and CI runs
  `makemigrations --check` — so without this file the build fails on a sentence.
"""
import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('masters', '0013_paneltranslation'),
    ]

    operations = [
        migrations.AlterField(
            model_name='material',
            name='estimation_rate',
            field=models.DecimalField(decimal_places=2, default=0, help_text="The BOM's planning value. Not a vendor price.", max_digits=12, validators=[django.core.validators.MinValueValidator(0)]),
        ),
    ]
