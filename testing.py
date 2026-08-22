"""
The base every existing test now sits on.

⚠ WHY THIS, AND NOT AN EXEMPTION FOR OLD TESTS
    The alternative was a setting that let the existing 381 tests keep browsing
    anonymously. It is faster by an hour and wrong for as long as the project
    lives: the suite would be testing an application that no longer exists, and
    the first thing anybody would notice is a screen that works in the tests and
    403s on the laptop.

    So every test signs in, exactly as every human now must. What the suite
    tests does not change; the door it comes through does.

⚠ THE ADMIN ROLE IS DELIBERATE. These tests were written to exercise screens,
    not permissions, so they run as the role that can reach everything. The
    tests that prove a Site engineer CANNOT reach the BOM belong with the
    matrix, in the next commit, and they are written from the matrix rather than
    inherited from here.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import Role, UserProfile


class AuthedTestCase(TestCase):
    """A signed-in Admin, and a client that stays signed in."""

    #: Handy for a test that needs a second person to exist.
    password = "not-a-real-password-42"

    def setUp(self):
        super().setUp()
        self.user = self.make_user("admin", role=Role.ADMIN, name="Test Admin")
        self.client.force_login(self.user)

    def make_user(self, username, role=Role.SITE, name="Somebody Else", active=True,
                  must_change_password=False, email=""):
        """
        ⚠ THE FIRST ARGUMENT IS THE USER ID, NOT AN EMAIL. Saahil chose a short
          SAP-style login — "keep login with username only" — and the email is
          an optional extra that nobody signs in with.

        ⚠ `force_login` skips the password, so tests do not depend on the hasher
          — but a test that wants to prove the login form works uses this
          password and posts it like a person would.
        """
        User = get_user_model()
        first, _, last = name.partition(" ")
        user = User.objects.create_user(
            username=username, email=email, password=self.password,
            first_name=first, last_name=last, is_active=active)
        UserProfile.objects.update_or_create(
            user=user,
            defaults={"role": role, "must_change_password": must_change_password})
        return user
