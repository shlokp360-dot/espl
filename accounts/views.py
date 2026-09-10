"""
Signing in, changing a password, and the Users screen.

>>> ANCHOR: USERS-SCREEN <<<

⚠ THE SCREEN LIVES UNDER MASTER DATA, NOT ON THE LAUNCHPAD.
    Saahil's instruction: "create a user Admin screen, where the user can add
    user ID and passwords to specified roles — add it under master data tile."
    It sits beside Materials, Vendors, Company profile and Company rates, which
    is where the other things-you-set-up-once already live.

⚠ THE FOUR SAFEGUARDS BELOW ARE NOT DECORATION. Each of them is a way to lock
    every human being out of user management permanently, and none of them is
    recoverable from inside the app.
"""
import re

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.views import PasswordChangeView
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST

from accounts import perms
from accounts.models import Role, UserEvent, UserProfile, record, role_of
from accounts.passwords import readable_password

User = get_user_model()

#: What a user ID may be made of. Letters, digits, dot, dash, underscore —
#: deliberately no spaces and no @, so nobody mistakes it for an email address.
USERNAME_SHAPE = re.compile(r"^[A-Za-z0-9._-]{2,30}$")


class ChangeOwnPassword(PasswordChangeView):
    """
    ⚠ CLEARING THE FLAG IS THE WHOLE POINT. Without this the forced-change
      middleware would send somebody straight back to this page after they had
      already done what it asked.
    """

    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("launchpad")

    def form_valid(self, form):
        response = super().form_valid(form)
        profile = getattr(self.request.user, "profile", None)
        if profile and profile.must_change_password:
            profile.must_change_password = False
            profile.save(update_fields=["must_change_password"])
        messages.success(self.request, "Password changed.")
        return response


# --------------------------------------------------------------- the guard
#
# ⚠ THE PLACEHOLDER THAT USED TO LIVE HERE IS GONE. It checked `role == admin`
#   by hand because the matrix did not exist yet; it now reads the matrix like
#   every other screen, through @requires("users.manage").
#
# ⚠ THE SUPERUSER ESCAPE IS KEPT, AND ONLY HERE. `perms.can()` deliberately does
#   NOT let `is_superuser` satisfy a business rule — being able to open Django
#   Admin should not mean being able to approve a purchase order. User
#   management is the one exception: if every Admin account is somehow lost or
#   locked out, the superuser must still be able to make one, and the
#   alternative is a shell on the server, which is exactly what a company with
#   no IT team does not have.
def _admin_only(request):
    if perms.can(request.user, "users.manage") or request.user.is_superuser:
        return None
    return HttpResponseForbidden(
        "Only an Admin can manage users. Ask an Admin if you think it should be you.")


def _display_name(user):
    return (user.get_full_name() or user.get_username()).strip()


# ---------------------------------------------------------------- the list
def user_list(request):
    """Everyone, with the dormant and the deactivated visible rather than hidden."""
    denied = _admin_only(request)
    if denied:
        return denied

    q = (request.GET.get("q") or "").strip()
    role = (request.GET.get("role") or "").strip()
    show = (request.GET.get("show") or "active").strip()

    # ⚠ select_related on the profile: without it this is one query per row,
    #   which is bug 3 in the project's own list and was written three times
    #   before anybody noticed.
    users = User.objects.select_related("profile").order_by("first_name", "username")

    if q:
        users = users.filter(
            Q(first_name__icontains=q) | Q(last_name__icontains=q)
            | Q(username__icontains=q) | Q(email__icontains=q))
    if role:
        users = users.filter(profile__role=role)
    if show == "active":
        users = users.filter(is_active=True)
    elif show == "inactive":
        users = users.filter(is_active=False)

    page = Paginator(users, 100).get_page(request.GET.get("page"))

    return render(request, "accounts/user_list.html", {
        "page": page,
        "q": q,
        "role": role,
        "show": show,
        "roles": Role.choices,
        # ⚠ paginator.count, not a second COUNT query — that mistake has been
        #   made three times in this codebase already.
        "total": page.paginator.count,
        "active_count": User.objects.filter(is_active=True).count(),
        "inactive_count": User.objects.filter(is_active=False).count(),
    })


