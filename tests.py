"""
What the board has to keep being true.

The four that matter most, and why each one is here rather than being assumed:

  · the finish is arithmetic, inclusive of the first day
  · a subtask cannot be filed under another project's header — the fault Saahil
    found by reading a dropdown in the prototype
  · a header name is unique on ONE site and free on every other
  · a site engineer can read the plan and cannot rewrite it
"""
from datetime import date, timedelta
from decimal import Decimal as D

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from accounts.testing import AuthedTestCase
from masters.models import Activity
from projects.models import Project
from tasks import schedule
from tasks.models import DelayReason, Subtask, TaskHeader


class TheDatesAreArithmetic(TestCase):
    """
    ⚠ NOTHING HERE TOUCHES THE DATABASE. Every one of these is a sum, and a sum
      that needs a fixture to prove it is a sum somebody will stop checking.
    """

    def test_three_days_from_monday_finishes_on_wednesday(self):
        # Inclusive of day one, which is how anybody on a site would say it.
        header = TaskHeader(start=date(2026, 8, 3), days=3)
        self.assertEqual(header.planned_end, date(2026, 8, 5))

    def test_one_day_starts_and_finishes_on_the_same_day(self):
        self.assertEqual(Subtask(start=date(2026, 8, 3), days=1).planned_end, date(2026, 8, 3))

    def test_a_header_with_no_subtasks_falls_back_to_its_own_window(self):
        # Which is exactly why a header carries dates of its own.
        header = TaskHeader(start=date(2026, 8, 3), days=5)
        self.assertEqual(header.work_span([]), (date(2026, 8, 3), date(2026, 8, 7)))
        self.assertEqual(header.days_over_plan([]), 0)

    def test_subtasks_running_past_the_commitment_are_flagged_before_anything_is_late(self):
        header = TaskHeader(start=date(2026, 8, 3), days=5)          # → 7 Aug
        rows = [Subtask(start=date(2026, 8, 3), days=2),
                Subtask(start=date(2026, 8, 6), days=6)]             # → 11 Aug
        self.assertEqual(header.days_over_plan(rows), 4)

    def test_progress_is_a_count_and_never_a_typed_percentage(self):
        header = TaskHeader(start=date(2026, 8, 3), days=5)
        rows = [Subtask(status=Subtask.Status.DONE), Subtask(status=Subtask.Status.OPEN),
                Subtask(status=Subtask.Status.BLOCKED)]
        self.assertEqual(header.progress(rows), (1, 3))

    def test_days_late_is_computed_from_what_happened_not_typed(self):
        subtask = Subtask(start=date(2026, 8, 3), days=3,            # due 5 Aug
                          finished_on=date(2026, 8, 8))             # finished 8 Aug
        self.assertEqual(subtask.days_late, 3)

    def test_finishing_early_is_not_a_negative_delay(self):
        subtask = Subtask(start=date(2026, 8, 3), days=5, finished_on=date(2026, 8, 4))
        self.assertEqual(subtask.days_late, 0)

    def test_overdue_and_late_are_different_questions(self):
        # Overdue: still open, and the date has passed. Late: finished, and it
        # finished after it should have. Something can be one without the other.
        open_row = Subtask(start=date(2026, 8, 3), days=1, status=Subtask.Status.OPEN)
        self.assertEqual(open_row.days_overdue(today=date(2026, 8, 6)), 3)
        self.assertEqual(open_row.days_late, 0)

        done_row = Subtask(start=date(2026, 8, 3), days=1, status=Subtask.Status.DONE,
                           finished_on=date(2026, 8, 6))
        self.assertEqual(done_row.days_overdue(today=date(2026, 8, 20)), 0)
        self.assertEqual(done_row.days_late, 3)


class BoardCase(AuthedTestCase):
    """Two Won sites, one that has not been sold, and a trade to book work under."""

    def setUp(self):
        super().setUp()
        self.rcc = Activity.objects.get(abbreviation="RCC")
        self.bhudarpura = Project.objects.create(
            name="Bhudarpura", bua_sqft=D("26545"), status=Project.Status.WON)
        self.sanskar = Project.objects.create(
            name="Shilp Sanskar", bua_sqft=D("18000"), status=Project.Status.WON)
        self.quoted = Project.objects.create(
            name="Not sold yet", bua_sqft=D("9000"), status=Project.Status.QUOTED)

    def header_on(self, project, name="Earthing"):
        return TaskHeader.objects.create(
            project=project, activity=self.rcc, name=name,
            start=date(2026, 8, 3), days=7, created_by=self.user)

    def board(self, project=None):
        url = reverse("task_board")
        return self.client.get(f"{url}?project={project.pk}" if project else url)


class TheBoardIsAboutOneSite(BoardCase):

    def test_the_picker_offers_won_projects_and_not_quoted_ones(self):
        # "have a project input option filtered from won projects" — a quoted job
        # has no site to work on.
        offered = {project.pk for project in self.board().context["projects"]}
        self.assertEqual(offered, {self.bhudarpura.pk, self.sanskar.pk})

    def test_a_completed_project_stays_in_the_picker(self):
        # ⚠ Otherwise every task on a finished building disappears on the day it
        #   is handed over, taking the record of who did what with it.
        self.bhudarpura.status = Project.Status.COMPLETED
        self.bhudarpura.save()
        offered = {project.pk for project in self.board().context["projects"]}
        self.assertIn(self.bhudarpura.pk, offered)

    def test_a_header_task_is_not_visible_on_another_project(self):
        # Saahil: "all tasks are unique". Every site has an Earthing, and they
        # are not the same Earthing.
        self.header_on(self.bhudarpura, "Earthing")
        self.header_on(self.sanskar, "Slab shuttering")

        names = [row["header"].name for row in self.board(self.sanskar).context["rows"]]
        self.assertEqual(names, ["Slab shuttering"])

    def test_the_new_subtask_box_offers_this_projects_headers_only(self):
        # ⚠ THE PROTOTYPE'S BUG, CAUGHT BY SAAHIL READING THE DROPDOWN. Filing
        #   work against the wrong building is not a mistake anybody notices.
        self.header_on(self.bhudarpura, "Earthing")
        self.header_on(self.sanskar, "Slab shuttering")

        offered = [header.name for header in self.board(self.sanskar).context["headers"]]
        self.assertEqual(offered, ["Slab shuttering"])

    def test_the_board_opens_on_an_installation_with_no_won_project(self):
        # A real state on the day the system is handed over, and not an error.
        Project.objects.all().delete()
        response = self.board()
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["project"])

    def test_the_board_does_not_query_once_per_header(self):
        """
        ⚠ THE THIRD TIME THIS MISTAKE WOULD HAVE BEEN MADE IN THIS CODEBASE.
          A fixed number would go stale with the next feature; what actually
          matters is that the count does not GROW with the work on the site.
        """
        for index in range(2):
            header = self.header_on(self.bhudarpura, f"Header {index}")
            Subtask.objects.create(header=header, title="Something",
                                   start=date(2026, 8, 3), days=1)

        with CaptureQueriesContext(connection) as small:
            self.board(self.bhudarpura)

        for index in range(2, 8):
            header = self.header_on(self.bhudarpura, f"Header {index}")
            Subtask.objects.create(header=header, title="Something",
                                   start=date(2026, 8, 3), days=1)

        with CaptureQueriesContext(connection) as large:
            self.board(self.bhudarpura)

        self.assertEqual(len(large), len(small),
                         "the board costs a query per header — prefetch_related has been lost")


