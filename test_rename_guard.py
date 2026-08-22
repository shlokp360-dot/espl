"""
Renaming a construction activity, and why it cannot happen.

>>> ANCHOR: ACTIVITY-RENAME-BLOCKED <<<
An estimate line copies the activity's NAME when it is created, and the reserve
is found again by matching that name back. Rename the activity and every line
carrying the old spelling loses its budget — silently, on live projects.

⚠⚠ THIS WAS A CONVENTION, NOT A RULE, AND NOBODY KNEW. The Company rates screen
   did not show the name field; that was the entire protection. Django Admin
   renamed activities happily. Saahil believed it was already blocked —
   "Renaming is not possible. If an activity is created, it stays" — and he was
   describing the intent, not the code.

⚠ THE GUARD IS IN THE MODEL, so Admin obeys it. A rule enforced only in a view
  leaves the one route that could do the damage unguarded.
"""
from decimal import Decimal as D

from django.core.exceptions import ValidationError
from django.test import TestCase

from masters.models import Activity
from projects.models import Estimate, EstimateLine, Project


class AnActivityNameCannotChangeOnceQuoted(TestCase):

    @classmethod
    def setUpTestData(cls):
        # ⚠ BUG 19 — migration 0003 seeds the real activity master, so RCC, PLM
        #   and sixteen others are taken before a test starts. ZQ* never will be.
        cls.used = Activity.objects.create(abbreviation="ZQR", name="Quoted trade",
                                           rate=D("100"), sort_order=910)
        cls.unused = Activity.objects.create(abbreviation="ZQU", name="Unquoted trade",
                                             rate=D("100"), sort_order=911)
        cls.project = Project.objects.create(name="Rename site", bua_sqft=D("1000"))
        estimate = Estimate.objects.create(project=cls.project)
        EstimateLine.objects.create(estimate=estimate, name="Quoted trade", rate=D("100"))

    def test_a_rename_is_refused_while_an_estimate_carries_the_name(self):
        self.used.name = "Something else"
        with self.assertRaises(ValidationError) as refused:
            self.used.full_clean()
        self.assertIn("name", refused.exception.message_dict)

    def test_the_refusal_names_the_alternative(self):
        """
        ⚠ A REFUSAL WITH A NAMED ALTERNATIVE, never a bare "not allowed" — the
          same shape as UnitOfMeasure's. Somebody stopped by this needs to know
          that deactivating is the way out.
        """
        self.used.name = "Something else"
        with self.assertRaises(ValidationError) as refused:
            self.used.full_clean()
        message = refused.exception.message_dict["name"][0]
        self.assertIn("Active", message)
        self.assertIn("1 estimate line", message)

    def test_an_unquoted_activity_may_still_be_renamed(self):
        """⚠ THE GUARD IS ABOUT THE DAMAGE, NOT ABOUT THE FIELD. A name nothing
        has copied is free to change; a typo caught the same day must be fixable."""
        self.unused.name = "Corrected spelling"
        self.unused.full_clean()
        self.unused.save()
        self.unused.refresh_from_db()
        self.assertEqual(self.unused.name, "Corrected spelling")

    def test_everything_else_on_a_quoted_activity_still_changes(self):
        """The rate is the whole reason this screen exists. Only the name locks."""
        self.used.rate = D("250")
        self.used.gst_percent = D("12")
        self.used.is_active = False
        self.used.full_clean()
        self.used.save()
        self.used.refresh_from_db()
        self.assertEqual(self.used.rate, D("250"))
        self.assertFalse(self.used.is_active)

    def test_saving_without_changing_the_name_is_not_refused(self):
        """⚠ THE GUARD COMPARES AGAINST WHAT IS IN THE DATABASE, not against a
        flag. Re-saving an untouched record must not trip it."""
        self.used.full_clean()
        self.used.save()

    def test_a_new_activity_is_never_blocked(self):
        fresh = Activity(abbreviation="ZQV", name="Brand new", rate=D("100"))
        fresh.full_clean()

    def test_the_count_is_taken_against_the_old_name(self):
        """
        ⚠ THE SUBTLE WAY THIS COULD HAVE BEEN WRONG. Counting lines matching the
          NEW name would find none and let every rename through — the check has
          to ask how many lines carry the spelling that is about to disappear.
        """
        self.assertEqual(self.used.estimates_using_the_name, 1)
        self.used.name = "A name no estimate has ever used"
        with self.assertRaises(ValidationError):
            self.used.full_clean()

    def test_deactivating_is_the_route_out(self):
        """What the refusal tells them to do has to actually work."""
        self.used.is_active = False
        self.used.full_clean()
        self.used.save()
        self.assertFalse(Activity.objects.get(pk=self.used.pk).is_active)
        # and the estimate line keeps its reserve
        self.assertEqual(EstimateLine.objects.filter(name="Quoted trade").count(), 1)
