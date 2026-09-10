"""
The baseline: what was first promised, kept when the plan moves.

>>> ANCHOR: TASK-BASELINE <<<

⚠ FOUR COLUMNS ON EACH LEVEL, ALL NULLABLE, NOTHING BACKFILLED. A task that has
    never been rescheduled has no original — the promise IS the plan until
    somebody changes it, and inventing a baseline for existing rows would be
    inventing a history they do not have.

⚠ THE SEVENTH DELAY REASON. `scope` — "Scope or design changed" — is added to
    the six agreed with the customer, because a plan that moves because the
    drawing changed is none of the other six, and without a word for it people
    will pick "Decision needed" and the count stops meaning anything.
    Three AlterFields below carry it to the columns that already existed; they
    change no data and no column type — Django records the choices, and CI's
    `makemigrations --check` fails without them.
"""
from django.db import migrations, models

REASONS = [
    ("material", "Material not delivered"),
    ("trade", "Waiting on another trade"),
    ("weather", "Weather"),
    ("labour", "Labour short"),
    ("decision", "Decision needed"),
    ("access", "Access not available"),
    ("scope", "Scope or design changed"),
]


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="taskheader",
            name="original_start",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="taskheader",
            name="original_days",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="taskheader",
            name="shift_reason",
            field=models.CharField(blank=True, choices=REASONS, max_length=20),
        ),
        migrations.AddField(
            model_name="taskheader",
            name="shift_note",
            field=models.CharField(blank=True, max_length=200),
        ),

        migrations.AddField(
            model_name="subtask",
            name="original_start",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="subtask",
            name="original_days",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="subtask",
            name="shift_reason",
            field=models.CharField(blank=True, choices=REASONS, max_length=20),
        ),
        migrations.AddField(
            model_name="subtask",
            name="shift_note",
            field=models.CharField(blank=True, max_length=200),
        ),

        # The choices only. No data moves.
        migrations.AlterField(
            model_name="subtask",
            name="delay_reason",
            field=models.CharField(blank=True, choices=REASONS, max_length=20),
        ),
        migrations.AlterField(
            model_name="subtask",
            name="blocked_reason",
            field=models.CharField(blank=True, choices=REASONS, max_length=20),
        ),
    ]