class AddingWork(BoardCase):

    # ⚠ THE ARGUMENT IS CALLED `where`, NOT `name`. Three of these forms have a
    #   field called "name", and a helper that took one too swallowed it.
    def post(self, where, **data):
        return self.client.post(reverse(where), data)

    def test_a_header_task_gets_a_finish_it_was_never_asked_for(self):
        self.post("task_header_new", project=self.bhudarpura.pk, activity=self.rcc.pk,
                  name="Earthing", start="2026-08-03", days=3)
        header = TaskHeader.objects.get(name="Earthing")
        self.assertEqual(header.planned_end, date(2026, 8, 5))
        self.assertEqual(header.created_by, self.user)

    def test_the_same_header_name_is_refused_here_and_allowed_next_door(self):
        self.header_on(self.bhudarpura, "Earthing")

        # Same site, different capitals — one job typed twice.
        self.post("task_header_new", project=self.bhudarpura.pk, activity=self.rcc.pk,
                  name="EARTHING", start="2026-08-03", days=3)
        self.assertEqual(TaskHeader.objects.filter(project=self.bhudarpura).count(), 1)

        # Another site — a real second job, and it must be allowed.
        self.post("task_header_new", project=self.sanskar.pk, activity=self.rcc.pk,
                  name="Earthing", start="2026-08-03", days=3)
        self.assertEqual(TaskHeader.objects.filter(project=self.sanskar).count(), 1)

    def test_a_header_task_without_an_activity_is_refused(self):
        # The activity is what will one day tie the plan to the estimate.
        self.post("task_header_new", project=self.bhudarpura.pk, name="Earthing",
                  start="2026-08-03", days=3)
        self.assertFalse(TaskHeader.objects.exists())

    def test_a_duration_of_zero_days_is_refused(self):
        self.post("task_header_new", project=self.bhudarpura.pk, activity=self.rcc.pk,
                  name="Earthing", start="2026-08-03", days=0)
        self.assertFalse(TaskHeader.objects.exists())

    def test_a_subtask_cannot_be_filed_under_another_projects_header(self):
        """⚠ THE ONE THAT MATTERS. See the note in tasks/views.py."""
        elsewhere = self.header_on(self.bhudarpura, "Earthing")

        response = self.client.post(reverse("task_subtask_new"), {
            "project": self.sanskar.pk, "header": elsewhere.pk,
            "title": "Dig earth pits", "start": "2026-08-03", "days": 1,
        })

        self.assertEqual(response.status_code, 302)     # refused, not crashed
        self.assertFalse(Subtask.objects.exists())

    def test_a_subtask_lands_on_the_header_it_was_given(self):
        header = self.header_on(self.bhudarpura, "Earthing")
        mistry = self.make_user("mistry", role=Role.SITE, name="Ramesh Mistry")

        self.post("task_subtask_new", project=self.bhudarpura.pk, header=header.pk,
                  title="Dig earth pits", assignee=mistry.pk, start="2026-08-03",
                  days=2, priority=Subtask.Priority.HIGH)

        subtask = Subtask.objects.get()
        self.assertEqual(subtask.header, header)
        self.assertEqual(subtask.assignee, mistry)
        self.assertEqual(subtask.priority, Subtask.Priority.HIGH)
        self.assertEqual(subtask.planned_end, date(2026, 8, 4))
        # Nothing has happened to it yet, and that is a state of its own.
        self.assertEqual(subtask.status, Subtask.Status.OPEN)
        self.assertIsNone(subtask.finished_on)

    def test_a_milestone_is_a_header_task_and_is_created_as_one(self):
        """
        ⚠⚠ THESE TWO TESTS ASSERTED A SEPARATE MILESTONE MODEL, AND THE REWRITE
           IS THE RECORD. Saahil: "it's either milestone or head work… we can go
           ahead with head work, remove the milestone, and then we change the
           name of head work to milestone."

           The old model carried a date somebody TYPED. A header task's finish
           is COMPUTED from the work under it, so the two could disagree and the
           typed one would never find out. There is no address that makes a
           milestone any more, because making a package IS making one.
        """
        self.post("task_header_new", project=self.bhudarpura.pk, name="Phase one",
                  activity=self.rcc.pk, start="2026-04-01", days="30")
        milestone = TaskHeader.objects.get(name="Phase one")
        self.assertEqual(milestone.project, self.bhudarpura)
        # ⚠ THE FINISH IS COMPUTED AND INCLUSIVE OF DAY ONE.
        self.assertEqual(milestone.planned_end, date(2026, 4, 30))

    def test_there_is_no_longer_an_address_that_creates_a_milestone(self):
        """A POST address nobody can reach is the orphaned flow the sweep finds."""
        from django.urls import NoReverseMatch
        with self.assertRaises(NoReverseMatch):
            reverse("task_milestone_new")


