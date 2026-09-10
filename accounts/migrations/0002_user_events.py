"""
The history of an account: created, role changed, password reset, deactivated.

⚠ THE EVENT, NEVER THE SECRET. No password, hashed or otherwise, goes in this
    table. What it answers is "who gave Ramesh access to purchase orders, and
    when" — the question that is impossible to reconstruct afterwards if it was
    not recorded at the time.

⚠ NOTHING IS BACKFILLED. Accounts that exist today get no "created" row,
    because nobody knows who created them or when. An empty history is honest.
"""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="UserEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("kind", models.CharField(
                    choices=[("created", "Account created"), ("role", "Role changed"),
                             ("password", "Password reset by an admin"),
                             ("deactivated", "Deactivated"), ("reactivated", "Reactivated"),
                             ("renamed", "User ID changed")],
                    max_length=20)),
                ("detail", models.CharField(blank=True, max_length=200)),
                ("at", models.DateTimeField(auto_now_add=True)),
                ("by", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name="user_events_caused", to=settings.AUTH_USER_MODEL)),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="events", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "account event",
                "ordering": ["-at", "-id"],
            },
        ),
    ]
