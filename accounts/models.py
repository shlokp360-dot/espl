"""
Who a person is, and what they are allowed to be.

WHAT THIS FILE IS FOR
    One field — `UserProfile.role` — and the vocabulary of roles it can hold.
    Nothing here decides what a role may DO; that is the matrix, and it arrives
    in the next commit as data in `accounts/perms.py`.

⚠ WHY A PROFILE AND NOT A CUSTOM USER MODEL
    A custom user model is the right answer on day one of a project. This is not
    day one: there is a live database with real projects, purchase orders and
    receipts in it, and swapping the user model underneath an existing
    `auth_user` table is a migration with a genuine chance of losing the one
    account that can log in and fix it. A one-to-one profile costs one extra
    join and cannot lose anybody.

⚠ THE LOGIN IS A SHORT USER ID, ON THE SAP MODEL
    Saahil's call — "keep login with username only", and then "like sap". So the
    Users screen asks for `ramesh`, not an address, and Django's own `username`
    column holds exactly that. An email is optional and signs nobody in; it is
    there for the day there is something to send.

    `accounts.backends.LoginBackend` matches it case-insensitively — SAP writes
    user IDs in capitals and a phone capitalises the first letter by itself, and
    neither should look like a wrong password.
"""
from django.conf import settings
from django.db import models


class Role(models.TextChoices):
    """
    The six roles, agreed screen by screen with the customer in the room.

    ⚠ THE VALUES ARE NOT FREE TO CHANGE. `projects/hub.py` already tags every
      launchpad tile with "admin", "purchase" and "site" — it was written that
      way months before this app existed, precisely so that filtering the
      launchpad by role would be one argument rather than a rewrite. The three
      strings below match it deliberately.

    ⚠ ROLES ARE FIXED IN CODE, USERS ARE NOT. Saahil, asked whether the admin
      should be able to invent new roles: "the admin should be able to add new
      users based on these defined roles for new hires." A screen for editing
      the roles themselves was offered and turned down — it doubles the slice
      and turns a reviewable matrix into database rows nobody audits.
    """

    ADMIN = "admin", "Admin"
    PROJECT_MANAGER = "pm", "Project manager"
    PURCHASE = "purchase", "Purchase manager"
    ACCOUNTANT = "accountant", "Accountant"
    SITE = "site", "Site engineer"
    COMPLIANCE = "compliance", "Compliance"