class WhoMayDoWhat(BoardCase):
    """
    Reading the plan is one permission; rewriting it is another.

    ⚠ AND THE SCREEN AGREES WITH THE VIEW. A button that answers with a 403
      looks like a fault in the system rather than a rule of the business.
    """

    def setUp(self):
        super().setUp()
        self.engineer = self.make_user("site.person", role=Role.SITE, name="Ramesh Mistry")

    def test_a_site_engineer_can_read_the_board(self):
        self.header_on(self.bhudarpura, "Earthing")
        self.client.force_login(self.engineer)
        self.assertEqual(self.board(self.bhudarpura).status_code, 200)

    def test_a_site_engineer_is_not_shown_the_add_buttons(self):
        self.client.force_login(self.engineer)
        body = self.board(self.bhudarpura).content.decode()
        self.assertNotIn("Add header task", body)
        self.assertNotIn("Add milestone", body)

    def test_an_admin_is_shown_them(self):
        body = self.board(self.bhudarpura).content.decode()
        self.assertIn("Add milestone", body)

    def test_a_site_engineer_cannot_create_anything(self):
        self.client.force_login(self.engineer)
        # ⚠ `task_milestone_new` WENT WITH THE MODEL. A milestone is a header
        #   task, so the first name here is the same act.
        for name in ("task_header_new", "task_subtask_new"):
            self.assertEqual(self.client.post(reverse(name), {}).status_code, 403,
                             f"a site engineer was allowed to post {name}")

    def test_a_project_manager_can(self):
        manager = self.make_user("pm.person", role=Role.PROJECT_MANAGER, name="Priya Shah")
        self.client.force_login(manager)
        self.client.post(reverse("task_header_new"), {
            "project": self.bhudarpura.pk, "activity": self.rcc.pk,
            "name": "Earthing", "start": "2026-08-03", "days": 3,
        })
        self.assertTrue(TaskHeader.objects.filter(name="Earthing").exists())

    def test_only_a_manager_sees_the_delay_log_tab(self):
        self.client.force_login(self.engineer)
        self.assertNotIn(reverse("task_delay_log"),
                         self.board(self.bhudarpura).content.decode())
        self.client.force_login(self.user)          # the Admin from AuthedTestCase
        self.assertIn(reverse("task_delay_log"),
                      self.board(self.bhudarpura).content.decode())

    def test_the_launchpad_tile_is_live_and_opens_for_a_site_engineer(self):
        # It sat greyed beside Analytics for weeks. Lighting it up is the point
        # of having drawn it there.
        self.client.force_login(self.engineer)
        tile = next(tile for tile in self.client.get(reverse("launchpad")).context["tiles"]
                    if tile["key"] == "tasks")
        self.assertTrue(tile["live"])
        self.assertEqual(self.client.get(tile["url"]).status_code, 200)


class TheTickBelongsToThePersonDoingTheWork(BoardCase):
    """
    ⚠ THE RULE THIS WHOLE SCREEN EXISTS FOR — *"the engineers tick is final"*.

    A manager who could tick on somebody's behalf is a manager who eventually
    will, and the one fact the board collects — did the person who did the work
    say it was finished — would quietly stop being true.
    """

    def setUp(self):
        super().setUp()
        self.engineer = self.make_user("mistry", role=Role.SITE, name="Ramesh Mistry")
        self.header = self.header_on(self.bhudarpura, "Earthing")

    def subtask(self, title="Dig earth pits", assignee=None, start=None, days=1, **extra):
        return Subtask.objects.create(
            header=self.header, title=title,
            assignee=assignee or self.engineer,
            start=start or timezone.localdate(), days=days, **extra)

    def as_engineer(self):
        self.client.force_login(self.engineer)

    # ---- who may tick ---------------------------------------------------
    def test_the_assignee_may_mark_their_own_row_done(self):
        row = self.subtask()
        self.as_engineer()
        self.client.post(reverse("task_subtask_done", args=[row.pk]), {})
        row.refresh_from_db()
        self.assertEqual(row.status, Subtask.Status.DONE)
        self.assertEqual(row.finished_on, timezone.localdate())

    def test_an_admin_may_not_tick_somebody_elses_row(self):
        # ⚠ NOT A PERMISSION QUESTION. The Admin holds every key in the matrix
        #   and is still refused, because the matrix cannot express "whose".
        row = self.subtask()
        response = self.client.post(reverse("task_subtask_done", args=[row.pk]), {})
        self.assertEqual(response.status_code, 403)
        row.refresh_from_db()
        self.assertEqual(row.status, Subtask.Status.OPEN)

    def test_a_manager_may_reopen_a_tick_and_an_engineer_may_not(self):
        row = self.subtask(status=Subtask.Status.DONE, finished_on=timezone.localdate())

        self.as_engineer()
        self.assertEqual(
            self.client.post(reverse("task_subtask_reopen", args=[row.pk]), {}).status_code, 403)

        self.client.force_login(self.user)          # Admin
        self.client.post(reverse("task_subtask_reopen", args=[row.pk]), {})
        row.refresh_from_db()
        self.assertEqual(row.status, Subtask.Status.OPEN)
        self.assertIsNone(row.finished_on)

    # ---- the finish date ------------------------------------------------
    def test_the_finish_date_is_captured_and_cannot_be_typed(self):
        """
        ⚠ Saahil: "the engineer doesn't set the new date". Letting somebody type
          when they finished is letting them decide whether they were late.
        """
        row = self.subtask(start=date(2026, 1, 5), days=1)
        self.as_engineer()
        self.client.post(reverse("task_subtask_done", args=[row.pk]), {
            "finished_on": "2026-01-05", "delay_reason": DelayReason.MATERIAL})
        row.refresh_from_db()
        self.assertEqual(row.finished_on, timezone.localdate())

    # ---- the reason -----------------------------------------------------
    def test_a_late_tick_without_a_reason_is_refused(self):
        row = self.subtask(start=date(2026, 1, 5), days=1)       # long past
        self.as_engineer()
        self.client.post(reverse("task_subtask_done", args=[row.pk]), {})
        row.refresh_from_db()
        self.assertEqual(row.status, Subtask.Status.OPEN,
                         "a late row was marked done with no reason — the log would say nothing")

    def test_a_late_tick_with_a_reason_records_both(self):
        row = self.subtask(start=date(2026, 1, 5), days=1)
        self.as_engineer()
        self.client.post(reverse("task_subtask_done", args=[row.pk]), {
            "delay_reason": DelayReason.MATERIAL, "delay_note": "Cement arrived on the 6th"})
        row.refresh_from_db()
        self.assertEqual(row.status, Subtask.Status.DONE)
        self.assertEqual(row.delay_reason, DelayReason.MATERIAL)
        self.assertEqual(row.delay_note, "Cement arrived on the 6th")
        self.assertGreater(row.days_late, 0)

    def test_an_on_time_tick_is_never_asked_for_a_reason(self):
        # Nobody justifies being early, and a form that asks anyway teaches
        # people to pick the first option in the list.
        row = self.subtask(days=30)
        self.as_engineer()
        self.client.post(reverse("task_subtask_done", args=[row.pk]), {})
        row.refresh_from_db()
        self.assertEqual(row.status, Subtask.Status.DONE)
        self.assertEqual(row.delay_reason, "")

    # ---- blocked --------------------------------------------------------
    def test_blocking_needs_a_reason_and_does_not_move_the_date(self):
        """⚠ Saahil: "reason is an input when you block"."""
        row = self.subtask(start=date(2026, 1, 5), days=1)
        planned = row.planned_end
        self.as_engineer()

        self.client.post(reverse("task_subtask_blocked", args=[row.pk]), {})
        row.refresh_from_db()
        self.assertEqual(row.status, Subtask.Status.OPEN, "blocked with no reason given")

        self.client.post(reverse("task_subtask_blocked", args=[row.pk]),
                         {"blocked_reason": DelayReason.TRADE, "blocked_note": "waiting on the sparky"})
        row.refresh_from_db()
        self.assertEqual(row.status, Subtask.Status.BLOCKED)
        self.assertEqual(row.blocked_reason, DelayReason.TRADE)
        # The date stays where it was and keeps counting. That is the truth.
        self.assertEqual(row.planned_end, planned)
        self.assertGreater(row.days_overdue(), 0)

    def test_unblocking_puts_it_back_and_clears_the_flag(self):
        row = self.subtask(status=Subtask.Status.BLOCKED, blocked_reason=DelayReason.TRADE)
        self.as_engineer()
        self.client.post(reverse("task_subtask_unblock", args=[row.pk]), {})
        row.refresh_from_db()
        self.assertEqual(row.status, Subtask.Status.OPEN)
        self.assertEqual(row.blocked_reason, "")

    # ---- my work --------------------------------------------------------
    def test_my_work_shows_mine_and_nobody_elses(self):
        somebody = self.make_user("other.person", role=Role.SITE, name="Somebody Else")
        self.subtask()
        Subtask.objects.create(header=self.header, title="Not mine", assignee=somebody,
                               start=timezone.localdate(), days=1)

        self.as_engineer()
        titles = [row["subtask"].title for row in self.client.get(reverse("task_mine")).context["live"]]
        self.assertEqual(titles, ["Dig earth pits"])

    def test_my_work_puts_the_blocked_and_the_overdue_at_the_top(self):
        self.subtask(title="Comfortable", days=60)
        self.subtask(title="Overdue", start=date(2026, 1, 5), days=1)
        self.subtask(title="Stuck", days=60, status=Subtask.Status.BLOCKED,
                     blocked_reason=DelayReason.TRADE)

        self.as_engineer()
        order = [row["subtask"].title for row in self.client.get(reverse("task_mine")).context["live"]]
        self.assertEqual(order[0], "Stuck")
        self.assertEqual(order[1], "Overdue")

    def test_my_work_crosses_projects_because_a_person_does(self):
        elsewhere = self.header_on(self.sanskar, "Slab shuttering")
        self.subtask()
        Subtask.objects.create(header=elsewhere, title="Tie steel", assignee=self.engineer,
                               start=timezone.localdate(), days=1)

        self.as_engineer()
        rows = self.client.get(reverse("task_mine")).context["live"]
        self.assertEqual(len(rows), 2)


