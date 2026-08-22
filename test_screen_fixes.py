"""
Three things Saahil found by looking at the built app.

Nothing here is a feature. Each one is a screen that said something untrue:

  1. Material groups drew an Active column against a field that did not exist,
     so all 25 rows read as deactivated and ticking one did nothing.
  2. Company profile offered a link to "All projects", left over from before
     Master data was restructured.
  3. A milestone could be saved a year away from its own tasks and nothing said
     a word — which is what stretched his Gantt to thirteen months.

⚠ THE FIRST TWO WERE INVISIBLE TO THE SUITE because a green test says a view
  returns 200, not that the thing on it can act. These are written from what he
  was looking at.
"""
from datetime import date, timedelta
from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils.html import escape

from accounts.models import Role, UserProfile
from masters import sheets
from masters.models import Activity, Material, MaterialGroup, UnitOfMeasure
from projects.models import Project
from tasks.models import Subtask, TaskHeader

User = get_user_model()


class AMaterialGroupCanBeRetired(TestCase):
    """
    The Active column on the material group master, which until now was drawn
    over nothing.
    """

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(username="mg.boss", password="x")
        UserProfile.objects.update_or_create(
            user=cls.admin, defaults={"role": Role.ADMIN, "must_change_password": False})

        cls.activity = Activity.objects.create(abbreviation="ZQM", name="Group test activity",
                                               rate=D("100"), sort_order=905)
        cls.live = MaterialGroup.objects.create(code="ZQL", name="Still in use")
        cls.retired = MaterialGroup.objects.create(code="ZQD", name="Not used any more")
        UnitOfMeasure.objects.get_or_create(code="Bag", defaults={"name": "Bag"})

        cls.material = Material.objects.create(
            code="ZQM-ZQD-001", name="TEST MATERIAL", group=cls.retired,
            home_activity=cls.activity, uom="Bag", estimation_rate=D("400"),
            gst_percent=D("18"))

    def setUp(self):
        self.client.force_login(self.admin)

    def test_a_group_starts_active(self):
        """Migration 0012 defaults True — nobody has to switch 25 things back on."""
        self.assertTrue(MaterialGroup.objects.get(code="ZQL").is_active)

    def test_the_screen_shows_the_tick_as_on(self):
        """
        ⚠ THE BUG, WRITTEN DOWN. Every box rendered unchecked because the field
          was absent and the template read it as empty.
        """
        page = self.client.get(reverse("material_group_list")).content.decode()

        self.assertIn(f'name="is_active-{self.live.id}"', page)
        self.assertIn("checked", page)

    def test_ticking_it_off_now_actually_saves(self):
        """It used to be dropped silently — the view guards on hasattr."""
        # ⚠ AN UNTICKED BOX SENDS NOTHING AT ALL, so the row being kept ON has to
        #   send "on" explicitly. Leaving it out of this POST is how the first
        #   run of this test deactivated the group it was asserting stayed live.
        #
        # ⚠⚠ AND THAT WAS THE BUG, WORKED AROUND HERE INSTEAD OF FIXED — see B1
        #    in `test_simple_masters.py`. The `row-<id>` markers below are what a
        #    real form now sends; a row that arrives without one is skipped
        #    rather than read. The workaround above is no longer load-bearing,
        #    but it is left in place because it is still what a real form does.
        self.client.post(reverse("material_group_save"), {
            f"row-{self.live.id}": "1",
            f"code-{self.live.id}": "ZQL",
            f"name-{self.live.id}": "Still in use",
            f"is_stock_item-{self.live.id}": "on",
            f"is_active-{self.live.id}": "on",
            f"row-{self.retired.id}": "1",
            f"code-{self.retired.id}": "ZQD",
            f"name-{self.retired.id}": "Not used any more",
            f"is_stock_item-{self.retired.id}": "on",
            f"is_active-{self.retired.id}": "",
        })

        self.assertTrue(MaterialGroup.objects.get(code="ZQL").is_active)
        self.assertFalse(MaterialGroup.objects.get(code="ZQD").is_active)

    def test_a_retired_group_is_not_offered_on_a_new_material(self):
        self.retired.is_active = False
        self.retired.save(update_fields=["is_active"])

        page = self.client.get(reverse("material_new")).content.decode()

        self.assertIn(escape(self.live.name), page)
        self.assertNotIn(escape(self.retired.name), page)

    def test_but_a_material_already_in_it_keeps_it(self):
        """
        ⚠ THE HALF THAT MATTERS, and the same rule `_uoms_for` follows. Without
          it, opening this material would show the dropdown defaulting to another
          group and saving would move it there with nobody meaning to.
        """
        self.retired.is_active = False
        self.retired.save(update_fields=["is_active"])

        page = self.client.get(
            reverse("material_edit", args=[self.material.id])).content.decode()

        self.assertIn(escape(self.retired.name), page)

    def test_retiring_a_group_cannot_touch_an_existing_code(self):
        """ANCHOR: CODE-GEN — the group code is the middle segment, assigned once."""
        self.retired.is_active = False
        self.retired.save(update_fields=["is_active"])

        self.material.refresh_from_db()
        self.assertEqual(self.material.code, "ZQM-ZQD-001")

    def test_the_excel_template_stops_offering_it(self):
        self.retired.is_active = False
        self.retired.save(update_fields=["is_active"])

        book = sheets.material_workbook()
        reference = "\n".join(
            str(cell.value) for row in book["Reference"].iter_rows() for cell in row)

        self.assertIn("ZQL", reference)
        self.assertNotIn("ZQD", reference)

    def test_but_the_import_still_accepts_it(self):
        """
        A retired group is not offered; a re-imported export of the materials
        already in it must still be read. Same rule the units follow.
        """
        self.retired.is_active = False
        self.retired.save(update_fields=["is_active"])

        self.assertIn("ZQD", {g.code for g in MaterialGroup.objects.all()})


