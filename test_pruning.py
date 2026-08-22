"""
A project dropping a checklist line it does not need.

>>> ANCHOR: COMPLIANCE-PRUNING <<<
Saahil, on the built app: he deactivated a line in the master and it vanished
from every project at once. There were only two states — an item belonged to
every project, or to exactly one — and neither of them can say "not applicable to
THIS site" while leaving the line in place everywhere else.

⚠⚠ THE TYPE-LEVEL TICK IS NOT TOUCHED AND THESE TESTS SAY SO. He was explicit:
   "I like that option of RERA applicable or any other compliance of applicable,
   and then based on that checkbox, it loads at the bottom. So please keep that."
   Ticking a regime still loads all of its items. The change is one level down.

⚠ THE THREE SCREENS MUST AGREE. The project screen, the Overview and the Expiry
  timeline all read the same funnel, so a removed line has to leave the rows, the
  counts and the timeline together. A pruned line still counted on the Overview
  would be a screen contradicting another screen, which is how nobody trusts
  either.
"""
from datetime import date, timedelta
from decimal import Decimal as D

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.html import escape

from accounts.models import Role
from accounts.testing import AuthedTestCase
from compliance.models import (
    ComplianceDocument, ComplianceItem, ComplianceTitle, ComplianceType, Kind,
    ProjectCompliance, ProjectComplianceItem, removed_item_ids,
)
from projects.models import Project

import tempfile

MEDIA = tempfile.mkdtemp()


class PruningFixture(AuthedTestCase):
    """Two Won sites, one regime that applies to both, three lines under it."""

    def setUp(self):
        super().setUp()
        self.type = ComplianceType.objects.create(
            code="ZQC", name="Test regime", applies_to_every_project=True)
        self.title = ComplianceTitle.objects.create(type=self.type, name="Permissions")
        self.lake = ComplianceItem.objects.create(
            title=self.title, name="Lake margin NOC", kind=Kind.ONE, sort_order=1)
        self.plinth = ComplianceItem.objects.create(
            title=self.title, name="Plinth checking certificate", kind=Kind.ONE, sort_order=2)
        self.fire = ComplianceItem.objects.create(
            title=self.title, name="Fire NOC", kind=Kind.ONE, sort_order=3)

        self.site = Project.objects.create(name="Bhudarpura", bua_sqft=D("10000"),
                                           status=Project.Status.WON)
        self.other = Project.objects.create(name="Chandranagar", bua_sqft=D("8000"),
                                            status=Project.Status.WON)

    def screen(self, project=None):
        return self.client.get(
            reverse("compliance_project", args=[(project or self.site).pk])).content.decode()

    def remove(self, item, project=None, **extra):
        return self.client.post(
            reverse("compliance_remove_item", args=[(project or self.site).pk, item.pk]),
            extra, follow=True)

    def restore(self, item, project=None):
        return self.client.post(
            reverse("compliance_restore_item", args=[(project or self.site).pk, item.pk]),
            follow=True)


class AProjectStartsWithEverything(PruningFixture):

    def test_a_fresh_project_shows_every_line(self):
        """
        ⚠ NO ROWS MEANS NOTHING HAS BEEN REMOVED. The project starts full and is
          pruned — his words — which is why this table records removals rather
          than selections. A selection table would have shown an empty checklist
          here until somebody backfilled it.
        """
        page = self.screen()

        for item in (self.lake, self.plinth, self.fire):
            self.assertIn(escape(item.name), page)

    def test_nothing_is_written_until_something_is_removed(self):
        self.screen()

        self.assertEqual(ProjectComplianceItem.objects.count(), 0)

    def test_a_new_master_line_reaches_projects_that_already_exist(self):
        """
        The original reason `applies_to_every_project` exists: a new municipal
        rule must land on live sites, not only on future ones. Absence already
        means included, so there is nothing to fan out and nothing to miss.
        """
        self.remove(self.lake)
        fresh = ComplianceItem.objects.create(
            title=self.title, name="New municipal circular", kind=Kind.ONE, sort_order=4)

        self.assertIn(escape(fresh.name), self.screen())