class TheDelayLogAnswersOneQuestion(BoardCase):
    """
    Not "which subtask was late" but "which KIND of problem keeps costing days".
    That is why the reason is a list and not a sentence.
    """

    def setUp(self):
        super().setUp()
        self.engineer = self.make_user("mistry", role=Role.SITE, name="Ramesh Mistry")
        self.header = self.header_on(self.bhudarpura, "Earthing")

    def late_by(self, days, reason, title="Dig earth pits"):
        start = date(2026, 1, 5)
        return Subtask.objects.create(
            header=self.header, title=title, assignee=self.engineer,
            start=start, days=1, status=Subtask.Status.DONE,
            # planned_end is the 5th; finishing later is the delay.
            finished_on=start + timedelta(days=days), delay_reason=reason)

    def test_the_summary_counts_days_by_reason_worst_first(self):
        self.late_by(5, DelayReason.MATERIAL, "a")
        self.late_by(4, DelayReason.MATERIAL, "b")
        self.late_by(2, DelayReason.WEATHER, "c")

        summary = self.client.get(reverse("task_delay_log")).context["summary"]
        self.assertEqual(summary[0]["reason"], DelayReason.MATERIAL)
        self.assertEqual(summary[0]["days"], 9)
        self.assertEqual(summary[0]["count"], 2)
        self.assertEqual(summary[1]["reason"], DelayReason.WEATHER)

    def test_work_that_finished_on_time_never_reaches_the_log(self):
        Subtask.objects.create(header=self.header, title="On time", assignee=self.engineer,
                               start=date(2026, 1, 5), days=1, status=Subtask.Status.DONE,
                               finished_on=date(2026, 1, 5))
        self.assertEqual(self.client.get(reverse("task_delay_log")).context["late"], [])

    def test_what_is_stuck_now_is_listed_separately_from_what_finished_late(self):
        # They are different questions: one is history, one is a phone call to
        # make this afternoon.
        self.late_by(3, DelayReason.MATERIAL)
        Subtask.objects.create(header=self.header, title="Stuck", assignee=self.engineer,
                               start=date(2026, 1, 5), days=1,
                               status=Subtask.Status.BLOCKED, blocked_reason=DelayReason.TRADE)

        response = self.client.get(reverse("task_delay_log"))
        self.assertEqual([row.title for row in response.context["blocked"]], ["Stuck"])
        self.assertEqual([row.title for row in response.context["late"]], ["Dig earth pits"])

    def test_it_filters_by_project_person_and_reason(self):
        self.late_by(3, DelayReason.MATERIAL, "material one")
        self.late_by(2, DelayReason.WEATHER, "weather one")

        url = reverse("task_delay_log")
        by_reason = self.client.get(f"{url}?reason={DelayReason.WEATHER}").context["late"]
        self.assertEqual([row.title for row in by_reason], ["weather one"])

        elsewhere = self.client.get(f"{url}?project={self.sanskar.pk}").context["late"]
        self.assertEqual(elsewhere, [])

    def test_a_site_engineer_cannot_open_it(self):
        self.client.force_login(self.engineer)
        self.assertEqual(self.client.get(reverse("task_delay_log")).status_code, 403)


