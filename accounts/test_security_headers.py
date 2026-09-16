"""
The two headers that must be on every response — nosniff especially, because
it is what stops a browser MIME-sniffing the one place the app renders an
uploaded file in a tab (compliance.views.view_inline). Set unconditionally in
config/settings.py so they hold in dev and under test, not only in production.
"""
from django.test import TestCase
from django.urls import reverse

from accounts.testing import AuthedTestCase


class EveryResponseCarriesTheHeaders(AuthedTestCase):
    def test_a_normal_page_has_nosniff_and_deny(self):
        response = self.client.get(reverse("launchpad"))
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
