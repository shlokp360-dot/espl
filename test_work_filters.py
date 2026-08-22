"""
The Work tab's two extra filters.

>>> ANCHOR: ANALYTICS-WORK-FILTERS <<<
Point 20. Analytics carried month, project and document type, and this tab —
the one that is entirely about site work — had nothing for the two things it is
actually about: which milestone, and which construction activity.

⚠ THE POINT THAT NEARLY GOT LOST. It was marked Decided in the review and then
  never assigned to a slice, so it sat unbuilt while four other commits went
  past. There is nothing clever in it; it is here because it was forgotten.

⚠ THE SHARED FILTER BAR IS ONE FORM. These two selects go INSIDE it, so choosing
  a milestone carries month, project and type along. A second form beside it
  would drop back to every project on the first click.
"""
from datetime import date
from decimal import Decimal as D

from django.test import TestCase
from django.urls import reverse
from django.utils.html import escape

from accounts.models import Role
from accounts.testing import AuthedTestCase
from masters.models import Activity
from projects.models import Project
from tasks.models import Subtask, TaskHeader


class WorkFilterFixture(AuthedTestCase):
    """One site, two activities, three milestones, so a filter has something to do."""

    def setUp(self):
        super().setUp()
        self.rcc = Activity.objects.create(abbreviation="ZQ1", name="Structure test",
                                           rate=D("100"), sort_order=910)
        self.finish = Activity.objects.create(abbreviation="ZQ2", name="Finishes test",
                                              rate=D("60"), sort_order=911)

        self.project = Project.objects.create(name="Filter site", bua_sqft=D("10000"),
                                              status=Project.Status.WON)
        self.other = Project.objects.create(name="Other site", bua_sqft=D("5000"),
                                            status=Project.Status.WON)

        self.footing = self.milestone("Footing", self.rcc)
        self.slab = self.milestone("Slab", self.rcc)
        self.paint = self.milestone("Painting", self.finish)

        # One late task under Footing, so days lost is not zero and can be seen
        # to move when the filter narrows.
        self.late = Subtask.objects.create(
            header=self.footing, title="Excavate", start=date(2026, 7, 1), days=5,
            status=Subtask.Status.DONE, finished_on=date(2026, 7, 12),
            delay_reason="material", created_by=self.user)
        Subtask.objects.create(header=self.slab, title="Shuttering", start=date(2026, 7, 20),
                               days=5, created_by=self.user)
        Subtask.objects.create(header=self.paint, title="Primer", start=date(2026, 8, 1),
                               days=3, created_by=self.user)

    def milestone(self, name, activity):
        return TaskHeader.objects.create(
            project=self.project, name=name, activity=activity,
            start=date(2026, 7, 1), days=20, created_by=self.user)

    def work(self, **params):
        params.setdefault("project", self.project.pk)
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return self.client.get(f"{reverse('analytics_tasks')}?{query}")


class TheFiltersAreOffered(WorkFilterFixture):

    def test_both_selects_are_on_the_page(self):
        page = self.work().content.decode()

        self.assertIn('name="milestone"', page)
        self.assertIn('name="activity"', page)

    def test_the_milestones_offered_are_this_project_s(self):
        """
        ⚠ BUG 14 IN A DIFFERENT HAT — the prototype dropdown that listed every
          project's header tasks. The choices come from the headers already
          loaded for this project, not from a master query.
        """
        elsewhere = TaskHeader.objects.create(
            project=self.other, name="Somewhere else", activity=self.rcc,
            start=date(2026, 7, 1), days=5, created_by=self.user)

        page = self.work().content.decode()

        self.assertIn(escape(self.footing.name), page)
        self.assertNotIn(escape(elsewhere.name), page)

    def test_only_the_activities_this_project_uses(self):
        spare = Activity.objects.create(abbreviation="ZQ3", name="Unused test activity",
                                        rate=D("10"), sort_order=912)

        page = self.work().content.decode()

        self.assertIn(escape(self.rcc.name), page)
        self.assertNotIn(escape(spare.name), page)

    def test_they_are_not_offered_on_the_other_analytics_tabs(self):
        """"Which milestone" means nothing on Payments or Gross to net."""
        for name in ("analytics_payments", "analytics_g2n", "analytics_budget"):
            page = self.client.get(reverse(name)).content.decode()
            self.assertNotIn('name="milestone"', page, name)


