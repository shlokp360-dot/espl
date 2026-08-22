"""
Slice 6, step 1 — project codes are assigned by the system, never typed.

WHAT CHANGES
    `Project.code` becomes `blank=True` so a new project can be saved without
    one. `Project.save()` then fills it in from the `project` NumberSeries —
    PRJ-000001, PRJ-000002, and so on.

WHY
    The same rule that already governs materials, vendors and purchase orders:
    a code is an IDENTITY, handed out once and never reused. Letting somebody
    type PRJ-BHUD because it reads better was considered and rejected — two
    people invent two schemes within a month, and a typo becomes permanent,
    because a code that other records point at can never be corrected.

⚠ NOTHING IS DROPPED, RENAMED OR REWRITTEN, and no existing code is touched.
    `save()` only generates when the field is empty, so PRJ-DEMO and PRJ-001
    keep exactly the codes they have. The unique constraint is unchanged.

⚠ THE COUNTER STARTS AT ZERO regardless of what already exists, exactly like
    the purchase-order series. That is safe here because the generated format
    (PRJ-000001, six digits) does not collide with the hand-typed codes already
    in the database. If it ever did, the unique constraint would refuse the save
    loudly rather than quietly writing a duplicate — which is the right failure.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0007_slice5a_document_fields'),
    ]

    operations = [
        migrations.AlterField(
            model_name='project',
            name='code',
            field=models.CharField(
                blank=True, max_length=12, unique=True,
                help_text='Assigned automatically, e.g. PRJ-000001. Never typed.'),
        ),
    ]
