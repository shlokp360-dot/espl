"""
Renames TradeDefault -> Activity, gives it the abbreviation that starts every
material code, and creates the MaterialActivity link table.

WHY A RENAME AND NOT A DROP-AND-RECREATE
    `makemigrations` proposed deleting TradeDefault and creating Activity. That
    works today only because the table is empty — on any database with rates in
    it, those rates would be silently destroyed. RenameModel keeps the table and
    its rows, so this migration is safe to run anywhere.

WHY THE ABBREVIATION IS ADDED IN THREE STEPS
    It is unique and required. Adding a unique column to a table that already
    has rows would make every row collide on the same default. So: add it
    nullable, fill in anything already there, then tighten it to required. On an
    empty database the middle step does nothing — it exists for safety.
"""
from django.db import migrations, models
import django.core.validators
import django.db.models.deletion


def fill_missing_abbreviations(apps, schema_editor):
    """
    Give any pre-existing activity a placeholder abbreviation so the column can
    be made required. Derives AAA, AAB, AAC... — deliberately ugly, because a
    placeholder should look wrong until a human replaces it.

    On a fresh database this does nothing at all.
    """
    Activity = apps.get_model("projects", "Activity")
    rows = Activity.objects.filter(abbreviation__isnull=True).order_by("id")
    if not rows.exists():
        return
    used = set(
        Activity.objects.exclude(abbreviation__isnull=True).values_list("abbreviation", flat=True)
    )
    for n, row in enumerate(rows):
        candidate = f"A{n // 26:01d}{chr(65 + n % 26)}"[:3].upper().ljust(3, "X")
        while candidate in used:
            candidate = f"X{len(used) % 100:02d}"
            used.add(candidate)
        used.add(candidate)
        row.abbreviation = candidate
        row.save(update_fields=["abbreviation"])


class Migration(migrations.Migration):

    dependencies = [
        ("masters", "0001_initial"),
        ("projects", "0001_initial"),
    ]

    operations = [
        migrations.RenameModel(old_name="TradeDefault", new_name="Activity"),
        migrations.AlterModelOptions(
            name="activity",
            options={"ordering": ["sort_order", "name"], "verbose_name_plural": "activities"},
        ),
        # --- the abbreviation, in three safe steps ---
        migrations.AddField(
            model_name="activity",
            name="abbreviation",
            field=models.CharField(
                max_length=3, null=True, unique=True,
                validators=[django.core.validators.RegexValidator(
                    "^[A-Z]{3}$",
                    "Exactly three capital letters, e.g. RCC. It becomes the first part of "
                    "every material code under this activity.",
                )],
                help_text="Three capital letters, typed by you. Must be unique — the system checks. "
                          "Auto-deriving from the name collides (Fabrication vs Fire Fighting).",
            ),
        ),
        migrations.RunPython(fill_missing_abbreviations, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="activity",
            name="abbreviation",
            field=models.CharField(
                max_length=3, unique=True,
                validators=[django.core.validators.RegexValidator(
                    "^[A-Z]{3}$",
                    "Exactly three capital letters, e.g. RCC. It becomes the first part of "
                    "every material code under this activity.",
                )],
                help_text="Three capital letters, typed by you. Must be unique — the system checks. "
                          "Auto-deriving from the name collides (Fabrication vs Fire Fighting).",
            ),
        ),
        migrations.AlterField(
            model_name="activity",
            name="rate",
            field=models.DecimalField(
                decimal_places=2, max_digits=10,
                help_text="Rupees per sqft of built-up area. EX-GST.",
                validators=[django.core.validators.MinValueValidator(0)],
            ),
        ),
        # --- which activities offer which materials ---
        migrations.CreateModel(
            name="MaterialActivity",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("is_home", models.BooleanField(
                    default=False,
                    help_text="The activity this material belongs to. "
                              "Its abbreviation is in the material's code.")),
                ("activity", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="material_links", to="projects.activity")),
                ("material", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="activity_links", to="masters.material")),
            ],
            options={
                "verbose_name_plural": "material activities",
                "ordering": ["material", "activity"],
                "unique_together": {("material", "activity")},
            },
        ),
    ]