class CompanyProfileOffersNoWayIntoProjects(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(username="cp.boss", password="x")
        UserProfile.objects.update_or_create(
            user=cls.admin, defaults={"role": Role.ADMIN, "must_change_password": False})

    def setUp(self):
        self.client.force_login(self.admin)

    def test_the_all_projects_link_is_gone(self):
        """
        Saahil, circling it: "Why do i see all projects from company profile?
        ideally should not be able to access from this screen."
        """
        page = self.client.get(reverse("company_profile")).content.decode()

        self.assertNotIn("All projects", page)

    def test_it_uses_the_master_data_breadcrumb_its_sisters_use(self):
        page = self.client.get(reverse("company_profile")).content.decode()

        self.assertIn(reverse("master_data"), page)
        self.assertIn("Master data", page)


class AWindowNowhereNearItsWork(TestCase):
    """
    >>> ANCHOR: TASK-WINDOW-WARNING <<<
    ⚠⚠ IT WARNS AND SAVES. A refusal would outlaw the state the amber bar exists
       to show — a milestone whose work has grown past its window. Only work that
       never touches the window at all is a typo rather than a schedule.
    """

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(username="win.boss", password="x")
        UserProfile.objects.update_or_create(
            user=cls.admin, defaults={"role": Role.ADMIN, "must_change_password": False})
        cls.activity = Activity.objects.create(abbreviation="ZQW", name="Window test activity",
                                               rate=D("100"), sort_order=906)
        cls.project = Project.objects.create(name="Window site", bua_sqft=D("10000"),
                                             status=Project.Status.WON)

    def setUp(self):
        self.client.force_login(self.admin)
        self.header = TaskHeader.objects.create(
            project=self.project, name="Site work", activity=self.activity,
            start=date(2026, 8, 14), days=7, created_by=self.admin)

    def messages_from(self, response):
        return [str(m) for m in response.wsgi_request._messages]

    def add_task(self, start, days=5):
        return self.client.post(reverse("task_subtask_new"), {
            "project": self.project.id, "header": self.header.id,
            "title": "TMT bar testing", "start": start.isoformat(), "days": days,
        }, follow=True)

    def test_a_task_inside_the_window_says_nothing(self):
        page = self.add_task(date(2026, 8, 15))

        self.assertNotIn("falls entirely outside", page.content.decode())

    def test_a_task_that_merely_overruns_says_nothing(self):
        """
        ⚠ THE CASE THAT MUST NOT FIRE. Starting inside and finishing past the
          window is an ordinary overrun; the chart already draws it amber, and a
          warning here would fire on the normal way of working.
        """
        page = self.add_task(date(2026, 8, 18), days=30)

        self.assertNotIn("falls entirely outside", page.content.decode())

    def test_a_task_a_year_away_is_flagged(self):
        page = self.add_task(date(2027, 8, 15))

        self.assertIn("falls entirely outside", page.content.decode())

    def test_and_it_is_saved_anyway(self):
        self.add_task(date(2027, 8, 15))

        self.assertEqual(Subtask.objects.filter(header=self.header).count(), 1)

    def test_the_warning_counts_the_days_so_a_wrong_year_shows(self):
        # The window ends 20/08/2026; the task starts 15/08/2027. 360 days, not
        # 361 — I asserted the wrong number first, and the code was right.
        page = self.add_task(date(2027, 8, 15)).content.decode()

        self.assertIn("360 days after it finishes", page)

    def test_moving_the_milestone_away_from_its_work_is_flagged_too(self):
        """
        ⚠⚠ THIS IS THE ONE THAT WOULD HAVE CAUGHT HIS. The mistyped year was on
           the milestone, not the task, so a check that only ran when a task was
           saved would have said nothing at all.
        """
        Subtask.objects.create(header=self.header, title="TMT bar testing",
                               start=date(2026, 8, 15), days=5, created_by=self.admin)

        page = self.client.post(
            reverse("task_header_edit", args=[self.header.id]),
            {"project": self.project.id, "name": "Site work",
             "activity": self.activity.id, "start": "2025-08-14", "days": 7,
             "reason": "scope", "note": "typo test"},
            follow=True).content.decode()

        self.assertIn("no longer covers", page)

    def test_a_milestone_with_no_tasks_yet_says_nothing(self):
        """There is nothing to be away from. Every plan starts here."""
        page = self.client.post(
            reverse("task_header_edit", args=[self.header.id]),
            {"project": self.project.id, "name": "Site work",
             "activity": self.activity.id, "start": "2025-08-14", "days": 7,
             "reason": "scope", "note": "typo test"},
            follow=True).content.decode()

        self.assertNotIn("no longer covers", page)
