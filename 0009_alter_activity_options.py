"""
The word on screen changes; nothing in the database does.

⚠ LABELS ONLY. Saahil asked for "activity" to read "construction activity" —
  his people say trade or construction activity, never the bare word. This
  migration carries no schema change at all: the table is still
  projects_activity, the class is still Activity, and every relation is
  untouched. It exists because Django records Meta options in migration state.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('masters', '0008_unit_of_measure_master'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='activity',
            options={'ordering': ['sort_order', 'name'], 'verbose_name': 'construction activity', 'verbose_name_plural': 'construction activities'},
        ),
    ]