# ---------------------------------------------------------------- the form
def user_form(request, user_id=None):
    """
    One screen creates and edits, like the material and vendor screens.

    On a new user the password box is required. On an existing one it is blank
    and optional — filling it in is a reset, leaving it alone changes nothing.
    """
    denied = _admin_only(request)
    if denied:
        return denied

    person = get_object_or_404(User.objects.select_related("profile"), pk=user_id) if user_id else None
    errors = []
    # ⚠ WHAT THEY TYPED COMES BACK WITH THE ERROR. A refused form that also
    #   empties itself makes the person type it all again to find out whether
    #   they fixed the one thing that was wrong.
    typed = {}

    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        username = (request.POST.get("username") or "").strip()
        email = (request.POST.get("email") or "").strip()
        role = (request.POST.get("role") or "").strip()
        password = request.POST.get("password") or ""
        active = request.POST.get("is_active") == "on"
        typed = {"name": name, "username": username, "email": email,
                 "role": role, "is_active": active}

        if not name:
            errors.append("A name is needed — it is what everybody else sees.")

        # ---- the user ID -----------------------------------------------------
        # ⚠ SHORT, LIKE SAP. Saahil's model, and the right one: the people most
        #   likely to sign in from a phone at seven in the morning are the least
        #   likely to have a company email address.
        unchanged = person is not None and username == person.username

        if not username:
            errors.append("A user ID is needed: it is what they type to sign in.")
        elif not unchanged and not USERNAME_SHAPE.match(username):
            # ⚠ THE SHAPE IS CHECKED ONLY WHEN THE ID CHANGES, and that is not
            #   laziness. The superuser created before any of this exists as
            #   "S@@hil06" — an address-shaped ID that the rule below would now
            #   refuse. Enforcing it on save would mean the one account that can
            #   fix everything cannot edit its own name without being renamed
            #   first. New IDs follow the rule; old ones are left where they are.
            errors.append(
                "A user ID can hold letters, digits, a dot, a dash or an underscore — "
                "no spaces and no @.")
        elif User.objects.filter(username__iexact=username) \
                         .exclude(pk=person.pk if person else None).exists():
            # ⚠ CASE-INSENSITIVE. RAMESH and ramesh sign in as the same person,
            #   so they must not be two accounts.
            errors.append(f"{username} is already taken. User IDs are not case sensitive.")

        # ⚠ THE EMAIL IS OPTIONAL AND IS NOT A LOGIN. It is there for the day
        #   there is something to send; nobody signs in with it.
        if email and User.objects.filter(email__iexact=email) \
                                 .exclude(pk=person.pk if person else None).exists():
            errors.append(f"{email} is already on another account.")

        if role not in dict(Role.choices):
            errors.append("Choose a role.")

        # ---- the four safeguards ------------------------------------------
        editing_self = person is not None and person.pk == request.user.pk
        if editing_self and not active:
            # ⚠ 1. You cannot switch yourself off. The next screen you would
            #      see is the login page, and you would not get past it.
            errors.append("You cannot deactivate your own account.")
        if editing_self and role_of(request.user) is not None \
                and role != role_of(request.user):
            # ⚠ 2. Nor demote yourself out of the only role that can undo it.
            #
            # ⚠⚠ UNLESS YOU HAVE NO ROLE AT ALL — see `ANCHOR: BOOTSTRAP-ADMIN`.
            #    The reason above is about demotion, and somebody with no role
            #    has nothing to demote from. Without this condition the rule
            #    fired on the one person it was never written for: the superuser
            #    on a brand-new database, who was told "Ask another Admin" when
            #    the whole problem was that there wasn't one. Safeguards 1 and 3
            #    are untouched, so you still cannot switch yourself off and you
            #    still cannot remove the last Admin.
            errors.append("You cannot change your own role. Ask another Admin.")

        if person is not None and not errors:
            losing_admin = (role != Role.ADMIN or not active) and role_of(person) == Role.ADMIN
            if losing_admin:
                others = UserProfile.objects.filter(role=Role.ADMIN, user__is_active=True) \
                                            .exclude(user_id=person.pk).count()
                if others == 0:
                    # ⚠ 3. The last Admin standing. Nothing inside the app could
                    #      put this right afterwards — it would need a shell on
                    #      the server, which is exactly what a company with no IT
                    #      team does not have.
                    errors.append(
                        "This is the last active Admin. Make somebody else an Admin first.")

        if password:
            try:
                validate_password(password, user=person)
            except ValidationError as exc:
                errors.extend(exc.messages)
        elif person is None:
            errors.append("Set a first password — you will need to tell them what it is.")

        if not errors:
            first, _, last = name.partition(" ")
            if person is None:
                # ⚠ STORED EXACTLY AS TYPED, matched case-insensitively at
                #   login. So the house style can be SAP-ish capitals — RAMESH —
                #   without anybody having to find the shift key on a phone.
                person = User.objects.create_user(
                    username=username, email=email, password=password,
                    first_name=first, last_name=last)
                UserProfile.objects.create(
                    user=person, role=role, created_by=request.user,
                    must_change_password=True)
                record(person, UserEvent.Kind.CREATED, by=request.user,
                       detail=f"as {dict(Role.choices)[role]}")
                messages.success(
                    request,
                    f"{name} added as {dict(Role.choices)[role]}. Tell them the password — "
                    "they will be asked to change it the first time they sign in.")
            else:
                # ⚠ WHAT CHANGED IS WORKED OUT BEFORE ANYTHING IS WRITTEN.
                #   Afterwards the old values are gone and the history would
                #   have nothing to say.
                was_role = role_of(person)
                was_username = person.username
                was_active = person.is_active

                person.first_name, person.last_name = first, last
                person.email = email
                person.username = username
                person.is_active = active
                if password:
                    person.set_password(password)
                person.save()
                profile, _created = UserProfile.objects.get_or_create(user=person)
                profile.role = role
                if password:
                    # A reset is a new shared secret, so the clock starts again.
                    profile.must_change_password = True
                profile.save()

                labels = dict(Role.choices)
                if was_role != role:
                    record(person, UserEvent.Kind.ROLE, by=request.user,
                           detail=f"{labels.get(was_role, '—')} → {labels[role]}")
                if was_username != username:
                    record(person, UserEvent.Kind.RENAMED, by=request.user,
                           detail=f"{was_username} → {username}")
                if was_active != active:
                    record(person,
                           UserEvent.Kind.DEACTIVATED if not active else UserEvent.Kind.REACTIVATED,
                           by=request.user)
                if password:
                    record(person, UserEvent.Kind.PASSWORD, by=request.user)
                messages.success(
                    request,
                    f"{name} saved." + (" New password set — they will be asked to change it."
                                        if password else ""))
            return redirect("user_list")

        for message in errors:
            messages.error(request, message)

    return render(request, "accounts/user_form.html", {
        "person": person,
        "roles": Role.choices,
        "typed": typed,
        "current_role": typed.get("role") or (role_of(person) if person else ""),
        # ⚠ Used to grey the two boxes rather than to enforce anything — the
        #   POST above is where the refusal actually happens.
        "editing_self": person is not None and person.pk == request.user.pk,
        "display_name": _display_name(person) if person else "",
        # ⚠ select_related on `by`, or this is one query per row on a screen
        #   that will eventually hold years of them.
        "history": (person.events.select_related("by")[:50] if person else []),
    })