class UserProfile(models.Model):
    """
    The one row that says which of the six a person is.

    ⚠ ONE ROLE PER PERSON. Saahil chose this over Django's groups and
      permissions: a company with no IT team is not going to curate forty
      permission tick-boxes, and a mis-ticked box is silent. One field is
      readable, greppable, and wrong in an obvious way rather than a subtle one.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.SITE)

    # ⚠ The admin sets the first password and tells the person what it is, so
    #   until they change it TWO people know it. This flag is what makes that a
    #   temporary state rather than a permanent one — see accounts/middleware.py.
    must_change_password = models.BooleanField(
        default=True,
        help_text="Forces a password change on the next sign-in.")

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="users_created")

    class Meta:
        verbose_name = "user role"
        verbose_name_plural = "user roles"

    def __str__(self):
        return f"{self.user.get_username()} — {self.get_role_display()}"

    @property
    def is_admin(self):
        return self.role == Role.ADMIN


class UserEvent(models.Model):
    """
    What has happened TO an account, and who did it.

    >>> ANCHOR: USER-HISTORY <<<

    ⚠ THE EVENT, NEVER THE SECRET. Saahil asked whether an admin could see a
      changed password. They cannot — passwords are one-way hashes, and if they
      were readable by an admin they would be readable by whoever steals the
      database. What IS worth keeping is the fact that a reset happened, who did
      it and when, because that is the question actually asked six months later:
      "who gave Ramesh access to purchase orders?"

    ⚠ IT IS APPEND-ONLY IN PRACTICE. Nothing in the application edits or deletes
      a row here. A history somebody can tidy up is not a history.

    ⚠ `detail` IS A SENTENCE, NOT A DIFF. "Site engineer → Purchase manager" is
      what a person needs; storing the old and new values in separate columns
      would mean rebuilding that sentence in every template that shows it.
    """

    class Kind(models.TextChoices):
        CREATED = "created", "Account created"
        ROLE = "role", "Role changed"
        PASSWORD = "password", "Password reset by an admin"
        DEACTIVATED = "deactivated", "Deactivated"
        REACTIVATED = "reactivated", "Reactivated"
        RENAMED = "renamed", "User ID changed"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="events")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    detail = models.CharField(max_length=200, blank=True)
    # ⚠ SET_NULL: the admin who did it may themselves be deactivated one day,
    #   and losing the whole event because of that would be worse than losing
    #   the name.
    by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="user_events_caused")
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-at", "-id"]
        verbose_name = "account event"

    def __str__(self):
        return f"{self.user.get_username()} — {self.get_kind_display()}"


def record(user, kind, by=None, detail=""):
    """One line, so a view never has to remember the field names."""
    return UserEvent.objects.create(user=user, kind=kind, by=by, detail=detail)


def role_of(user):
    """
    The role string for a user, or None if there is nobody / no profile yet.

    ⚠ EVERY CALLER GOES THROUGH THIS, so a user who somehow has no profile row
      degrades to "no role" — which the permission layer will refuse — rather
      than raising `RelatedObjectDoesNotExist` in the middle of a page.
    """
    if not user or not user.is_authenticated:
        return None
    profile = getattr(user, "profile", None)
    return profile.role if profile else None


def ensure_bootstrap_admin(user):
    """
    The very first Admin on a brand-new database, and nobody after that.

    >>> ANCHOR: BOOTSTRAP-ADMIN <<<
    ⚠⚠ THE DEADLOCK THIS EXISTS TO BREAK, hit for real on 16 Aug 2026 during the
       PostgreSQL rehearsal. `createsuperuser` makes a `User` and NO
       `UserProfile`, the permission matrix reads `UserProfile.role`, and there
       is no Django Admin to repair it from. So a freshly built system opens on
       an almost empty launchpad where every tile refuses you, and it looks
       exactly like the application is broken.

    ⚠ IT WAS NEVER QUITE A WALL — a superuser could reach the Users screen
      through the escape in `accounts.views._admin_only` and create a SECOND
      account as Admin, then sign in as that. But nobody finds that, and
      safeguard 2 pointed the wrong way while they looked: "Ask another Admin"
      when there is no other Admin.

    ⚠⚠ THE CONDITION IS "THIS SYSTEM HAS NO ADMIN", NOT "THIS USER IS A
       SUPERUSER". That distinction is the whole design.

       Granting Admin to every superuser would have been the easier rule and it
       reverses a decision made deliberately elsewhere — `perms.can()` says a
       superuser is NOT automatically allowed, because being able to open a
       shell should not silently mean being able to approve a purchase order.
       Superuser is handed out by whoever administers the server; Admin is a
       business role. They are different questions and they stay different.

       So this door closes behind itself. The moment one active Admin exists it
       never opens again, and a superuser created in year two is given a role by
       an Admin like everybody else.

    ⚠ THE SAME PREDICATE AS SAFEGUARD 3 in `accounts.views.user_form` —
      `role=ADMIN, user__is_active=True`. The two rules have to agree, or the
      screen would refuse to remove the last Admin while this quietly decided
      there was not one. It also means that if every Admin is ever deactivated
      the door reopens, which is the same emergency and the same answer.

    ⚠ IT IS RECORDED, NOT SILENT. A privilege that appears on its own with
      nothing in the history is indistinguishable from one somebody granted
      themselves. `UserEvent` already answers "who gave Ramesh access?" and this
      writes to it with `by=None`, which reads as "the system did".

    Returns True only when it actually granted, so the caller can say so on
    screen. Cheap: the count query runs only for a superuser who has no role,
    which is nobody at all after the first day.
    """
    if not user or not user.is_authenticated or not user.is_superuser:
        return False
    if role_of(user) is not None:
        return False
    if UserProfile.objects.filter(role=Role.ADMIN, user__is_active=True).exists():
        return False

    profile, _ = UserProfile.objects.update_or_create(
        user=user,
        defaults={"role": Role.ADMIN, "must_change_password": False})
    # ⚠ NOT `must_change_password=True`: this person typed their own password
    #   into `createsuperuser`. Nobody else has ever known it, which is the only
    #   thing that flag is for.

    # ⚠⚠ DJANGO CACHES THE *ABSENCE* OF A REVERSE ONE-TO-ONE. The lookup above
    #   stored "no profile" against this in-memory user, so every later
    #   `user.profile` in the same request would still find nothing and the
    #   caller would see the grant fail. Attaching it here fixes the object the
    #   caller is holding; `refresh_from_db()` is not enough on its own and
    #   depends on the Django version.
    user.profile = profile

    record(user, UserEvent.Kind.ROLE, by=None,
           detail="No role → Admin, because this system had no active Admin")
    return True
