"""
The first sign-in must end in a new password — and on a brand-new database, the
first sign-in must also be able to reach something.

WHY
    The admin types the first password and tells the person what it is. Until
    they change it, two people know it — and on a site where the same phrase
    gets reused for the next three hires, it stays known. This middleware makes
    that state last exactly one sign-in.

⚠ IT MUST NOT TRAP ANYBODY. The password-change screen, the logout button and
    the login page itself are all reachable while the flag is set, or the only
    thing a new user can do is sit on a redirect loop and telephone Saahil.

⚠⚠ AND THE SAME IS TRUE OF THE FIRST ADMIN — see `ANCHOR: BOOTSTRAP-ADMIN`. The
    rule lives in `accounts.models` where it can be read next to the roles it
    grants; this only calls it, because a request is the earliest moment the
    application knows who somebody is.
"""
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse

from accounts.models import ensure_bootstrap_admin


class ForcePasswordChangeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            # ⚠ BEFORE the password check, not after: the grant writes a profile
            #   row, and the check on the next line reads one. Ordering them the
            #   other way would make the very first request after a bootstrap
            #   see a profile that did not exist when it was fetched.
            if ensure_bootstrap_admin(user):
                messages.info(
                    request,
                    "You have been made an Admin, because this system had none. "
                    "It happens once, on a new installation, and it is recorded "
                    "against your account.")
            profile = getattr(user, "profile", None)
            if profile is not None and profile.must_change_password:
                allowed = {
                    reverse("password_change"),
                    reverse("logout"),
                    reverse("login"),
                }
                # >>> ANCHOR: NO-DJANGO-ADMIN <<<
                # ⚠⚠ THE /admin/ EXEMPTION WAS REMOVED WITH ADMIN ITSELF, and it
                #    was quietly a hole: somebody who had not yet chosen their
                #    own password — whose password is by definition known to
                #    whoever set the account up — could still reach every table
                #    in the database through it. The exemption existed to avoid
                #    locking a half-set-up account out of the emergency exit;
                #    the emergency exit is now `manage.py shell` on the server,
                #    which no browser can reach.
                if request.path not in allowed:
                    messages.info(
                        request,
                        "Choose your own password before going any further — "
                        "the one you were given is known to somebody else.")
                    return redirect("password_change")
        return self.get_response(request)
