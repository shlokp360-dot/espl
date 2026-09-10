"""
The demonstration seeder has to keep working, because it is the first thing
somebody who clones this repository runs.

⚠ THE ACCEPTANCE TEST IS "EVERY SCREEN HAS SOMETHING ON IT". A page that is
  correct and empty looks broken to a person seeing the app for the first time,
  and they form a view of the whole system from it. So this walks all seventeen
  screens after seeding and asserts each one answers.

⚠ AND THAT `--remove` LEAVES NOTHING. The command writes to whatever database it
  is pointed at, including a real one. If the removal ever stops being exact,
  somebody's live data is what pays for it.
"""
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Role, UserProfile
from compliance.models import ComplianceDocument
from compliance import status as compliance_status
from masters.models import Material, Vendor
from projects.bom_models import Bom, PurchaseOrder, Receipt
from projects.models import Estimate, Project
from tasks.models import Subtask, TaskHeader

MEDIA = tempfile.mkdtemp()

SCREENS = [
    "launchpad", "analytics_home", "analytics_g2n", "analytics_budget", "analytics_bom",
    "analytics_payments", "analytics_tasks", "analytics_documents",
    "compliance_home", "compliance_project_default", "compliance_timeline", "compliance_master",
    "task_board", "task_schedule", "task_mine", "task_people", "task_delay_log",
    "project_list", "po_register", "master_data",
]