class TheScheduleIsArithmeticBeforeItIsAPicture(BoardCase):
    """
    ⚠ EVERY LEFT AND WIDTH IS TESTED AS A NUMBER, because a bar in the wrong
      place looks like a plan rather than like a fault. Nobody double-checks a
      chart against the dates it was drawn from.
    """

    def setUp(self):
        super().setUp()
        self.header = TaskHeader.objects.create(
            project=self.bhudarpura, activity=self.rcc, name="Earthing",
            start=date(2026, 4, 1), days=30)              # 1 → 30 April

    def chart(self, today=date(2026, 4, 15)):
        return schedule.build(self.bhudarpura, today=today)

    def test_the_span_is_padded_out_to_whole_months(self):
        # A scale that starts mid-month puts every label out of line with the
        # bars underneath it.
        chart = self.chart()
        self.assertEqual(chart["span"]["start"], date(2026, 4, 1))
        self.assertEqual(chart["span"]["end"], date(2026, 4, 30))
        self.assertEqual(chart["span"]["days"], 30)

    def test_the_month_widths_add_up_to_the_whole_chart(self):
        Subtask.objects.create(header=self.header, title="Later work",
                               start=date(2026, 6, 1), days=10)
        chart = self.chart()
        self.assertEqual([month["label"] for month in chart["months"]],
                         ["Apr 2026", "May 2026", "Jun 2026"])
        # ⚠⚠ THIS ASSERTED 100.0 UNTIL THE CHART STOPPED SCALING TO THE PAGE,
        #    and the rewrite is the record. Widths are PIXELS now — see
        #    ANCHOR: TASK-SCHEDULE-SCALE — so the months add up to the track,
        #    not to a hundred. The question the test asks is unchanged: no day
        #    is drawn twice and none is missing.
        total = sum(float(month["width"]) for month in chart["months"])
        self.assertAlmostEqual(total, float(chart["track_px"]), places=2)
        self.assertAlmostEqual(total, chart["span"]["days"] * schedule.PX_PER_DAY, places=2)

    def test_a_bar_starts_where_its_date_starts(self):
        """
        ⚠ IN PIXELS NOW, NOT PERCENT. Fifteen days into the span is fifteen days
          wide at a fixed scale, whatever the project's length — which is the
          whole point of the change.
        """
        Subtask.objects.create(header=self.header, title="Second half",
                               start=date(2026, 4, 16), days=15)
        row = next(row for row in self.chart()["rows"] if row["kind"] == "subtask")
        self.assertAlmostEqual(float(row["bar"]["left"]), 15 * schedule.PX_PER_DAY, places=2)
        self.assertAlmostEqual(float(row["bar"]["width"]), 15 * schedule.PX_PER_DAY, places=2)

    def test_the_scale_does_not_change_when_the_project_gets_longer(self):
        """
        ⚠⚠ THE FAULT SAAHIL FOUND, ASSERTED. The same fortnight of work must be
           the same width whether the project runs one month or two years. Under
           the old percentage geometry it shrank until it was unreadable.
        """
        Subtask.objects.create(header=self.header, title="A fortnight",
                               start=date(2026, 4, 1), days=14)
        narrow = next(r for r in self.chart()["rows"] if r["kind"] == "subtask")["bar"]["width"]

        TaskHeader.objects.create(project=self.bhudarpura, activity=self.rcc,
                                  name="Two years out", start=date(2028, 3, 1), days=31)
        wide = next(r for r in self.chart()["rows"] if r["kind"] == "subtask")["bar"]["width"]
        self.assertEqual(narrow, wide)

    def test_a_one_day_task_is_still_visible_in_a_two_year_span(self):
        # ⚠ An invisible bar reads as "there is no work here", which is the
        #   opposite of the truth.
        # A far-off package, so the span really is two years wide.
        TaskHeader.objects.create(project=self.bhudarpura, activity=self.rcc,
                                  name="Handover", start=date(2028, 3, 1), days=31)
        Subtask.objects.create(header=self.header, title="One day",
                               start=date(2026, 4, 2), days=1)
        row = next(row for row in self.chart()["rows"] if row["kind"] == "subtask")
        self.assertGreater(float(row["bar"]["width"]), 0)

    def test_a_late_subtask_gets_a_second_segment_and_no_words(self):
        Subtask.objects.create(header=self.header, title="Ran over",
                               start=date(2026, 4, 1), days=5,      # due the 5th
                               status=Subtask.Status.DONE, finished_on=date(2026, 4, 10))
        row = next(row for row in self.chart()["rows"] if row["kind"] == "subtask")
        self.assertIsNotNone(row["late_bar"])
        self.assertEqual(row["late"], 5)
        # The tail begins the day after the planned end: 6 April is day 5.
        self.assertAlmostEqual(float(row["late_bar"]["left"]), 5 * schedule.PX_PER_DAY, places=2)

    def test_an_open_row_grows_its_tail_up_to_today_and_no_further(self):
        Subtask.objects.create(header=self.header, title="Still open",
                               start=date(2026, 4, 1), days=5)
        row = next(row for row in self.chart(today=date(2026, 4, 15))["rows"]
                   if row["kind"] == "subtask")
        self.assertEqual(row["late"], 10)
        self.assertIsNotNone(row["late_bar"])

    def test_finishing_on_time_draws_one_bar_only(self):
        Subtask.objects.create(header=self.header, title="On time",
                               start=date(2026, 4, 1), days=5,
                               status=Subtask.Status.DONE, finished_on=date(2026, 4, 4))
        row = next(row for row in self.chart()["rows"] if row["kind"] == "subtask")
        self.assertIsNone(row["late_bar"])

    def test_the_headers_amber_band_is_a_different_thing_from_late(self):
        """
        ⚠ THE TWO WARNINGS THAT MUST NOT BE MERGED. Nothing here has slipped —
          the subtasks simply run past the window the manager committed to.
        """
        Subtask.objects.create(header=self.header, title="Overruns the plan",
                               start=date(2026, 4, 20), days=20)     # → 9 May

        # ⚠ "header" BECAME "milestone", AND THE ROW NOW CARRIES BOTH COLOURS
        #   ITSELF: the navy window it was given, and an amber tail for exactly
        #   how far the work ran past it. The line still marks the judged
        #   finish too — belt and braces, not a duplicate: the band is fixed at
        #   what was promised, the line moves with what actually happened.
        milestone_row = next(row for row in self.chart()["rows"] if row["kind"] == "milestone")
        self.assertEqual(milestone_row["over"], 9)
        self.assertIsNotNone(milestone_row["bar"])
        self.assertIsNotNone(milestone_row["over_bar"])
        # The window band is fixed at 1 → 30 April, whatever the work does.
        self.assertAlmostEqual(float(milestone_row["bar"]["left"]), 0, places=2)
        self.assertAlmostEqual(float(milestone_row["bar"]["width"]), 30 * schedule.PX_PER_DAY, places=2)
        # The overrun tail starts the day after the window closes (1 May) and
        # runs to where the work actually finished (9 May) — 9 days.
        self.assertAlmostEqual(float(milestone_row["over_bar"]["left"]), 30 * schedule.PX_PER_DAY, places=2)
        self.assertAlmostEqual(float(milestone_row["over_bar"]["width"]), 9 * schedule.PX_PER_DAY, places=2)

        line = self.chart()["milestones"][0]
        self.assertTrue(line["over"])
        # The line moved with the work rather than staying on the promise.
        self.assertEqual(line["date"], date(2026, 5, 9))
        # ⚠ A BAR IS A DAY-INCLUSIVE RECTANGLE; A LINE IS A DAY-START POINT.
        #   The tail covers the whole of 9 May, so its right edge sits at the
        #   START of 10 May — one day-width past the line, which marks the
        #   start of 9 May itself. Not a mismatch: it is the same convention
        #   every subtask bar already uses against the "today" marker.
        self.assertAlmostEqual(float(line["left"]) + schedule.PX_PER_DAY,
                               float(milestone_row["over_bar"]["left"]) +
                               float(milestone_row["over_bar"]["width"]), places=2)

        subtask_row = next(row for row in self.chart()["rows"] if row["kind"] == "subtask")
        self.assertEqual(subtask_row["late"], 0, "nothing is late — only the plan no longer fits")
        self.assertIsNone(subtask_row["late_bar"])

    def test_a_milestone_draws_its_window_the_moment_it_exists(self):
        """
        >>> ANCHOR: MILESTONE-LINE <<<
        ⚠⚠ THE FAULT SAAHIL FOUND, ASSERTED. A milestone with NO subtasks yet
           used to draw nothing at all — not the band, not a hint of its span —
           which read as "there is no plan here" on exactly the project length
           that is ordinary rather than exceptional. `work_span` falls back to
           the header's own dates when there are no subtasks, so the band does
           not depend on anything being scheduled under it yet.
        """
        empty_header = TaskHeader.objects.create(
            project=self.bhudarpura, activity=self.rcc, name="Nothing under it yet",
            start=date(2026, 4, 1), days=30)
        row = next(row for row in schedule.build(self.bhudarpura, today=date(2026, 4, 15))["rows"]
                  if row["kind"] == "milestone" and row["header"] == empty_header)
        self.assertIsNotNone(row["bar"])
        self.assertGreater(float(row["bar"]["width"]), 0)
        # Nothing has run past a window with no subtasks in it.
        self.assertIsNone(row["over_bar"])

    def test_a_milestones_finish_is_a_computed_position(self):
        """
        >>> ANCHOR: MILESTONE-LINE <<<
        ⚠ THE LINE'S DATE IS THE PHASE'S FINISH, COMPUTED, not a typed one. The
          band and the line are two different facts and both are asserted
          elsewhere; this pins down the line alone.
        """
        entry = self.chart()["milestones"][0]
        self.assertEqual(entry["date"], self.header.planned_end)
        self.assertNotIn("width", entry)

    def test_today_is_marked_only_when_it_falls_inside_the_span(self):
        self.assertIsNotNone(self.chart(today=date(2026, 4, 15))["today"])
        # A chart of last year's work should not draw a marker jammed against
        # one edge, which is a lie about where today is.
        self.assertIsNone(self.chart(today=date(2027, 1, 1))["today"])

    def test_a_project_with_nothing_on_it_draws_nothing(self):
        self.assertIsNone(schedule.build(self.sanskar, today=date(2026, 4, 15)))

    def test_the_screen_opens_for_a_site_engineer(self):
        engineer = self.make_user("mistry", role=Role.SITE, name="Ramesh Mistry")
        self.client.force_login(engineer)
        self.assertEqual(
            self.client.get(f"{reverse('task_schedule')}?project={self.bhudarpura.pk}").status_code,
            200)


