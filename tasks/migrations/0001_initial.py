"""
Header tasks, subtasks and milestones.

⚠ THREE NEW TABLES AND NOTHING ELSE TOUCHED. No column is added to a project, a
    BOM line or a purchase order — tasks are descriptions, not materials, and
    nothing existing has to change shape to carry them.

⚠ THE ACTIVITY IS A FOREIGN KEY, PROTECTED. The BOQ reserve matches activities
    by NAME and that is a known landmine; this is the same relationship done by
    ID so renaming an activity cannot orphan anything.
"""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("masters", "0008_unit_of_measure_master"),
        ("projects", "0010_who_raised_delivered_and_paid"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="TaskHeader",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120)),
                ("start", models.DateField(
                    help_text="When the manager expects this work to begin.")),
                ("days", models.PositiveIntegerField(
                    default=7,
                    help_text="Duration in days. The finish is worked out from this.")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("activity", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="task_headers", to="masters.activity")),
                ("created_by", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name="task_headers_created", to=settings.AUTH_USER_MODEL)),
                ("owner", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name="task_headers_owned", to=settings.AUTH_USER_MODEL)),
                ("project", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="task_headers", to="projects.project")),
            ],
            options={"ordering": ["start", "id"]},
        ),
        migrations.CreateModel(
            name="Milestone",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120)),
                ("date", models.DateField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name="milestones_created", to=settings.AUTH_USER_MODEL)),
                ("project", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="milestones", to="projects.project")),
            ],
            options={"ordering": ["date", "id"]},
        ),
        migrations.CreateModel(
            name="Subtask",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("title", models.CharField(
                    help_text="What needs doing, in their words.", max_length=200)),
                ("start", models.DateField()),
                ("days", models.PositiveIntegerField(default=1)),
                ("priority", models.CharField(
                    choices=[("H", "High"), ("N", "Normal"), ("L", "Low")],
                    default="N", max_length=1)),
                ("status", models.CharField(
                    choices=[("open", "Not started"), ("blocked", "Blocked"), ("done", "Done")],
                    default="open", max_length=10)),
                ("finished_on", models.DateField(blank=True, null=True)),
                ("delay_reason", models.CharField(
                    blank=True,
                    choices=[("material", "Material not delivered"),
                             ("trade", "Waiting on another trade"), ("weather", "Weather"),
                             ("labour", "Labour short"), ("decision", "Decision needed"),
                             ("access", "Access not available")],
                    max_length=20)),
                ("delay_note", models.CharField(blank=True, max_length=200)),
                ("blocked_reason", models.CharField(
                    blank=True,
                    choices=[("material", "Material not delivered"),
                             ("trade", "Waiting on another trade"), ("weather", "Weather"),
                             ("labour", "Labour short"), ("decision", "Decision needed"),
                             ("access", "Access not available")],
                    max_length=20)),
                ("blocked_note", models.CharField(blank=True, max_length=200)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("assignee", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name="subtasks", to=settings.AUTH_USER_MODEL)),
                ("created_by", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name="subtasks_created", to=settings.AUTH_USER_MODEL)),
                ("header", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="subtasks", to="tasks.taskheader")),
            ],
            options={"ordering": ["start", "id"]},
        ),
        migrations.AddConstraint(
            model_name="taskheader",
            constraint=models.UniqueConstraint(
                fields=("project", "name"), name="one_header_name_per_project"),
        ),
    ]
