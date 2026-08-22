"""
The three shared master screens, and the two faults found by walking through them.

>>> ANCHOR: MASTER-TABS <<<
⚠⚠ THESE TESTS EXIST BECAUSE A WALKTHROUGH FOUND THE BUGS AND A MARKDOWN FILE
   CANNOT GUARD THEM. Material groups, Vendor groups and Units of measure share
   one view and one save handler, so a fault in either is a fault in all three.

  B1  A row absent from the submitted form was DEACTIVATED, because an unticked
      checkbox and a missing checkbox look identical in an HTTP POST.
  B2  Material groups could not create a row at all — `MaterialGroup.name` is
      required by the model and the screen never offered a field for it.
"""
from django.urls import reverse

from accounts.models import Role
from accounts.testing import AuthedTestCase
from masters.models import MaterialGroup, UnitOfMeasure, VendorGroup


class ASaveNeverTouchesARowItWasNotShown(AuthedTestCase):
    """
    >>> ANCHOR: MASTER-TABS <<<
    ⚠⚠ THE FAULT: an unticked checkbox is not submitted at all, so "the user
       cleared this" and "this row was not on the form" arrive identically. The
       handler read every row in the table and set `is_active` from a key that
       was never going to be there, so any row missing from the form went
       inactive.

    ⚠ HOW IT HAPPENS IN REAL USE, and it is ordinary: two tabs open, or a row
      added in one window while another window still shows the older form.
      Saahil hit it live — `TRP` (Transport) went inactive during a walkthrough
      while a completely different row was being edited.

    ⚠ THE FIX IS A PER-ROW MARKER. Every rendered row carries a hidden
      `row-<id>` field. No marker, no opinion: the row is skipped entirely.
    """

    def setUp(self):
        super().setUp()
        self.kept = VendorGroup.objects.create(name="ZQ Kept Group", is_active=True)
        self.shown = VendorGroup.objects.create(name="ZQ Shown Group", is_active=True)

    def test_a_row_missing_from_the_post_is_left_alone(self):
        """The one that matters. Submit a form that never mentioned `kept`."""
        self.client.post(reverse("vendor_group_save"), {
            f"row-{self.shown.id}": "1",
            f"name-{self.shown.id}": self.shown.name,
            f"is_active-{self.shown.id}": "on",
        })
        self.kept.refresh_from_db()
        self.assertTrue(
            self.kept.is_active,
            "a row that was not on the submitted form was deactivated — B1")

    def test_unticking_a_row_that_was_shown_still_works(self):
        """
        ⚠ THE GUARD MUST NOT BREAK THE FEATURE. A row that WAS on the form and
          whose box was cleared must still deactivate, or the fix has simply
          made Active unusable.
        """
        self.client.post(reverse("vendor_group_save"), {
            f"row-{self.shown.id}": "1",
            f"name-{self.shown.id}": self.shown.name,
            # is_active deliberately absent — the user cleared it
            f"row-{self.kept.id}": "1",
            f"name-{self.kept.id}": self.kept.name,
            f"is_active-{self.kept.id}": "on",
        })
        self.shown.refresh_from_db()
        self.kept.refresh_from_db()
        self.assertFalse(self.shown.is_active, "clearing Active on a shown row must work")
        self.assertTrue(self.kept.is_active)

    def test_the_same_guard_protects_units_of_measure(self):
        """One handler, three screens — so the fault and the fix are shared."""
        kept = UnitOfMeasure.objects.create(code="ZQKEPT", name="Kept", is_active=True)
        shown = UnitOfMeasure.objects.create(code="ZQSHOWN", name="Shown", is_active=True)

        self.client.post(reverse("uom_save"), {
            f"row-{shown.id}": "1",
            f"code-{shown.id}": shown.code,
            f"name-{shown.id}": shown.name,
            f"is_active-{shown.id}": "on",
        })
        kept.refresh_from_db()
        self.assertTrue(kept.is_active, "units of measure share the fault — B1")


class MaterialGroupsCanBeCreatedFromTheirOwnScreen(AuthedTestCase):
    """
    >>> ANCHOR: MASTER-TABS <<<
    ⚠⚠ B2. `MaterialGroup.name` is a required field on the model, and the screen
       offered no input for it — so the blank bottom row could never validate and
       a group could not be created at all. The only route left was Django
       Admin, which contradicts the decision that master data is six entries and
       nothing opens Admin.

    ⚠ THE SIBLING SCREEN PROVED IT WAS AN OMISSION, not a design choice: Vendor
      groups uses `name` as its key field and shows it.
    """

    def test_a_new_group_can_be_added_with_a_code_and_a_name(self):
        before = MaterialGroup.objects.count()
        self.client.post(reverse("material_group_save"), {
            "new-code": "ZQG",
            "new-name": "ZQ Test Group",
        })
        self.assertEqual(MaterialGroup.objects.count(), before + 1,
                         "the blank row could not create a group — B2")
        fresh = MaterialGroup.objects.get(code="ZQG")
        self.assertEqual(fresh.name, "ZQ Test Group")

    def test_the_name_is_shown_and_editable_on_the_screen(self):
        group = MaterialGroup.objects.create(code="ZQH", name="ZQ Before")
        page = self.client.get(reverse("material_group_list"))
        self.assertContains(page, "ZQ Before")

        self.client.post(reverse("material_group_save"), {
            f"row-{group.id}": "1",
            f"code-{group.id}": group.code,
            f"name-{group.id}": "ZQ After",
            f"is_active-{group.id}": "on",
        })
        group.refresh_from_db()
        self.assertEqual(group.name, "ZQ After", "the name is not editable on screen — B2")


class TheScreensStayReachable(AuthedTestCase):
    """A cheap guard: all three render for an Admin and refuse a Site engineer."""

    def test_all_three_render(self):
        for name in ("material_group_list", "vendor_group_list", "uom_list"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_a_site_engineer_cannot_edit_them(self):
        self.client.force_login(self.make_user("zqsite1", role=Role.SITE))
        response = self.client.post(reverse("vendor_group_save"), {})
        self.assertEqual(response.status_code, 403)
