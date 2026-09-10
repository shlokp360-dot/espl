"""
The gate, the sign-in, and the Users screen.

⚠ THE FIRST TEST IS THE ONE THAT MATTERS. It walks every URL the application
  publishes and proves a logged-out visitor is turned away from all of them.
  Written that way on purpose: a test that lists ten screens by hand passes
  happily on the day somebody adds an eleventh and forgets.

⚠ THE LOGIN IS A USER ID, NOT AN EMAIL. Saahil's call — "keep login with
  username only", on the SAP model. An email is optional, is never asked for at
  the door, and exists for the day there is something to send.
"""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import URLPattern, URLResolver, get_resolver, reverse

from accounts.models import Role, UserProfile
from accounts.testing import AuthedTestCase

User = get_user_model()

# Addresses that must stay reachable without an account, or nobody can get one.
OPEN_TO_STRANGERS = {"login"}


def every_url_name():
    """
    Every named URL this project serves, with Django Admin left out.

    ⚠ Admin brings its own login and its own hundred URL names; including them
      would test Django rather than us.
    """
    names = []

    def walk(patterns, namespace=None):
        for entry in patterns:
            if isinstance(entry, URLResolver):
                ns = entry.namespace or namespace
                if ns == "admin":
                    continue
                walk(entry.url_patterns, ns)
            elif isinstance(entry, URLPattern) and entry.name:
                if namespace:
                    continue
                names.append(entry.name)

    walk(get_resolver().url_patterns)
    return sorted(set(names))


def try_reverse(name):
    """A URL for a name, guessing 1 for any argument it needs."""
    for args in ((), (1,), (1, 1), (1, 1, 1)):
        try:
            return reverse(name, args=args)
        except Exception:
            continue
    return None


class EveryScreenNeedsALogin(TestCase):
    def test_a_stranger_is_turned_away_from_every_address(self):
        checked = 0
        for name in every_url_name():
            if name in OPEN_TO_STRANGERS:
                continue
            url = try_reverse(name)
            if url is None:
                continue
            checked += 1
            response = self.client.get(url)
            self.assertEqual(
                response.status_code, 302,
                f"{name} ({url}) answered a logged-out visitor with {response.status_code}")
            self.assertTrue(
                response.url.startswith(settings.LOGIN_URL),
                f"{name} sent a stranger to {response.url} rather than the login page")
        # If the walk ever finds nothing, the test above passes for the wrong
        # reason. This is the tripwire for that.
        self.assertGreater(checked, 20, "the URL walk found almost nothing — it is broken")

    def test_the_login_page_itself_is_open(self):
        self.assertEqual(self.client.get(reverse("login")).status_code, 200)

    def test_the_login_page_asks_for_a_user_id_not_an_email(self):
        body = self.client.get(reverse("login")).content.decode()
        self.assertIn("User ID", body)
        self.assertNotIn('type="email"', body)

    def test_sessions_last_a_working_day(self):
        # 12 hours: long enough not to re-type at lunch, short enough that a
        # laptop left at the site office does not stay open all week.
        self.assertEqual(settings.SESSION_COOKIE_AGE, 12 * 60 * 60)


class SigningIn(AuthedTestCase):
    def setUp(self):
        super().setUp()
        self.client.logout()

    def post_login(self, username, password):
        return self.client.post(reverse("login"), {"username": username, "password": password})

    def test_the_user_id_is_the_login(self):
        response = self.post_login("admin", self.password)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("launchpad"))

    def test_capitals_do_not_matter(self):
        # SAP shows user IDs in capitals and a phone capitalises the first
        # letter by itself. Neither should look like a wrong password.
        self.assertEqual(self.post_login("ADMIN", self.password).status_code, 302)

    def test_a_wrong_password_says_nothing_useful(self):
        response = self.post_login("admin", "wrong-password")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "do not match an account")

    def test_an_unknown_user_id_gets_the_same_message(self):
        self.assertContains(self.post_login("nobody", "whatever"), "do not match an account")

    def test_a_deactivated_account_cannot_sign_in(self):
        self.make_user("leaver", role=Role.SITE, active=False)
        response = self.post_login("leaver", self.password)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_an_address_still_works_for_an_account_that_predates_the_rule(self):
        """
        ⚠ A COURTESY, NOT THE RULE. The superuser created before this app has an
          email and a username that is neither short nor SAP-shaped; it should
          not have to be re-taught.
        """
        legacy = User.objects.create_user(
            username="saahil", email="saahil@elegancesky.test", password=self.password)
        UserProfile.objects.create(user=legacy, role=Role.ADMIN, must_change_password=False)
        self.assertEqual(self.post_login("saahil@elegancesky.test", self.password).status_code, 302)
        self.client.logout()
        self.assertEqual(self.post_login("saahil", self.password).status_code, 302)


