"""
A material group can be retired, like a vendor group or a unit already could.

⚠⚠ THIS FIXES A CONTROL THAT WAS DRAWN AND COULD NOT ACT. The shared master
   template prints an Active column for all three code-and-name tables;
   MaterialGroup had no such field, so all 25 rows rendered unchecked — reading
   as "everything is deactivated" — and ticking one saved nothing, because the
   view guards with hasattr. Nothing was ever corrupted. It simply lied, and
   Saahil found it by looking at the screen.

⚠ DEFAULT TRUE, so every existing group stays exactly as it is. Nobody has to go
  and turn 25 things back on after migrating.

⚠ IT CANNOT AFFECT AN EXISTING MATERIAL CODE. The group code is the middle
  segment of every code under it and codes are assigned once — ANCHOR: CODE-GEN.
  Inactive means "do not offer this again", never "this is wrong".
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('masters', '0011_vendorrate_source_po_line'),
    ]

    operations = [
        migrations.AddField(
            model_name='materialgroup',
            name='is_active',
            field=models.BooleanField(default=True),
        ),
    ]
