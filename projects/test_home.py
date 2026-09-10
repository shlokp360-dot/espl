"""
The home screen — every role gets one, and it stays cheap.

>>> ANCHOR: HOME-SCREEN <<<
"""
from django.test import TestCase
from django.urls import reverse

from accounts.models import Role
from accounts.testing import AuthedTestCase


class EveryRoleHasAHome(AuthedTestCase):
    def test_every_role_renders_the_launchpad(self):
        for role in Role.values:
            person = self.make_user(f"zq.{role}", role=role)
            self.client.force_login(person)
            response = self.client.get(reverse("launchpad"))
            self.assertEqual(response.status_code, 200, role)

    def test_a_site_engineer_sees_no_money_band(self):
        self.client.force_login(self.make_user("zq.site", role=Role.SITE))
        html = self.client.get(reverse("launchpad")).content.decode()
        self.assertNotIn("Committed this year", html)
        self.assertNotIn("Collected from buyers", html)

    def test_an_admin_sees_the_band_and_the_cards(self):
        html = self.client.get(reverse("launchpad")).content.decode()
        for text in ("Committed this year", "Purchase orders", "Sales", "Drawings"):
            self.assertIn(text, html)


class TheHomeStaysCheap(AuthedTestCase):
    """The page everybody loads first must not grow a query per row."""

    def test_query_count_is_bounded(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(reverse("launchpad"))
        self.assertLess(len(ctx.captured_queries), 45, len(ctx.captured_queries))