@override_settings(MEDIA_ROOT=MEDIA)
class TheShowcaseSeeder(TestCase):

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        User = get_user_model()
        self.boss = User.objects.create_superuser(username="mentor", password="x", email="")

    def seed(self):
        call_command("seed_showcase", verbosity=0)

    # ---- what it builds --------------------------------------------------
    def test_it_needs_nothing_imported_first(self):
        """
        ⚠ THE WHOLE POINT. Somebody who has just cloned has no spreadsheets, no
          `.env` and no master data, because none of that is committed.
        """
        self.assertEqual(Material.objects.count(), 0)
        self.seed()
        self.assertGreater(Material.objects.count(), 0)
        self.assertGreater(Vendor.objects.count(), 0)

    def test_three_won_projects_each_with_an_estimate_and_a_bom(self):
        self.seed()
        projects = Project.objects.filter(name__startswith="Showcase — ")
        self.assertEqual(projects.count(), 3)
        for project in projects:
            self.assertEqual(project.status, Project.Status.WON)
            self.assertTrue(Estimate.objects.filter(project=project).exists())
            self.assertTrue(Bom.objects.filter(project=project).exists())

    def test_documents_exist_at_every_stage(self):
        # ⚠ Otherwise the analytics stages have nothing to separate: committed,
        #   received and paid count on three different dates.
        self.seed()
        for status_value in (PurchaseOrder.Status.DRAFT, PurchaseOrder.Status.APPROVED,
                             PurchaseOrder.Status.DELIVERED, PurchaseOrder.Status.PAID):
            self.assertTrue(PurchaseOrder.objects.filter(status=status_value).exists(),
                            f"nothing is {status_value}")

    def test_the_dates_are_spread_across_months(self):
        """A seeder that stamped everything today would leave every chart flat."""
        self.seed()
        months = {order.approved_at.month for order in
                  PurchaseOrder.objects.exclude(approved_at=None)}
        self.assertGreaterEqual(len(months), 3)

    def test_required_by_is_set_so_the_vendor_scorecard_can_exist(self):
        # ⚠ It is empty on every real document today — see OPEN-BEFORE-GO-LIVE.
        self.seed()
        self.assertFalse(PurchaseOrder.objects.filter(required_by=None).exists())
        self.assertTrue(Receipt.objects.exists())

    def test_the_work_shows_every_state_the_board_can_draw(self):
        self.seed()
        self.assertTrue(Subtask.objects.filter(status=Subtask.Status.DONE).exists())
        self.assertTrue(Subtask.objects.filter(status=Subtask.Status.BLOCKED).exists())
        self.assertTrue(Subtask.objects.exclude(delay_reason="").exists(), "nothing finished late")
        self.assertTrue(Subtask.objects.exclude(original_start=None).exists(), "nothing replanned")

    def test_compliance_shows_valid_expiring_and_expired(self):
        """
        ⚠ EXPIRED IS THE STATE THE MODULE EXISTS TO PREVENT. A demonstration
          where everything is green teaches nobody what the screen is for.
        """
        self.seed()
        response = self.client.get(reverse("compliance_timeline")) if self.client.login(
            username="mentor", password="x") else None
        self.assertTrue(ComplianceDocument.objects.exclude(expires_on=None).exists())
        self.assertGreater(len(response.context["expired"]), 0)
        self.assertGreater(len(response.context["expiring"]), 0)

    def test_a_document_has_been_replaced_so_the_history_is_not_empty(self):
        self.seed()
        first = ComplianceDocument.objects.values("project", "item").annotate()
        pairs = [(row["project"], row["item"]) for row in first]
        self.assertGreater(len(pairs), len(set(pairs)), "no item has two versions")

    # ---- the trap it avoids ---------------------------------------------
    def test_a_superuser_with_no_profile_is_made_an_admin(self):
        """
        ⚠ `createsuperuser` MAKES AN ACCOUNT WITH NO ROLE, and the matrix answers
          "no role" with an almost empty launchpad. Somebody demonstrating the
          app would conclude it is broken.
        """
        self.assertFalse(UserProfile.objects.filter(user=self.boss).exists())
        self.seed()
        self.assertEqual(UserProfile.objects.get(user=self.boss).role, Role.ADMIN)

    def test_the_demo_colleagues_cannot_sign_in(self):
        # A demo account with a known password is a habit worth not starting.
        self.seed()
        User = get_user_model()
        for person in User.objects.filter(username__endswith=".demo"):
            self.assertFalse(person.has_usable_password(), person.username)

    # ---- every screen ----------------------------------------------------
    def test_every_screen_answers_after_seeding(self):
        self.seed()
        self.client.login(username="mentor", password="x")
        for name in SCREENS:
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200, f"{name} did not answer")

    def test_the_analytics_overview_is_not_all_zeroes(self):
        self.seed()
        self.client.login(username="mentor", password="x")
        context = self.client.get(reverse("analytics_home")).context
        self.assertGreater(context["paid"]["net_payable"], 0)
        self.assertGreater(context["committed"]["taxable"], 0)
        self.assertGreater(context["reserve_pct"], 0)
        self.assertGreater(context["days_lost"], 0)

    # ---- and taking it away ---------------------------------------------
    def test_remove_leaves_nothing_behind(self):
        self.seed()
        call_command("seed_showcase", "--remove", verbosity=0)

        self.assertEqual(Project.objects.filter(name__startswith="Showcase — ").count(), 0)
        self.assertEqual(PurchaseOrder.objects.count(), 0)
        self.assertEqual(TaskHeader.objects.count(), 0)
        self.assertEqual(ComplianceDocument.objects.count(), 0)
        self.assertEqual(Material.objects.filter(group__code="SHW").count(), 0)
        self.assertEqual(Vendor.objects.filter(code__startswith="VEN-S").count(), 0)
        self.assertEqual(get_user_model().objects.filter(username__endswith=".demo").count(), 0)

    def test_remove_does_not_touch_anything_else(self):
        """⚠ It writes to whatever database it is pointed at, including a real one."""
        mine = Project.objects.create(name="A real project", bua_sqft=1000)
        vendor = Vendor.objects.create(code="VEN-999", name="A real vendor", phone="9000000000")
        self.seed()
        call_command("seed_showcase", "--remove", verbosity=0)

        self.assertTrue(Project.objects.filter(pk=mine.pk).exists())
        self.assertTrue(Vendor.objects.filter(pk=vendor.pk).exists())

    def test_running_it_twice_refuses_rather_than_doubling(self):
        self.seed()
        before = Project.objects.count()
        self.seed()
        self.assertEqual(Project.objects.count(), before)

    # ---- C7: a real vendor can already hold one of the invented numbers ---
    def test_it_does_not_crash_when_a_real_vendor_already_has_that_phone(self):
        """
        ⚠ C7. This happened for real: import_masters brought in a genuine
          "Sambhav Hardware" whose phone happened to match the showcase vendor
          of the same name. `phone` is unique, so the seeder used to crash mid
          transaction. It rolled back cleanly, but the seeder has to actually
          seed, not just fail safely.
        """
        real = Vendor.objects.create(code="VEN-020", name="Sambhav Hardware",
                                      phone="9409124489", payment_terms="30 days")
        self.seed()

        demo = Vendor.objects.get(code="VEN-S01")
        self.assertNotEqual(demo.phone, real.phone)
        self.assertTrue(Vendor.objects.filter(pk=real.pk, phone="9409124489").exists(),
                         "the real vendor's own number must not be touched")
