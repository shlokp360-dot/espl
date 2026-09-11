"""
Transmittals are gone. The owner, 11 Sep 2026: "No requirement of transmittal,
just revisions." The two tables are dropped outright — no production data
existed in them — and the `transmittal` NumberSeries row, if one was ever
taken, is left alone: a number series is never rewound.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [("drawings", "0003_five_types")]

    operations = [
        migrations.DeleteModel(name="TransmittalLine"),
        migrations.DeleteModel(name="Transmittal"),
    ]