class ThePeopleScreenIsAWorkloadNotAScoreboard(BoardCase):

    def setUp(self):
        super().setUp()
        self.engineer = self.make_user("mistry", role=Role.SITE, name="Ramesh Mistry")
        self.header = self.header_on(self.bhudarpura, "Earthing")

    def row_for(self, person, response):
        return next(row for row in response.context["rows"] if row["person"] == person)

    def test_it_counts_open_blocked_overdue_and_done(self):
        Subtask.objects.create(header=self.header, title="Open", assignee=self.engineer,
                               start=timezone.localdate(), days=30)
        Subtask.objects.create(header=self.header, title="Overdue", assignee=self.engineer,
                               start=date(2026, 1, 5), days=1)
        Subtask.objects.create(header=self.header, title="Stuck", assignee=self.engineer,
                               start=timezone.localdate(), days=30,
                               status=Subtask.Status.BLOCKED, blocked_reason=DelayReason.TRADE)
        Subtask.objects.create(header=self.header, title="Finished", assignee=self.engineer,
                               start=date(2026, 1, 5), days=1, status=Subtask.Status.DONE,
                               finished_on=date(2026, 1, 8), delay_reason=DelayReason.WEATHER)

        row = self.row_for(self.engineer, self.client.get(reverse("task_people")))
        self.assertEqual(row["open"], 2)          # the open one and the overdue one
        self.assertEqual(row["blocked"], 1)
        self.assertEqual(row["overdue"], 1)
        self.assertEqual(row["done"], 1)
        self.assertEqual(row["days_late"], 3)

    def test_unassigned_work_is_the_first_row(self):
        # ⚠ Nobody sees it on their own screen and nobody can tick it.
        Subtask.objects.create(header=self.header, title="Nobody's",
                               start=timezone.localdate(), days=1)
        Subtask.objects.create(header=self.header, title="Somebody's", assignee=self.engineer,
                               start=timezone.localdate(), days=1)
        rows = self.client.get(reverse("task_people")).context["rows"]
        self.assertIsNone(rows[0]["person"])

    def test_the_next_one_due_is_the_earliest_still_open(self):
        Subtask.objects.create(header=self.header, title="Later", assignee=self.engineer,
                               start=date(2026, 12, 1), days=1)
        Subtask.objects.create(header=self.header, title="Sooner", assignee=self.engineer,
                               start=date(2026, 6, 1), days=1)
        row = self.row_for(self.engineer, self.client.get(reverse("task_people")))
        self.assertEqual(row["next"].title, "Sooner")

    def test_a_site_engineer_cannot_open_it(self):
        self.client.force_login(self.engineer)
        self.assertEqual(self.client.get(reverse("task_people")).status_code, 403)


