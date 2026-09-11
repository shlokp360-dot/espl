"""
The five types of drawing receivable, in the owner's words (11 Sep 2026):
"Architect, Structure, Survey, Passing and MEP are the main types of drawings
receivable." Passing is the AMC-approved (passed) plan set.

⚠ RENAMED IN PLACE, NOT REPLACED. ARC, STR, SUR and MEP already exist from
  `0002_seed_groups` and may already hold drawings, so their rows are kept and
  only the name and order change. PAS is created. LND and INT are deactivated
  only when nothing is filed under them; a group holding drawings stays active,
  because a section that vanished from the register with files still under it
  is the kind of hole this module does not make.

⚠ `get_or_create` / `update` so re-running is harmless, like 0002.
"""
from django.db import migrations

TYPES = [
    ("ARC", "Architect", 10),
    ("STR", "Structure", 20),
    ("SUR", "Survey", 30),
    ("PAS", "Passing", 40),
    ("MEP", "MEP", 50),
]
RETIRED = ["LND", "INT"]


def seed(apps, _schema_editor):
    DrawingGroup = apps.get_model("drawings", "DrawingGroup")
    for code, name, order in TYPES:
        row, created = DrawingGroup.objects.get_or_create(
            code=code, defaults={"name": name, "sort_order": order})
        if not created:
            row.name, row.sort_order, row.is_active = name, order, True
            row.save(update_fields=["name", "sort_order", "is_active"])
    # Retired rows sink to the bottom of the Groups screen, switched off; one
    # still holding drawings keeps its place and stays active.
    for offset, row in enumerate(DrawingGroup.objects.filter(code__in=RETIRED).order_by("code")):
        if row.drawings.exists():
            continue
        row.sort_order, row.is_active = 90 + offset * 10, False
        row.save(update_fields=["sort_order", "is_active"])


def unseed(apps, _schema_editor):
    DrawingGroup = apps.get_model("drawings", "DrawingGroup")
    DrawingGroup.objects.filter(code="PAS", drawings=None).delete()
    DrawingGroup.objects.filter(code__in=RETIRED).update(is_active=True)


class Migration(migrations.Migration):

    dependencies = [("drawings", "0002_seed_groups")]

    operations = [migrations.RunPython(seed, unseed)]