class RemovingALine(PruningFixture):

    def test_it_leaves_the_project_screen(self):
        self.remove(self.lake)

        page = self.screen()
        self.assertNotIn(escape(self.lake.name), page.split("Removed from this project")[0])

    def test_it_leaves_the_overview_counts_too(self):
        """
        ⚠ THE ONE THAT WOULD ROT QUIETLY. If pruning were applied on the project
          screen instead of in the shared funnel, the Overview would keep counting
          a line the project no longer shows, and the two screens would disagree
          with nobody able to say which was right.
        """
        before = self.client.get(reverse("compliance_home")).content.decode()
        self.remove(self.lake)
        after = self.client.get(reverse("compliance_home")).content.decode()

        self.assertNotEqual(before, after)
        self.assertNotIn(escape(self.lake.name), after)

    def test_it_leaves_the_expiry_timeline(self):
        valid = ComplianceItem.objects.create(
            title=self.title, name="Labour licence", kind=Kind.VALID, validity_days=365)
        ComplianceDocument.objects.create(
            project=self.site, item=valid, original_name="licence.pdf",
            file="compliance/x.pdf", expires_on=date.today() + timedelta(days=30),
            uploaded_by=self.user)

        self.assertIn(escape(valid.name),
                      self.client.get(reverse("compliance_timeline")).content.decode())

        ProjectComplianceItem.objects.create(project=self.site, item=valid,
                                             removed_by=self.user)

        self.assertNotIn(escape(valid.name),
                         self.client.get(reverse("compliance_timeline")).content.decode())

    def test_every_other_project_is_untouched(self):
        """
        ⚠ THE WHOLE POINT. Deactivating in the master was already possible and is
          exactly what removed the line from all of his sites at once.
        """
        self.remove(self.lake)

        self.assertIn(escape(self.lake.name), self.screen(self.other))

    def test_the_master_is_untouched(self):
        self.remove(self.lake)

        self.lake.refresh_from_db()
        self.assertTrue(self.lake.is_active)

    def test_it_records_who_and_when(self):
        self.remove(self.lake, reason="No water body on this plot")

        row = ProjectComplianceItem.objects.get(project=self.site, item=self.lake)
        self.assertEqual(row.removed_by, self.user)
        self.assertEqual(row.reason, "No water body on this plot")

    def test_removing_it_twice_is_harmless(self):
        self.remove(self.lake)
        self.remove(self.lake)

        self.assertEqual(ProjectComplianceItem.objects.filter(project=self.site).count(), 1)


@override_settings(MEDIA_ROOT=MEDIA)
class ALineHoldingPaperCannotBeRemoved(PruningFixture):
    """
    ⚠⚠ IT MUST NEVER ORPHAN FILED PAPER. Removal is for lines that were never
       applicable to the site — a lake NOC on a plot with no lake. A line somebody
       has already filed a certificate against is a different situation, and this
       module exists to keep that evidence findable years later.
    """

    def setUp(self):
        super().setUp()
        ComplianceDocument.objects.create(
            project=self.site, item=self.plinth, original_name="plinth.pdf",
            file=SimpleUploadedFile("plinth.pdf", b"%PDF-1.4", content_type="application/pdf"),
            uploaded_by=self.user)

    def test_it_is_refused(self):
        self.remove(self.plinth)

        self.assertFalse(ProjectComplianceItem.objects.filter(item=self.plinth).exists())

    def test_the_refusal_says_how_many(self):
        page = self.remove(self.plinth).content.decode()

        self.assertIn("holds 1 document", page)

    def test_and_the_line_is_still_there(self):
        self.remove(self.plinth)

        self.assertIn(escape(self.plinth.name), self.screen())

    def test_the_button_is_not_offered_in_the_first_place(self):
        """A button that always refuses is not a button. The server refuses anyway."""
        page = self.screen()

        remove_url = reverse("compliance_remove_item", args=[self.site.pk, self.plinth.pk])
        self.assertNotIn(remove_url, page)


