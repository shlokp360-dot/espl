"""
The first Admin on a brand-new database — `ANCHOR: BOOTSTRAP-ADMIN`.

⚠ THE BUG THESE EXIST FOR WAS FOUND BY BUILDING A REAL DATABASE, not by
  reading. On 16 Aug 2026 the PostgreSQL rehearsal reached a working
  installation that nobody could use: `createsuperuser` had made an account with
  no `UserProfile`, so the matrix answered "no role" to every screen, and with
  no Django Admin there was no way back in. It looked exactly like the
  application was broken.

⚠⚠ THE POINT OF THE RULE IS THE CONDITION, NOT THE GRANT. "This system has no
   Admin" and "this user is a superuser" are different rules, and the easy one
   is wrong — `perms.can()` deliberately refuses to let `is_superuser` satisfy a
   business rule. So the test that matters most is
   `test_a_second_superuser_gets_nothing_once_an_admin_exists`: it is the one
   that proves the door shut behind itself.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import (Role, UserEvent, UserProfile, ensure_bootstrap_admin,
                             role_of)

User = get_user_model()


class TheBootstrapGrant(TestCase):
    """The rule itself, called directly."""

    def test_a_superuser_on_a_virgin_system_becomes_admin(self):
        boss = User.objects.create_superuser(username="zqfirst", password="x", email="")
        self.assertIsNone(role_of(boss))

        self.assertTrue(ensure_bootstrap_admin(boss))
        self.assertEqual(UserProfile.objects.get(user=boss).role, Role.ADMIN)

    def test_a_second_superuser_gets_nothing_once_an_admin_exists(self):
        """⚠⚠ THE DOOR CLOSES BEHIND ITSELF. This is the whole design."""
        first = User.objects.create_superuser(username="zqfirst", password="x", email="")
        ensure_bootstrap_admin(first)

        later = User.objects.create_superuser(username="zqlater", password="x", email="")
        self.assertFalse(ensure_bootstrap_admin(later))
        self.assertIsNone(role_of(later))

    def test_an_ordinary_user_never_gets_it_even_with_no_admin_anywhere(self):
        # ⚠ A person with no role on a system with no Admin is the exact shape
        #   of the bootstrap case, and they still get nothing — because they
        #   cannot reach a shell, which is the only thing that made the
        #   superuser trustworthy here.
        person = User.objects.create_user(username="zqplain", password="x")
        self.assertFalse(ensure_bootstrap_admin(person))
        self.assertIsNone(role_of(person))

    def test_it_does_not_touch_a_superuser_who_already_has_a_role(self):
        boss = User.objects.create_superuser(username="zqsite", password="x", email="")
        UserProfile.objects.create(user=boss, role=Role.SITE)

        self.assertFalse(ensure_bootstrap_admin(boss))
        self.assertEqual(role_of(boss), Role.SITE, "a deliberate role was overwritten")

    def test_a_deactivated_admin_does_not_hold_the_door_shut(self):
        """
        ⚠ THE SAME PREDICATE AS SAFEGUARD 3 — `role=ADMIN, user__is_active=True`.
          If every Admin is switched off the installation is just as unusable as
          an empty one, and the two rules have to agree about that or the screen
          would refuse to remove the last Admin while this decided there was not
          one.
        """
        gone = User.objects.create_user(username="zqgone", password="x", is_active=False)
        UserProfile.objects.create(user=gone, role=Role.ADMIN)

        boss = User.objects.create_superuser(username="zqfirst", password="x", email="")
        self.assertTrue(ensure_bootstrap_admin(boss))

    def test_the_grant_is_written_into_the_history(self):
        """⚠ A privilege that appears with nothing behind it cannot be told apart
           from one somebody granted themselves."""
        boss = User.objects.create_superuser(username="zqfirst", password="x", email="")
        ensure_bootstrap_admin(boss)

        event = UserEvent.objects.get(user=boss, kind=UserEvent.Kind.ROLE)
        self.assertIsNone(event.by, "the system did it, not a person")
        self.assertIn("no active Admin", event.detail)

    def test_the_new_admin_is_not_asked_to_change_their_password(self):
        # They typed it into createsuperuser themselves; nobody else ever knew it.
        boss = User.objects.create_superuser(username="zqfirst", password="x", email="")
        ensure_bootstrap_admin(boss)
        self.assertFalse(UserProfile.objects.get(user=boss).must_change_password)

    def test_the_profile_is_usable_on_the_object_already_in_memory(self):
        """
        ⚠⚠ DJANGO CACHES THE *ABSENCE* OF A REVERSE ONE-TO-ONE. `role_of()` looks
           for the profile before the grant, which stores "there isn't one"
           against that in-memory user — so without the fix every later
           `user.profile` in the same request still finds nothing and the grant
           silently does not take effect for the rest of the page.
        """
        boss = User.objects.create_superuser(username="zqfirst", password="x", email="")
        ensure_bootstrap_admin(boss)
        self.assertEqual(role_of(boss), Role.ADMIN)


class TheSystemRepairsItselfOnARequest(TestCase):
    """End to end, which is how it will actually happen."""

    def test_signing_in_on_a_new_installation_opens_the_app(self):
        User.objects.create_superuser(username="zqfirst", password="pw-zq-12345", email="")
        self.client.login(username="zqfirst", password="pw-zq-12345")

        response = self.client.get(reverse("launchpad"), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(UserProfile.objects.get(user__username="zqfirst").role,
                         Role.ADMIN)

    def test_it_says_so_rather_than_doing_it_quietly(self):
        User.objects.create_superuser(username="zqfirst", password="pw-zq-12345", email="")
        self.client.login(username="zqfirst", password="pw-zq-12345")

        response = self.client.get(reverse("launchpad"), follow=True)
        self.assertContains(response, "made an Admin")

    def test_an_admin_screen_is_reachable_afterwards(self):
        # ⚠ The launchpad answering is not the same as the tiles opening — that
        #   was the actual complaint: "it shows my role doesn't have that
        #   authorization".
        User.objects.create_superuser(username="zqfirst", password="pw-zq-12345", email="")
        self.client.login(username="zqfirst", password="pw-zq-12345")
        self.client.get(reverse("launchpad"))

        self.assertEqual(self.client.get(reverse("analytics_home")).status_code, 200)


class TheSelfRoleSafeguard(TestCase):
    """Safeguard 2 — relaxed for one case and unchanged for every other."""

    def setUp(self):
        self.admin = User.objects.create_user(username="zqadmin", password="pw-zq-12345")
        UserProfile.objects.create(user=self.admin, role=Role.ADMIN,
                                   must_change_password=False)

    def _post(self, person, role):
        return self.client.post(reverse("user_edit", args=[person.pk]), {
            "username": person.get_username(),
            "name": person.get_full_name() or person.get_username(),
            "email": "",
            "role": role,
            "is_active": "on",
        }, follow=True)

    def test_an_admin_still_cannot_change_their_own_role(self):
        # ⚠ The original rule, and it must keep working — a second Admin exists
        #   so safeguard 3 is not what is refusing this.
        other = User.objects.create_user(username="zqadmin2", password="x")
        UserProfile.objects.create(user=other, role=Role.ADMIN)

        self.client.login(username="zqadmin", password="pw-zq-12345")
        response = self._post(self.admin, Role.PURCHASE)

        self.assertContains(response, "cannot change your own role")
        self.assertEqual(role_of(self.admin), Role.ADMIN)

    def test_a_role_less_superuser_may_now_give_themselves_a_role(self):
        """
        ⚠ THE RELAXATION, AND THE ONLY CASE IT COVERS. This superuser gets no
          bootstrap grant — `self.admin` already holds Admin, so the door is
          shut — and they can still reach the Users screen through the escape in
          `_admin_only`. Before this change safeguard 2 refused them too, with
          "Ask another Admin", which was the advice that led nowhere.
        """
        boss = User.objects.create_superuser(username="zqsuper", password="pw-zq-12345",
                                             email="")
        self.assertIsNone(role_of(boss), "the bootstrap door should be shut here")

        self.client.force_login(boss)
        self._post(boss, Role.ADMIN)

        self.assertEqual(role_of(User.objects.get(pk=boss.pk)), Role.ADMIN)

    def test_the_last_admin_safeguard_is_untouched(self):
        """
        ⚠ SAFEGUARD 3 STILL REFUSES, and this reaches it the only way anybody
          can: a role-less superuser, who is exempt from safeguard 2 now, trying
          to demote the one remaining Admin. If the relaxation had been written
          any wider than "the person editing has no role", this is where it
          would show.
        """
        boss = User.objects.create_superuser(username="zqsuper", password="pw-zq-12345",
                                             email="")
        self.client.force_login(boss)

        response = self._post(self.admin, Role.SITE)

        self.assertContains(response, "last active Admin")
        self.assertEqual(role_of(User.objects.get(pk=self.admin.pk)), Role.ADMIN)