class TheFirstSignInForcesANewPassword(AuthedTestCase):
    def setUp(self):
        super().setUp()
        self.newcomer = self.make_user("newbie", role=Role.SITE, must_change_password=True)
        self.client.force_login(self.newcomer)

    def test_every_screen_redirects_until_the_password_is_changed(self):
        self.assertRedirects(self.client.get(reverse("launchpad")), reverse("password_change"))

    def test_the_password_screen_itself_is_reachable(self):
        self.assertEqual(self.client.get(reverse("password_change")).status_code, 200)

    def test_changing_it_clears_the_flag_and_opens_the_app(self):
        response = self.client.post(reverse("password_change"), {
            "old_password": self.password,
            "new_password1": "Gh7-quarry-lantern",
            "new_password2": "Gh7-quarry-lantern",
        })
        self.assertRedirects(response, reverse("launchpad"))
        self.newcomer.profile.refresh_from_db()
        self.assertFalse(self.newcomer.profile.must_change_password)
        self.assertEqual(self.client.get(reverse("launchpad")).status_code, 200)


class TheUsersScreen(AuthedTestCase):
    def add(self, **overrides):
        payload = {"name": "Ramesh Patel", "username": "ramesh", "email": "",
                   "role": Role.SITE, "password": "Gh7-quarry-lantern", "is_active": "on"}
        payload.update(overrides)
        return self.client.post(reverse("user_new"), payload)

    def test_it_is_listed_under_master_data(self):
        self.assertContains(self.client.get(reverse("master_data")), reverse("user_list"))

    def test_an_admin_can_add_somebody(self):
        self.assertRedirects(self.add(), reverse("user_list"))
        person = User.objects.get(username="ramesh")
        self.assertEqual(person.profile.role, Role.SITE)
        # They were given a password by somebody else, so they must replace it.
        self.assertTrue(person.profile.must_change_password)

    def test_an_email_is_optional(self):
        self.add()
        self.assertEqual(User.objects.get(username="ramesh").email, "")

    def test_the_new_account_can_actually_sign_in(self):
        self.add()
        self.client.logout()
        response = self.client.post(reverse("login"), {
            "username": "ramesh", "password": "Gh7-quarry-lantern"})
        self.assertEqual(response.status_code, 302)

    def test_two_accounts_cannot_share_a_user_id_even_in_different_capitals(self):
        self.add()
        self.add(name="Somebody Else", username="RAMESH")
        self.assertEqual(User.objects.filter(username__iexact="ramesh").count(), 1)

    def test_a_user_id_cannot_contain_a_space_or_an_at_sign(self):
        self.add(username="ramesh patel")
        self.add(username="ramesh@elegancesky.test")
        self.assertFalse(User.objects.filter(first_name="Ramesh").exists())

    def test_an_account_that_predates_the_rule_can_still_be_edited(self):
        """
        ⚠ THE REAL SUPERUSER IS "S@@hil06". The shape rule would refuse it, so
          saving that record without renaming it would be impossible — on the
          one account that can repair everything else. The shape is therefore
          checked only when the ID actually changes.
        """
        legacy = self.make_user("S@@hil06", role=Role.PURCHASE, name="Old Account")
        response = self.client.post(reverse("user_edit", args=[legacy.pk]), {
            "name": "Old Account", "username": "S@@hil06", "email": "",
            "role": Role.ACCOUNTANT, "password": "", "is_active": "on"})
        self.assertRedirects(response, reverse("user_list"))
        legacy.profile.refresh_from_db()
        self.assertEqual(legacy.profile.role, Role.ACCOUNTANT)

    def test_but_changing_it_to_a_bad_shape_is_still_refused(self):
        legacy = self.make_user("S@@hil06", role=Role.PURCHASE, name="Old Account")
        self.client.post(reverse("user_edit", args=[legacy.pk]), {
            "name": "Old Account", "username": "another@bad.one", "email": "",
            "role": Role.PURCHASE, "password": "", "is_active": "on"})
        legacy.refresh_from_db()
        self.assertEqual(legacy.username, "S@@hil06")

    def test_a_weak_password_is_refused(self):
        self.add(username="weak", password="12345678")
        self.assertFalse(User.objects.filter(username="weak").exists())

    def test_you_cannot_deactivate_yourself(self):
        response = self.client.post(reverse("user_toggle_active", args=[self.user.pk]))
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.assertContains(self.client.get(response.url), "cannot deactivate your own")

    def test_you_cannot_change_your_own_role(self):
        self.client.post(reverse("user_edit", args=[self.user.pk]), {
            "name": "Test Admin", "username": self.user.username, "email": "",
            "role": Role.SITE, "password": "", "is_active": "on"})
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.role, Role.ADMIN)

    def test_one_admin_of_two_can_be_demoted(self):
        other = self.make_user("second", role=Role.ADMIN, name="Second Admin")
        self.client.post(reverse("user_edit", args=[other.pk]), {
            "name": "Second Admin", "username": "second", "email": "",
            "role": Role.ACCOUNTANT, "password": "", "is_active": "on"})
        other.profile.refresh_from_db()
        self.assertEqual(other.profile.role, Role.ACCOUNTANT)

    def superuser_who_is_not_an_admin(self):
        """
        ⚠ THE ONLY WAY TO REACH THE LAST-ADMIN RULE.

        An Admin editing another Admin is, by definition, a second Admin — so
        the rule cannot fire. Editing yourself is stopped one rule earlier. What
        is left is a Django superuser whose ROLE is something else: they get
        past the door because of `is_superuser`, and they are the person who
        could otherwise demote the last Admin in the building.
        """
        boss = self.make_user("root", role=Role.SITE)
        boss.is_superuser = boss.is_staff = True
        boss.save(update_fields=["is_superuser", "is_staff"])
        return boss

    def test_the_last_admin_cannot_be_demoted(self):
        self.client.force_login(self.superuser_who_is_not_an_admin())
        self.client.post(reverse("user_edit", args=[self.user.pk]), {
            "name": "Test Admin", "username": self.user.username, "email": "",
            "role": Role.SITE, "password": "", "is_active": "on"})
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.role, Role.ADMIN)

    def test_the_last_active_admin_cannot_be_switched_off(self):
        self.client.force_login(self.superuser_who_is_not_an_admin())
        response = self.client.post(reverse("user_toggle_active", args=[self.user.pk]))
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.assertContains(self.client.get(response.url), "last active Admin")

    def test_deactivating_keeps_the_person_and_their_history(self):
        person = self.make_user("leaver", role=Role.PURCHASE)
        self.client.post(reverse("user_toggle_active", args=[person.pk]))
        person.refresh_from_db()
        self.assertFalse(person.is_active)
        self.assertTrue(User.objects.filter(pk=person.pk).exists())

    def test_a_site_engineer_cannot_open_the_users_screen(self):
        self.client.force_login(self.make_user("sitey", role=Role.SITE))
        self.assertEqual(self.client.get(reverse("user_list")).status_code, 403)
        self.assertEqual(self.client.get(reverse("user_new")).status_code, 403)


class TheStandingWarningIsGone(AuthedTestCase):
    def test_the_no_login_banner_has_been_removed(self):
        """
        ⚠ THIS TEST REPLACES ONE THAT ASSERTED THE OPPOSITE.

        The banner said "No login is required to reach these screens" and there
        were three tests keeping it on the page. It was true, it was important,
        and it is now false — leaving it up would train people to ignore the
        next warning that matters.
        """
        for name in ("launchpad", "project_list", "master_data"):
            body = self.client.get(reverse(name)).content.decode()
            self.assertNotIn("No login is required", body)

    def test_the_header_says_who_is_signed_in(self):
        body = self.client.get(reverse("launchpad")).content.decode()
        self.assertIn("Test Admin", body)
        self.assertIn(reverse("logout"), body)
