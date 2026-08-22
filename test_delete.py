"""
Deleting a task, and a milestone.

>>> ANCHOR: TASK-DELETE <<<
Point 14 of the review. There was no delete route anywhere in this module, so a
row typed under the wrong milestone stayed there forever. Saahil chose option B
when the two were put to him: Admin and project manager may delete ANY task,
history included, and it is their judgement.

⚠⚠ THIS IS THE ONLY THING IN THE MODULE THAT DESTROYS A RECORD. Everything else
   keeps what happened beside what was planned. So the tests here are mostly
   about who cannot do it, and about what goes with it.
"""
from datetime import date, timedelta
from decimal import Decimal as D

from django.test import TestCase
from django.urls import reverse

from accounts.models import Role
from accounts.testing import AuthedTestCase
from masters.models import Activity
from projects.models import Project
from tasks.models import Subtask, TaskHeader


class DeleteFixture(AuthedTestCase):

    def setUp(self):
        super().setUp()
        self.activity = Activity.objects.create(abbreviation="ZQX", name="Delete test activity",
                                                rate=D("100"), sort_order=907)
        self.project = Project.objects.create(name="Delete site", bua_sqft=D("10000"),
                                              status=Project.Status.WON)
        self.header = TaskHeader.objects.create(
            project=self.project, name="Site work", activity=self.activity,
            start=date(2026, 8, 3), days=20, created_by=self.user)
        self.task = Subtask.objects.create(
            header=self.header, title="Dig earth pits", start=date(2026, 8, 4), days=5,
            assignee=self.user, created_by=self.user)
        self.empty = TaskHeader.objects.create(
            project=self.project, name="Nothing under this", activity=self.activity,
            start=date(2026, 9, 1), days=5, created_by=self.user)

    def delete_task(self, task=None):
        return self.client.post(
            reverse("task_subtask_delete", args=[(task or self.task).pk]), follow=True)

    def delete_header(self, header):
        return self.client.post(
            reverse("task_header_delete", args=[header.pk]), follow=True)


class DeletingATask(DeleteFixture):

    def test_it_goes(self):
        self.delete_task()

        self.assertFalse(Subtask.objects.filter(pk=self.task.pk).exists())

    def test_the_milestone_stays(self):
        self.delete_task()

        self.assertTrue(TaskHeader.objects.filter(pk=self.header.pk).exists())

    def test_a_finished_task_can_go_too(self):
        """
        ⚠ ANY TASK, NOT ONLY AN OPEN ONE. He was asked and said any: a finished
          row filed against the wrong milestone is exactly the one somebody needs
          to remove.
        """
        self.task.status = Subtask.Status.DONE
        self.task.finished_on = date(2026, 8, 9)
        self.task.save(update_fields=["status", "finished_on"])

        self.delete_task()

        self.assertFalse(Subtask.objects.filter(pk=self.task.pk).exists())

    def test_deleting_a_late_task_says_the_delay_stops_counting(self):
        """
        ⚠ THE CONSEQUENCE WORTH NAMING. Days lost per reason is counted from the
          subtasks themselves — there is no separate log table — so the delay
          leaves the log with the row. Said in the message rather than found out.
        """
        self.task.status = Subtask.Status.DONE
        self.task.finished_on = self.task.planned_end + timedelta(days=4)
        self.task.delay_reason = "material"
        self.task.save(update_fields=["status", "finished_on", "delay_reason"])

        page = self.delete_task().content.decode()

        self.assertIn("no longer counted in the log", page)

    def test_an_on_time_task_is_not_told_about_the_log(self):
        page = self.delete_task().content.decode()

        self.assertNotIn("no longer counted in the log", page)

    def test_it_is_post_only(self):
        """A delete that works by being visited will be visited by a link preview."""
        self.assertEqual(
            self.client.get(reverse("task_subtask_delete", args=[self.task.pk])).status_code, 405)


class DeletingAMilestone(DeleteFixture):

    def test_an_empty_one_goes(self):
        self.delete_header(self.empty)

        self.assertFalse(TaskHeader.objects.filter(pk=self.empty.pk).exists())

    def test_one_holding_tasks_is_refused(self):
        """
        ⚠⚠ NO CASCADE. Deleting a fortnight of somebody's work from a button
           labelled with a phase name is not a decision anybody made.
        """
        self.delete_header(self.header)

        self.assertTrue(TaskHeader.objects.filter(pk=self.header.pk).exists())
        self.assertTrue(Subtask.objects.filter(pk=self.task.pk).exists())

    def test_the_refusal_says_how_many(self):
        page = self.delete_header(self.header).content.decode()

        self.assertIn("still holds 1 task", page)

    def test_the_button_is_not_drawn_on_one_holding_tasks(self):
        page = self.client.get(f"{reverse('task_board')}?project={self.project.pk}").content.decode()

        self.assertNotIn(reverse("task_header_delete", args=[self.header.pk]), page)
        self.assertIn(reverse("task_header_delete", args=[self.empty.pk]), page)


class WhoMayDelete(DeleteFixture):
    """
    ⚠ `tasks.manage`, and NOT `tasks.mine`. Those two keys answer opposite
      questions: may this person record what happened to their own work, versus
      may this person say it never happened. The engineer holds the first.
    """

    def test_a_site_engineer_cannot_even_though_it_is_their_task(self):
        engineer = self.make_user("site.del", role=Role.SITE)
        self.task.assignee = engineer
        self.task.save(update_fields=["assignee"])
        self.client.force_login(engineer)

        self.assertEqual(
            self.client.post(reverse("task_subtask_delete", args=[self.task.pk])).status_code, 403)
        self.assertTrue(Subtask.objects.filter(pk=self.task.pk).exists())

    def test_an_accountant_cannot(self):
        self.client.force_login(self.make_user("acc.del", role=Role.ACCOUNTANT))

        self.assertEqual(
            self.client.post(reverse("task_subtask_delete", args=[self.task.pk])).status_code, 403)

    def test_a_project_manager_may(self):
        self.client.force_login(self.make_user("pm.del", role=Role.PROJECT_MANAGER))
        self.delete_task()

        self.assertFalse(Subtask.objects.filter(pk=self.task.pk).exists())

    def test_the_button_is_not_drawn_for_somebody_who_cannot(self):
        self.client.force_login(self.make_user("site.del2", role=Role.SITE))

        page = self.client.get(f"{reverse('task_board')}?project={self.project.pk}").content.decode()
        self.assertNotIn(reverse("task_subtask_delete", args=[self.task.pk]), page)


class TheChartRefitsAfterwards(DeleteFixture):
    """
    ⚠ THE SPAN IS DERIVED FROM WHAT IS LEFT, so there is nothing to recalculate —
      but that is worth a test rather than an assumption, because it is exactly
      the kind of thing a cached span would get wrong.
    """

    def test_the_span_shrinks_when_the_late_row_goes(self):
        from tasks import schedule

        far = Subtask.objects.create(
            header=self.header, title="Much later", start=date(2027, 3, 1), days=5,
            created_by=self.user)
        before = schedule.build(self.project)["span"]["end"]

        far.delete()
        after = schedule.build(self.project)["span"]["end"]

        self.assertLess(after, before)

    def test_deleting_the_last_task_leaves_the_milestone_drawable(self):
        from tasks import schedule

        self.task.delete()

        chart = schedule.build(self.project)
        self.assertIsNotNone(chart)