class ReschedulingKeepsTheFirstPromise(BoardCase):
    """
    ⚠ THE RULE SAAHIL CHOSE WHEN EDITING WAS ADDED: "keep the first promise".
      The team works to the new date; the original stays on the row. Without it
      an editable plan can always be made to look on time, and the delay log
      quietly stops counting the days that were replanned rather than missed —
      which, on a site, is most of them.
    """

    def setUp(self):
        super().setUp()
        self.engineer = self.make_user("mistry", role=Role.SITE, name="Ramesh Mistry")
        self.header = TaskHeader.objects.create(
            project=self.bhudarpura, activity=self.rcc, name="Earthing",
            start=date(2026, 4, 1), days=10)
        self.row = Subtask.objects.create(
            header=self.header, title="Dig earth pits", assignee=self.engineer,
            start=date(2026, 4, 1), days=5)

    def edit(self, **data):
        payload = {"title": self.row.title, "assignee": self.engineer.pk,
                   "start": "2026-04-01", "days": 5, "priority": "N"}
        payload.update(data)
        return self.client.post(reverse("task_subtask_edit", args=[self.row.pk]), payload)

    def test_pushing_the_finish_out_without_a_reason_is_refused(self):
        self.edit(days=12)
        self.row.refresh_from_db()
        self.assertEqual(self.row.days, 5, "the plan moved with nobody saying why")

    def test_pushing_it_out_with_a_reason_keeps_the_original(self):
        self.edit(days=12, shift_reason=DelayReason.SCOPE, shift_note="Drawing revised")
        self.row.refresh_from_db()
        self.assertEqual(self.row.days, 12)
        self.assertEqual(self.row.original_start, date(2026, 4, 1))
        self.assertEqual(self.row.original_days, 5)
        self.assertEqual(self.row.promised_end, date(2026, 4, 5))   # what was first agreed
        self.assertEqual(self.row.planned_end, date(2026, 4, 12))   # what the team works to
        self.assertEqual(self.row.days_shifted, 7)
        self.assertEqual(self.row.shift_reason, DelayReason.SCOPE)

    def test_pulling_work_forward_is_never_a_delay(self):
        # ⚠ No reason is asked for, and nothing is recorded as lost.
        self.edit(start="2026-03-25")
        self.row.refresh_from_db()
        self.assertEqual(self.row.start, date(2026, 3, 25))
        self.assertEqual(self.row.days_shifted, 0)

    def test_the_promise_is_captured_once_and_not_re_captured(self):
        """A plan pushed out three times is one promise, not three."""
        self.edit(days=12, shift_reason=DelayReason.SCOPE)
        self.edit(days=20, shift_reason=DelayReason.MATERIAL)
        self.row.refresh_from_db()
        self.assertEqual(self.row.original_days, 5, "the second edit overwrote the first promise")
        self.assertEqual(self.row.days_shifted, 15)

    def test_a_reassignment_moves_it_to_the_other_persons_screen(self):
        somebody = self.make_user("other.person", role=Role.SITE, name="Somebody Else")
        self.edit(assignee=somebody.pk)
        self.row.refresh_from_db()
        self.assertEqual(self.row.assignee, somebody)

    def test_an_engineer_cannot_open_the_edit_screen(self):
        self.client.force_login(self.engineer)
        self.assertEqual(
            self.client.get(reverse("task_subtask_edit", args=[self.row.pk])).status_code, 403)

    def test_a_header_keeps_its_promise_too(self):
        self.client.post(reverse("task_header_edit", args=[self.header.pk]), {
            "name": "Earthing", "activity": self.rcc.pk, "start": "2026-04-01", "days": 25,
            "shift_reason": DelayReason.DECISION})
        self.header.refresh_from_db()
        self.assertEqual(self.header.days, 25)
        self.assertEqual(self.header.days_shifted, 15)

    def test_replanned_days_reach_the_delay_log_and_are_counted(self):
        # ⚠ THE POINT OF THE WHOLE BASELINE. Nothing here is late by any test,
        #   and seven days have still been lost.
        self.edit(days=12, shift_reason=DelayReason.SCOPE)
        response = self.client.get(reverse("task_delay_log"))
        self.assertEqual([row.title for row in response.context["shifted"]], ["Dig earth pits"])
        self.assertEqual(response.context["late"], [])
        self.assertEqual(response.context["total_days"], 7)
        self.assertEqual(response.context["summary"][0]["reason"], DelayReason.SCOPE)


class MovingSeveralAtOnce(BoardCase):
    """
    ⚠ THE AGREED SUBSTITUTE FOR DEPENDENCIES. A dependency graph is the feature
      everybody asks for and nobody maintains; this is the blunt instrument that
      does the same job — tick the rows that have to move, shift them together,
      say why once.
    """

    def setUp(self):
        super().setUp()
        self.engineer = self.make_user("mistry", role=Role.SITE, name="Ramesh Mistry")
        self.header = self.header_on(self.bhudarpura, "Earthing")
        self.elsewhere = self.header_on(self.sanskar, "Slab shuttering")
        self.first = Subtask.objects.create(header=self.header, title="One",
                                            start=date(2026, 4, 1), days=5)
        self.second = Subtask.objects.create(header=self.header, title="Two",
                                             start=date(2026, 4, 6), days=5)
        self.other_site = Subtask.objects.create(header=self.elsewhere, title="Not this one",
                                                 start=date(2026, 4, 1), days=5)

    def bulk(self, **data):
        payload = {"project": self.bhudarpura.pk}
        payload.update(data)
        return self.client.post(reverse("task_subtasks_bulk"), payload)

    def test_ticked_rows_move_together(self):
        self.bulk(action="shift", days=7, shift_reason=DelayReason.MATERIAL,
                  subtask=[self.first.pk, self.second.pk])
        self.first.refresh_from_db()
        self.second.refresh_from_db()
        self.assertEqual(self.first.start, date(2026, 4, 8))
        self.assertEqual(self.second.start, date(2026, 4, 13))
        self.assertEqual(self.first.days_shifted, 7)
        self.assertEqual(self.first.shift_reason, DelayReason.MATERIAL)

    def test_a_shift_outward_without_a_reason_moves_nothing(self):
        self.bulk(action="shift", days=7, subtask=[self.first.pk])
        self.first.refresh_from_db()
        self.assertEqual(self.first.start, date(2026, 4, 1))

    def test_pulling_forward_needs_no_reason(self):
        self.bulk(action="shift", days=-3, subtask=[self.first.pk])
        self.first.refresh_from_db()
        self.assertEqual(self.first.start, date(2026, 3, 29))
        self.assertEqual(self.first.days_shifted, 0)

    def test_a_row_from_another_project_is_not_touched(self):
        # ⚠ Same rule as everywhere else here: ids are looked up WITHIN the
        #   chosen project, so a posted id from another site is simply not found.
        self.bulk(action="shift", days=7, shift_reason=DelayReason.MATERIAL,
                  subtask=[self.other_site.pk])
        self.other_site.refresh_from_db()
        self.assertEqual(self.other_site.start, date(2026, 4, 1))

    def test_reassigning_in_bulk(self):
        self.bulk(action="reassign", assignee=self.engineer.pk,
                  subtask=[self.first.pk, self.second.pk])
        self.first.refresh_from_db()
        self.second.refresh_from_db()
        self.assertEqual(self.first.assignee, self.engineer)
        self.assertEqual(self.second.assignee, self.engineer)

    def test_an_engineer_cannot_use_it(self):
        self.client.force_login(self.engineer)
        self.assertEqual(
            self.client.post(reverse("task_subtasks_bulk"), {}).status_code, 403)


