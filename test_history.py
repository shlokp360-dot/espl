"""
Commit 3: who did what, and the account history.

⚠ NO TEST HERE READS A PASSWORD, BECAUSE NOTHING CAN. What is asserted is that
  the EVENT was recorded — the question people actually ask months later is
  "who gave this person access", not "what was the password".
"""
from django.contrib.auth import get_user_model
from django.urls import reverse

from accounts.models import Role, UserEvent
from accounts.passwords import readable_password
from accounts.testing import AuthedTestCase

User = get_user_model()


class ResettingAPasswordFromTheList(AuthedTestCase):
    def setUp(self):
        super().setUp()
        self.person = self.make_user("ramesh", role=Role.SITE, name="Ramesh Patel")

    def test_it_sets_a_new_password_that_actually_works(self):
        response = self.client.post(reverse("user_reset_password", args=[self.person.pk]))
        self.assertRedirects(response, reverse("user_list"))

        # The password is in the message and nowhere else, ever again.
        shown = [m.message for m in response.wsgi_request._messages]
        fresh = shown[0].split("—")[1].split("\n")[0].strip()

        self.client.logout()
        signed_in = self.client.post(reverse("login"),
                                     {"username": "ramesh", "password": fresh})
        self.assertEqual(signed_in.status_code, 302)

    def test_the_old_password_stops_working_immediately(self):
        self.client.post(reverse("user_reset_password", args=[self.person.pk]))
        self.client.logout()
        response = self.client.post(reverse("login"),
                                    {"username": "ramesh", "password": self.password})
        self.assertEqual(response.status_code, 200)

    def test_they_must_change_it_at_the_next_sign_in(self):
        self.client.post(reverse("user_reset_password", args=[self.person.pk]))
        self.person.profile.refresh_from_db()
        self.assertTrue(self.person.profile.must_change_password)

    def test_the_reset_is_recorded_but_the_password_is_not(self):
        self.client.post(reverse("user_reset_password", args=[self.person.pk]))
        event = self.person.events.get()
        self.assertEqual(event.kind, UserEvent.Kind.PASSWORD)
        self.assertEqual(event.by, self.user)
        self.assertEqual(event.detail, "")     # ⚠ nothing secret is stored

    def test_you_cannot_reset_your_own_from_the_list(self):
        # The button is not drawn for yourself; this proves the row too.
        self.assertNotContains(self.client.get(reverse("user_list")),
                               reverse("user_reset_password", args=[self.user.pk]))

    def test_a_site_engineer_cannot_reset_anybody(self):
        self.client.force_login(self.make_user("sitey", role=Role.SITE))
        response = self.client.post(reverse("user_reset_password", args=[self.person.pk]))
        self.assertEqual(response.status_code, 403)


class ThePasswordIsReadableAloud(AuthedTestCase):
    def test_two_words_and_a_number(self):
        for _ in range(50):
            word_one, word_two, number = readable_password().split("-")
            self.assertNotEqual(word_one, word_two)
            self.assertGreaterEqual(len(word_one), 4)
            self.assertTrue(number.isdigit())
            # ⚠ Nothing that needs spelling out down a phone.
            self.assertTrue((word_one + word_two).isalpha())

    def test_it_is_not_the_same_twice(self):
        self.assertGreater(len({readable_password() for _ in range(50)}), 45)


class TheAccountHistory(AuthedTestCase):
    def add(self, **overrides):
        payload = {"name": "Ramesh Patel", "username": "ramesh", "email": "",
                   "role": Role.SITE, "password": "Gh7-quarry-lantern", "is_active": "on"}
        payload.update(overrides)
        return self.client.post(reverse("user_new"), payload)

    def test_creating_somebody_is_recorded_with_their_role(self):
        self.add()
        event = User.objects.get(username="ramesh").events.get()
        self.assertEqual(event.kind, UserEvent.Kind.CREATED)
        self.assertIn("Site engineer", event.detail)
        self.assertEqual(event.by, self.user)

    def test_a_role_change_records_both_sides(self):
        self.add()
        person = User.objects.get(username="ramesh")
        self.client.post(reverse("user_edit", args=[person.pk]), {
            "name": "Ramesh Patel", "username": "ramesh", "email": "",
            "role": Role.PURCHASE, "password": "", "is_active": "on"})
        event = person.events.filter(kind=UserEvent.Kind.ROLE).get()
        self.assertEqual(event.detail, "Site engineer → Purchase manager")

    def test_renaming_a_user_id_is_recorded(self):
        self.add()
        person = User.objects.get(username="ramesh")
        self.client.post(reverse("user_edit", args=[person.pk]), {
            "name": "Ramesh Patel", "username": "ramesh.patel", "email": "",
            "role": Role.SITE, "password": "", "is_active": "on"})
        self.assertEqual(person.events.filter(kind=UserEvent.Kind.RENAMED).get().detail,
                         "ramesh → ramesh.patel")

    def test_deactivating_and_reactivating_both_land(self):
        person = self.make_user("leaver", role=Role.PURCHASE)
        self.client.post(reverse("user_toggle_active", args=[person.pk]))
        self.client.post(reverse("user_toggle_active", args=[person.pk]))
        self.assertEqual(
            [e.kind for e in person.events.order_by("id")],
            [UserEvent.Kind.DEACTIVATED, UserEvent.Kind.REACTIVATED])

    def test_nothing_is_recorded_when_nothing_changed(self):
        self.add()
        person = User.objects.get(username="ramesh")
        person.events.all().delete()
        self.client.post(reverse("user_edit", args=[person.pk]), {
            "name": "Ramesh Patel", "username": "ramesh", "email": "",
            "role": Role.SITE, "password": "", "is_active": "on"})
        self.assertEqual(person.events.count(), 0)

    def test_the_history_is_on_the_user_screen(self):
        self.add()
        person = User.objects.get(username="ramesh")
        body = self.client.get(reverse("user_edit", args=[person.pk])).content.decode()
        self.assertIn("History", body)
        self.assertIn("Account created", body)

    def test_an_account_with_no_history_says_so_rather_than_showing_a_blank(self):
        body = self.client.get(reverse("user_edit", args=[self.user.pk])).content.decode()
        self.assertIn("predates the history", body)