@require_POST
def user_reset_password(request, user_id):
    """
    Two clicks, from the list, when somebody rings up locked out.

    ⚠ THIS IS THE WHOLE POINT OF THE SCREEN. Before it existed the only way to
      reset a password was `manage.py changepassword` at a command line — which
      Saahil had to do himself, on the evening the login was built, to get back
      into his own system.

    ⚠ THE NEW PASSWORD IS SHOWN ONCE AND NEVER AGAIN. It is hashed the moment it
      is saved, so this screen is the only place it will ever be readable. The
      message says so, because somebody will otherwise expect to find it later.

    ⚠ AND IT IS READABLE ALOUD — `quarry-lantern-47`, not `Xk7#pQ2!`. The admin
      is going to say it down a phone to somebody on a site. See
      accounts/passwords.py.
    """
    denied = _admin_only(request)
    if denied:
        return denied

    person = get_object_or_404(User.objects.select_related("profile"), pk=user_id)
    fresh = readable_password()
    person.set_password(fresh)
    person.save(update_fields=["password"])

    profile, _created = UserProfile.objects.get_or_create(user=person)
    # Somebody else chose it, so it is temporary by definition.
    profile.must_change_password = True
    profile.save(update_fields=["must_change_password"])

    record(person, UserEvent.Kind.PASSWORD, by=request.user)
    messages.success(
        request,
        f"New password for {_display_name(person)} — {fresh}\n"
        f"Tell them now: this is the only time it can be shown, and they will be asked "
        f"to change it when they sign in.")
    return redirect("user_list")


@require_POST
def user_toggle_active(request, user_id):
    """
    Deactivate or reactivate from the list, without opening the form.

    ⚠ 4. THERE IS NO DELETE, HERE OR ANYWHERE. A person who leaves still
      approved purchase orders and uploaded documents last year; deleting the
      row would either orphan that history or cascade through it. Deactivating
      keeps every trace and stops the login, which is what "they have left"
      actually means.
    """
    denied = _admin_only(request)
    if denied:
        return denied

    person = get_object_or_404(User, pk=user_id)
    if person.pk == request.user.pk:
        messages.error(request, "You cannot deactivate your own account.")
        return redirect("user_list")

    if person.is_active and role_of(person) == Role.ADMIN:
        others = UserProfile.objects.filter(role=Role.ADMIN, user__is_active=True) \
                                    .exclude(user_id=person.pk).count()
        if others == 0:
            messages.error(request, "This is the last active Admin. Make somebody else an Admin first.")
            return redirect("user_list")

    person.is_active = not person.is_active
    person.save(update_fields=["is_active"])
    record(person,
           UserEvent.Kind.REACTIVATED if person.is_active else UserEvent.Kind.DEACTIVATED,
           by=request.user)
    messages.success(
        request,
        f"{_display_name(person)} {'reactivated' if person.is_active else 'deactivated'}.")
    return redirect("user_list")
