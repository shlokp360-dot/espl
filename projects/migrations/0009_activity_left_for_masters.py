"""
Slice 8, step 2 of 2 — the projects app lets go of the activity master.

⚠ AGAIN, NOTHING HAPPENS TO THE DATABASE. `SeparateDatabaseAndState` with an
    empty database half: the foreign keys are re-pointed in Django's STATE from
    `projects.Activity` to `masters.Activity`, and since both names refer to the
    same table, `projects_activity`, no column changes and no row moves.

    Run `sqlmigrate` on this and it prints nothing. That is the whole point.

WHAT WOULD HAVE HAPPENED WITHOUT IT
    Django would have seen a model vanish from one app and appear in another,
    and generated DeleteModel plus CreateModel — dropping the table containing
    all 18 trades, which every BOM line, every purchase order line and every
    estimate depends on. The two halves of this move exist to make that
    impossible rather than merely unlikely.

⚠ DEPENDS ON masters/0006 AND MUST RUN AFTER IT. The model has to exist in its
    new home before it stops existing in this one.
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0008_project_code_is_generated"),
        ("masters", "0006_activity_moves_into_masters"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                # Re-point everything that named the old owner, THEN drop it.
                # The other order would leave a foreign key referring to a model
                # the state no longer has.
                migrations.AlterField(
                    model_name="materialactivity",
                    name="activity",
                    field=models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="material_links", to="masters.activity"),
                ),
                migrations.AlterField(
                    model_name="bomline",
                    name="activity",
                    field=models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="bom_lines", to="masters.activity"),
                ),
                migrations.DeleteModel(name="Activity"),
            ],
        ),
    ]