class NoScreenLeaksRawTemplateSyntax(BoardCase):
    """
    ⚠ BUG 11, WHICH HAS ALREADY HAPPENED ONCE. A mistyped tag does not raise —
      it prints itself onto the page. The same guard runs over the project
      screens; these three are now covered too.

    ⚠ AND IT FIRES ON CSS AND JAVASCRIPT AS WELL. `width:38%}` leaks `%}` and
      looks exactly like a broken tag, which is why the board's stylesheet has a
      semicolon before that brace.
    """

    def setUp(self):
        super().setUp()
        engineer = self.make_user("mistry", role=Role.SITE, name="Ramesh Mistry")
        header = self.header_on(self.bhudarpura, "Earthing")
        Subtask.objects.create(header=header, title="Dig earth pits", assignee=self.user,
                               start=date(2026, 1, 5), days=1)
        Subtask.objects.create(header=header, title="Backfill", assignee=engineer,
                               start=date(2026, 1, 5), days=1, status=Subtask.Status.DONE,
                               finished_on=date(2026, 1, 9), delay_reason=DelayReason.MATERIAL)

    def test_the_five_task_screens_render_clean(self):
        for url in (f"{reverse('task_board')}?project={self.bhudarpura.pk}",
                    f"{reverse('task_schedule')}?project={self.bhudarpura.pk}",
                    reverse("task_mine"),
                    reverse("task_people"),
                    reverse("task_delay_log")):
            body = self.client.get(url).content.decode()
            for leak in ("{#", "#}", "{%", "%}"):
                self.assertNotIn(leak, body, f"{url} printed raw template syntax: {leak}")


class MilestoneLabelsStaggerAndLinesDoNot(BoardCase):
    """
    >>> ANCHOR: MILESTONE-LINE <<<
    Saahil, shown the vertical dotted line: "can you just show me what you're
    talking about? I really don't understand what will happen if they are
    sitting on top of each other."

    ⚠⚠ THE ANSWER IS THAT THE LABEL MOVES AND THE LINE NEVER DOES. Moving a line
       so its label fits would be drawing a lie about the date it marks.
    """

    def milestone(self, name, start, days):
        return TaskHeader.objects.create(project=self.bhudarpura, activity=self.rcc,
                                         name=name, start=start, days=days)

    def lines(self):
        return schedule.build(self.bhudarpura, today=date(2026, 4, 1))["milestones"]

    def test_two_phases_far_apart_share_the_first_lane(self):
        self.milestone("Foundation", date(2026, 4, 1), 30)
        self.milestone("Finishing", date(2027, 1, 1), 30)
        self.assertEqual({line["lane"] for line in self.lines()}, {0})

    def test_two_phases_days_apart_do_not(self):
        """The collision he asked to see, and the fix for it."""
        self.milestone("Foundation", date(2026, 4, 1), 30)      # → 30 April
        self.milestone("Superstructure", date(2026, 4, 2), 32)  # → 3 May
        lanes = [line["lane"] for line in self.lines()]
        self.assertEqual(len(set(lanes)), 2, "two labels days apart landed in the same lane")

    def test_the_lines_themselves_stay_exactly_on_their_dates(self):
        first = self.milestone("Foundation", date(2026, 4, 1), 30)
        second = self.milestone("Superstructure", date(2026, 4, 2), 32)
        by_name = {line["header"].name: line for line in self.lines()}
        self.assertEqual(by_name["Foundation"]["date"], first.planned_end)
        self.assertEqual(by_name["Superstructure"]["date"], second.planned_end)
        self.assertLess(float(by_name["Foundation"]["left"]),
                        float(by_name["Superstructure"]["left"]))

    def test_they_come_back_in_date_order(self):
        self.milestone("Late one", date(2026, 8, 1), 10)
        self.milestone("Early one", date(2026, 4, 1), 10)
        names = [line["header"].name for line in self.lines()]
        self.assertEqual(names, sorted(names, key=lambda n: n == "Late one"))

    def test_a_crowd_never_pushes_a_label_out_of_existence(self):
        """
        ⚠ FIVE PHASES INSIDE A FORTNIGHT IS MORE THAN THE LANES CAN SEPARATE.
          Better a collision than a label silently dropped — somebody looking at
          a crowded chart can still read the tooltip.
        """
        # ⚠ build() RETURNS None WITH NOTHING TO DRAW, which is the honest answer
        #   and the reason this cannot just count before and after.
        for n in range(5):
            self.milestone(f"Phase {n}", date(2026, 4, 1 + n), 5)
        lines = self.lines()
        self.assertEqual(len(lines), 5)
        for line in lines:
            self.assertIsNotNone(line["lane"])

    def test_only_the_lanes_in_use_are_reported(self):
        self.milestone("Foundation", date(2026, 4, 1), 30)
        self.milestone("Finishing", date(2027, 1, 1), 30)
        chart = schedule.build(self.bhudarpura, today=date(2026, 4, 1))
        self.assertEqual(chart["milestone_lanes"], [0])
