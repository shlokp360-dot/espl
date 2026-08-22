"""
Where a captured vendor rate came from.

>>> ANCHOR: VENDOR-RATE-CAPTURE <<<
A rate is now written back to the vendor/material master when a purchase order
is approved, replacing whatever was there — so the row needs to say which order
proved it, or it is a number with no provenance.

⚠ ADD ONLY, AND NULLABLE. Nothing is rewritten and no existing row changes.
  Every rate already in the table — there are none on the live database, and
  seed_stress writes some — keeps a null source, which is truthful: nobody knows
  where those came from.

⚠ IT DEPENDS ON `projects` AS WELL AS `masters`, because the foreign key points
  the other way round to the usual direction of travel in this codebase. That is
  also why the model declares it as a string.
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('masters', '0010_alter_material_home_activity'),
        ('projects', '0010_who_raised_delivered_and_paid'),
    ]

    operations = [
        migrations.AddField(
            model_name='vendorrate',
            name='source_po_line',
            field=models.ForeignKey(blank=True, help_text='The approved order line this rate was taken from.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='captured_rates', to='projects.purchaseorderline'),
        ),
    ]
