"""
Django Admin is not mounted, and must not come back.

>>> ANCHOR: NO-DJANGO-ADMIN <<<
Saahil, after seeing a raw Django screen during a walkthrough: "I don't want the
admin or any other user to ever access the Django screens. Everything has to be
interfaced with the UI that we have decided."

⚠⚠ THE REASON IS NOT TIDINESS. Django Admin walks past every rule this
   application exists to enforce: the activity rename that would silently zero a
   budget, the BOQ that locks at Won, the delete refused while something
   references it, the permission matrix, the vendor rate that may only be
   captured from an approved order. A screen that edits any table directly makes
   all of those advisory.

⚠ THESE TESTS ARE THE GUARD. Re-adding `path("admin/", admin.site.urls)` would
  be a one-line change that looks harmless in a diff, and would restore every
  bypass at once. It fails here instead.
"""
from django.test import TestCase
from django.urls import NoReverseMatch, reverse

from accounts.models import Role, UserProfile
from accounts.testing import AuthedTestCase


class ThereIsNoAdminUrl(TestCase):

    def test_the_admin_index_is_not_routed(self):
        self.assertEqual(self.client.get("/admin/").status_code, 404)

    def test_no_admin_table_is_reachable(self):
        """The addresses a curious superuser would actually type."""
        for path in ("/admin/masters/materialgroup/",
                     "/admin/masters/material/",
                     "/admin/masters/vendor/",
                     "/admin/projects/project/",
                     "/admin/auth/user/",
                     "/admin/masters/activity/",
                     "/admin/login/"):
            self.assertEqual(self.client.get(path).status_code, 404, path)

    def test_the_admin_namespace_cannot_be_reversed(self):
        """
        ⚠ THE STRUCTURAL CHECK, not a string one. If anybody re-registers the
          URLconf this starts resolving again and the test fails, whatever the
          paths above happen to be called at the time.
        """
        with self.assertRaises(NoReverseMatch):
            reverse("admin:index")


class NoScreenSendsAnybodyThere(AuthedTestCase):
    """
    ⚠ TWO LINKS EXISTED AND BOTH ARE GONE: the "Admin" item in the header for a
      superuser, and a "Open in Admin" link on the empty-BOM screen that told
      people to build their estimate there. A dead link to a 404 is worse than
      no link — it teaches somebody the address.
    """

    def setUp(self):
        super().setUp()
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])

    def test_the_header_offers_no_admin_link_even_to_a_superuser(self):
        page = self.client.get(reverse("launchpad")).content.decode()
        self.assertNotIn('href="/admin/', page)
        self.assertNotIn(">Admin<", page)

    def test_the_master_data_screens_do_not_link_out(self):
        for name in ("master_data", "material_group_list", "vendor_group_list", "uom_list"):
            page = self.client.get(reverse(name)).content.decode()
            self.assertNotIn("/admin/", page, name)


class TheForcedPasswordChangeHasNoBypass(AuthedTestCase):
    """
    >>> ANCHOR: NO-DJANGO-ADMIN <<<
    ⚠⚠ THE EXEMPTION THAT WENT WITH IT, AND IT WAS QUIETLY A HOLE. The
       must-change-password middleware skipped anything under /admin/, so
       somebody who had not yet chosen their own password — whose password is by
       definition still known to whoever set the account up — could reach every
       table in the database through it.
    """

    def test_somebody_who_must_change_their_password_is_redirected_everywhere(self):
        person = self.make_user("zqfresh", role=Role.ADMIN, must_change_password=True)
        self.client.force_login(person)

        for name in ("launchpad", "master_data", "project_list"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 302, name)
            self.assertIn(reverse("password_change"), response["Location"], name)

    def test_admin_is_not_a_way_round_it(self):
        """
        ⚠ TWO GUARDS, AND THE MIDDLEWARE GETS THERE FIRST. The URL does not
          exist, so the resolver would 404 it — but the middleware runs before
          the resolver and sends them to the password screen instead. That is
          the better answer of the two: a redirect to the thing they must do,
          rather than a dead end. What matters is that it is never a 200 and
          never a working table.
        """
        person = self.make_user("zqfresh2", role=Role.ADMIN, must_change_password=True)
        person.is_superuser = True
        person.save(update_fields=["is_superuser"])
        self.client.force_login(person)

        response = self.client.get("/admin/masters/material/")
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("password_change"), response["Location"])

        # And once the password IS chosen, it is still not there.
        profile = UserProfile.objects.get(user=person)
        profile.must_change_password = False
        profile.save(update_fields=["must_change_password"])
        self.assertEqual(self.client.get("/admin/masters/material/").status_code, 404)

    def test_the_password_screen_itself_stays_reachable(self):
        """The guard must not lock somebody out of the one screen they need."""
        person = self.make_user("zqfresh3", role=Role.ADMIN, must_change_password=True)
        self.client.force_login(person)
        self.assertEqual(self.client.get(reverse("password_change")).status_code, 200)
        self.assertEqual(
            UserProfile.objects.get(user=person).must_change_password, True)
