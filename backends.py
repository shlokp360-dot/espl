"""
Signing in with a username.

⚠ WHY THIS EXISTS AT ALL, NOW THAT THE LOGIN IS A USERNAME
    Django's own backend would already accept it — but exactly. `username`
    lookups are case-sensitive on PostgreSQL, and a phone that capitalises the
    first letter turns RAMESH, Ramesh and ramesh into three different accounts,
    two of which do not exist. To the person typing, that is indistinguishable
    from a wrong password.

    Saahil's model is SAP: a short user ID. SAP shows those in capitals, so the
    admin is free to create RAMESH if that is the house style — this backend
    matches whatever they type against however it was stored, and the Users
    screen refuses two accounts whose IDs differ only by case.

⚠ AN EMAIL STILL WORKS, AS A COURTESY AND NOT AS THE RULE. Accounts created
    before this change hold an address in the username column, and the superuser
    that predates the whole app has one in its email field. Neither should have
    to be re-taught. Nothing on screen invites it.

⚠ IT REFUSES AMBIGUITY RATHER THAN GUESSING. If two accounts somehow share a
    login, this returns nobody instead of picking one.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class LoginBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        typed = (username or "").strip()
        if not typed or password is None:
            return None

        User = get_user_model()

        matches = list(User.objects.filter(username__iexact=typed)[:2])
        if not matches:
            # The courtesy fallback: an address, for accounts that predate the
            # username rule.
            matches = list(User.objects.filter(email__iexact=typed)[:2])

        if len(matches) != 1:
            # ⚠ Nobody, or more than one. Run the hasher anyway so a wrong
            #   username and a wrong password take the same time to fail —
            #   otherwise the login form quietly reports which accounts exist.
            User().set_password(password)
            return None

        user = matches[0]
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None

    def get_user(self, user_id):
        """
        The user for a session — WITH THE PROFILE ALREADY ATTACHED.

        ⚠ THIS IS A QUERY PER REQUEST, FOR EVERY REQUEST, AND IT SHOWED UP THE
          MOMENT IT WAS WRITTEN. Two screens assert how many queries they cost —
          the document register and the project list — and both jumped by three
          the first time the suite ran behind a login: the session, the user, and
          a profile lookup from the middleware asking whether this person still
          has to change their password.

          Session and user are Django's and unavoidable. The third is ours, and
          `select_related` folds it into the second. The permission layer reads
          the role on every request too, so this one join pays for that as well.

        ⚠ AND IT IS A JOIN RATHER THAN A CACHE ON PURPOSE. Keeping the role in
          the session would be cheaper still and would mean that demoting
          somebody did nothing until they next signed in — a permission change
          that quietly does not apply is worse than a query.
        """
        User = get_user_model()
        try:
            user = User.objects.select_related("profile").get(pk=user_id)
        except User.DoesNotExist:
            return None
        return user if self.user_can_authenticate(user) else None