class FilteringNarrowsTheTables(WorkFilterFixture):
    """
    ⚠ THESE ASSERT ON THE TABLE DATA, NOT ON THE PAGE TEXT. Written first as
      "the activity name is not in the HTML", which failed for the right reason:
      the name is still in the filter dropdown, because that is where you choose
      it. A whole-page assertion cannot tell a row from a control.
    """

    def labels(self, **params):
        return [row["label"] for row in self.work(**params).context["rows"]]

    def test_by_milestone(self):
        self.assertEqual(self.labels(milestone=self.paint.pk), [self.finish.name])

    def test_by_activity(self):
        self.assertEqual(self.labels(activity=self.finish.pk), [self.finish.name])

    def test_days_lost_follows_the_filter(self):
        """The late task is under Footing, so filtering to Painting must zero it."""
        everything = self.work().context["days_lost"]
        painting = self.work(milestone=self.paint.pk).context["days_lost"]

        self.assertGreater(everything, 0)
        self.assertEqual(painting, 0)

    def test_the_two_combine(self):
        """Slab is a Structure milestone, so asking for it under Finishes is empty."""
        self.assertEqual(self.labels(milestone=self.slab.pk, activity=self.finish.pk), [])

    def test_rubbish_in_the_address_is_ignored_rather_than_crashing(self):
        """A filter is a query string; anybody can type anything into one."""
        self.assertEqual(self.work(milestone="; drop table", activity="none").status_code, 200)


class WhatTheFilterDoesNotTouch(WorkFilterFixture):

    def test_the_chart_still_draws_the_whole_plan(self):
        """
        ⚠ DELIBERATE. It is the same drawing the site team reads every morning,
          and a Gantt showing one phase out of six is a different picture from
          the one they discuss. The screen says so when a filter is on.
        """
        chart = self.work(milestone=self.paint.pk).context["chart_data"]

        names = [row["header"].name for row in chart["rows"] if row["kind"] == "milestone"]
        self.assertIn(self.footing.name, names)
        self.assertIn(self.paint.name, names)

    def test_and_says_so_on_screen(self):
        page = self.work(milestone=self.paint.pk).content.decode()

        self.assertIn("the filters narrow the", page)

    def test_nothing_is_said_when_no_filter_is_on(self):
        self.assertNotIn("the filters narrow the", self.work().content.decode())


class TheProjectFilterSurvives(WorkFilterFixture):
    """
    ⚠⚠ THE REASON THE SELECTS LIVE INSIDE THE SHARED FORM. A second form would
       post `milestone` on its own, and the project would fall back to the first
       Won site — quietly showing somebody another building's numbers.
    """

    def test_the_selects_are_inside_the_one_form(self):
        page = self.work().content.decode()

        form = page.split("<form method=\"get\"")[1].split("</form>")[0]
        for control in ('name="month"', 'name="project"', 'name="type"',
                        'name="milestone"', 'name="activity"'):
            self.assertIn(control, form)

    def test_filtering_keeps_the_chosen_project(self):
        page = self.work(milestone=self.slab.pk).content.decode()

        self.assertIn(escape(self.project.name), page)
        self.assertNotIn(escape(self.other.name).replace("Other site", "OTHER SITE ROWS"), page)


class OnlyAdminReadsThisAtAll(WorkFilterFixture):
    """The tab is `analytics.view`, which is Admin alone. Unchanged by point 20."""

    def test_a_project_manager_is_refused(self):
        self.client.force_login(self.make_user("pm.filter", role=Role.PROJECT_MANAGER))

        self.assertEqual(self.client.get(reverse("analytics_tasks")).status_code, 403)
