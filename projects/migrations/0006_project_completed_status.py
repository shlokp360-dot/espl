"""
Adds COMPLETED to a project's status list.

WHY
    A project can never be deleted once anything has been delivered — a receipt
    protects its PO line, which protects the order, which protects the project.
    So finished jobs pile up on the list forever. Saahil's answer: mark them
    Completed and filter the list, rather than trying to delete them.

SAFE TO RUN
    This changes the LIST OF ALLOWED VALUES, not the column and not a single
    row. `choices` lives in Django, not in the database, so nothing is rewritten
    and no existing project changes status. Compare with the Activity rename in
    migration 0002, which had to be written by hand because Django's automatic
    version proposed dropping and recreating the table.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0005_number_series"),
    ]

    operations = [
        migrations.AlterField(
            model_name="project",
            name="status",
            field=models.CharField(
                choices=[("draft", "Draft"), ("quoted", "Quoted"), ("won", "Won"),
                         ("completed", "Completed"), ("lost", "Lost")],
                default="draft", max_length=10),
        ),
    ]