class PuttingALineBack(PruningFixture):

    def test_it_returns_to_the_checklist(self):
        self.remove(self.lake)
        self.restore(self.lake)

        self.assertIn(escape(self.lake.name),
                      self.screen().split("Removed from this project")[0])

    def test_the_removal_row_is_gone(self):
        self.remove(self.lake)
        self.restore(self.lake)

        self.assertFalse(ProjectComplianceItem.objects.filter(item=self.lake).exists())

    def test_removed_lines_are_listed_so_they_can_be_found(self):
        self.remove(self.lake)

        self.assertIn("Removed from this project", self.screen())

    def test_the_panel_is_absent_when_nothing_has_been_removed(self):
        """An empty panel on every project is the space he objected to."""
        self.assertNotIn("Removed from this project", self.screen())


class TheTypeLevelTickStillBehaves(PruningFixture):
    """
    ⚠⚠ HE ASKED FOR THIS TO BE LEFT ALONE IN SO MANY WORDS. These tests are here
       so a later change to pruning cannot quietly take it with it.
    """

    def setUp(self):
        super().setUp()
        self.optional = ComplianceType.objects.create(
            code="ZQO", name="Optional regime", applies_to_every_project=False)
        title = ComplianceTitle.objects.create(type=self.optional, name="Registration")
        self.item = ComplianceItem.objects.create(title=title, name="Registration certificate")

    def test_an_untitled_regime_shows_nothing(self):
        self.assertNotIn(escape(self.item.name), self.screen())

    def test_ticking_it_loads_all_of_its_items(self):
        ProjectCompliance.objects.create(project=self.site, type=self.optional, applicable=True)

        self.assertIn(escape(self.item.name), self.screen())

    def test_pruning_a_line_does_not_turn_the_regime_off(self):
        ProjectCompliance.objects.create(project=self.site, type=self.optional, applicable=True)
        self.remove(self.item)

        row = ProjectCompliance.objects.get(project=self.site, type=self.optional)
        self.assertTrue(row.applicable)


class WhoMayPrune(PruningFixture):
    """
    ⚠ `compliance.master`, NOT `compliance.upload`. Pruning changes what the
      project is judged against — it moves the denominator on the Overview — so
      it sits with the people who own the checklist rather than everyone who can
      file a certificate. One line in the matrix if that proves too narrow.
    """

    def test_an_accountant_cannot_prune(self):
        self.client.force_login(self.make_user("acc.person", role=Role.ACCOUNTANT))

        self.assertEqual(
            self.client.post(
                reverse("compliance_remove_item", args=[self.site.pk, self.lake.pk])).status_code,
            403)

    def test_a_site_engineer_cannot_prune(self):
        """They hold compliance.view — the widest read in the system — and no more."""
        self.client.force_login(self.make_user("site.person", role=Role.SITE))

        self.assertEqual(
            self.client.post(
                reverse("compliance_remove_item", args=[self.site.pk, self.lake.pk])).status_code,
            403)

    def test_compliance_may(self):
        self.client.force_login(self.make_user("comp.person", role=Role.COMPLIANCE))
        self.remove(self.lake)

        self.assertTrue(ProjectComplianceItem.objects.filter(item=self.lake).exists())

    def test_the_button_is_not_drawn_for_somebody_who_cannot(self):
        self.client.force_login(self.make_user("site.person2", role=Role.SITE))

        self.assertNotIn(reverse("compliance_remove_item", args=[self.site.pk, self.lake.pk]),
                         self.screen())


class TheLookupIsAskedOncePerProject(PruningFixture):
    """
    >>> ANCHOR: COMPLIANCE-PRUNING <<<
    The Overview walks every Won project against every regime. A removals lookup
    inside the regime loop would multiply by the number of types — bugs 3 and 9
    again, on a screen that already loops twice.
    """

    def test_removed_item_ids_is_one_query(self):
        self.remove(self.lake)

        with self.assertNumQueries(1):
            removed_item_ids(self.site)

    def test_and_none_at_all_without_a_project(self):
        with self.assertNumQueries(0):
            self.assertEqual(removed_item_ids(None), set())
