"""
The role table, and a role for everybody who already exists.

⚠ THE SEED IS THE IMPORTANT HALF.
    The moment `LoginRequiredMiddleware` is switched on, the only way into this
    system is an account that can sign in. Saahil's superuser is currently the
    only account there is, so it gets the Admin role here, in the same migration
    that creates the table. If that seeding were left to a management command
    somebody had to remember, the first run on the server would produce a
    perfectly secured application that nobody could enter.

⚠ AND IT DOES NOT ASK ANYONE TO CHANGE A PASSWORD THEY ALREADY CHOSE.
    `must_change_password` defaults to True — right for an account whose first
    password was typed by somebody else — and is set False here for accounts
    that predate this screen. Their owners picked those passwords themselves.
"""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def give_everyone_a_role(apps, schema_editor):
    """
    ⚠ SUPERUSERS BECOME ADMIN; ANYBODY ELSE BECOMES A SITE ENGINEER — the least
      that can be done with an account, on the principle that a role handed out
      by a migration should never be the most powerful one by accident.

      Today that second branch touches nothing: there is exactly one account.
      It exists because "today" is a description of one database.
    """
    User = apps.get_model(settings.AUTH_USER_MODEL)
    UserProfile = apps.get_model("accounts", "UserProfile")

    for user in User.objects.all():
        UserProfile.objects.update_or_create(
            user=user,
            defaults={
                "role": "admin" if user.is_superuser else "site",
                "must_change_password": False,
            },
        )


def take_them_away(apps, schema_editor):
    apps.get_model("accounts", "UserProfile").objects.all().delete()


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="UserProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("role", models.CharField(
                    choices=[("admin", "Admin"), ("pm", "Project manager"),
                             ("purchase", "Purchase manager"), ("accountant", "Accountant"),
                             ("site", "Site engineer"), ("compliance", "Compliance")],
                    default="site", max_length=20)),
                ("must_change_password", models.BooleanField(
                    default=True,
                    help_text="Forces a password change on the next sign-in.")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name="users_created", to=settings.AUTH_USER_MODEL)),
                ("user", models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="profile", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "user role",
                "verbose_name_plural": "user roles",
            },
        ),
        migrations.RunPython(give_everyone_a_role, take_them_away),
    ]
