"""
The six register sections every site starts with.

⚠ A DATA MIGRATION, NOT A FIXTURE, so a fresh database and the test database
  both have them without anybody remembering to load anything. `get_or_create`
  so re-running is harmless.
"""
from django.db import migrations

GROUPS = [
    ("ARC", "Architectural", 10),
    ("STR", "Structural", 20),
    ("MEP", "Mechanical/Electrical/Plumbing", 30),
    ("LND", "Landscape", 40),
    ("INT", "Interior", 50),
    ("SUR", "Survey", 60),
]


def seed(apps, _schema_editor):
    DrawingGroup = apps.get_model("drawings", "DrawingGroup")
    for code, name, order in GROUPS:
        DrawingGroup.objects.get_or_create(code=code, defaults={"name": name, "sort_order": order})


def unseed(apps, _schema_editor):
    DrawingGroup = apps.get_model("drawings", "DrawingGroup")
    DrawingGroup.objects.filter(code__in=[code for code, _n, _o in GROUPS], drawings=None).delete()


class Migration(migrations.Migration):

    dependencies = [("drawings", "0001_initial")]

    operations = [migrations.RunPython(seed, unseed)]
