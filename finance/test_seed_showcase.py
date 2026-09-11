"""
The finance and drawings demo seeder has to keep working: it is what somebody
runs to see the Finance & Accounting tabs and the Drawings repository with
something on them.

⚠ THE ACCEPTANCE TEST IS "EVERY TAB HAS ROWS" — Overview, Bills, RA bills,
  Payments, Vendor ledger, TDS, and the Drawings overview with BOTH sections —
  and that `--remove` leaves the finance and drawings tables exactly as empty
  as it found them, with seed_showcase's own data still in place.
"""
import shutil
import tempfile
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from drawings.models import Architect, Drawing, DrawingRevision
from finance.models import RABill, VendorInvoice, VendorPayment
from masters.models import Vendor
from projects.bom_models import BomLine, PurchaseOrder
from projects.models import Project

MEDIA = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=MEDIA)
class TheFinanceShowcaseSeeder(TestCase):

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        User = get_user_model()
        User.objects.create_superuser(username="mentor", password="x", email="")

    def seed_all(self):
        quiet = StringIO()
        call_command("seed_showcase", stdout=quiet)          # also makes mentor an Admin
        call_command("seed_sales_showcase", stdout=quiet)
        call_command("seed_finance_showcase", stdout=quiet)
        self.client.login(username="mentor", password="x")

    def test_it_refuses_without_the_showcase_projects(self):
        err = StringIO()
        call_command("seed_finance_showcase", stderr=err)
        self.assertIn("seed_showcase", err.getvalue())
        self.assertEqual(VendorInvoice.objects.count(), 0)

    def test_every_finance_tab_and_the_drawings_overview_have_rows(self):
        self.seed_all()

        # Bills: invoices on POs and approved RA bills on WOs, at every status.
        rows = self.client.get(reverse("finance_bills")).context["rows"]
        self.assertGreaterEqual(len(rows), 10)
        self.assertEqual({r["status"] for r in rows}, {"open", "part_paid", "settled"})
        self.assertTrue(any(r["kind"] == "wo" for r in rows))
        self.assertTrue(any(r["tds"] > 0 for r in rows))

        # Overview: something payable, something overdue, something paid this month.
        kpis = self.client.get(reverse("finance_home")).context["kpis"]
        self.assertGreater(kpis["payable_now"], 0)
        self.assertGreater(kpis["overdue_count"], 0)
        self.assertGreater(kpis["paid_month"], 0)
        self.assertGreater(kpis["tds_quarter"], 0)

        # RA bills: draft, certified, approved and paid, with an advance recovered.
        rows = self.client.get(reverse("finance_ra_bills")).context["rows"]
        self.assertEqual({r["bill"].status for r in rows},
                         {"draft", "certified", "approved", "paid"})
        self.assertTrue(any(r["ladder"]["advance_recovery"] > 0 for r in rows))
        work_order = PurchaseOrder.objects.get(number="WO-S01")
        context = self.client.get(reverse("finance_wo", args=[work_order.id])).context
        self.assertGreater(context["s"]["advance_recovered"], 0)

        # Payments: this month by default, and it is not empty.
        rows = self.client.get(reverse("finance_payments")).context["rows"]
        self.assertGreater(len(rows), 0)
        self.assertTrue(VendorPayment.objects.filter(kind=VendorPayment.Kind.ADVANCE).exists())
        self.assertTrue(VendorPayment.objects.filter(tds_amount__gt=0).count() >= 2)

        # Vendor ledger for the contractor: order, advance, bills, payments, ties.
        contractor = Vendor.objects.get(code="VEN-S07")
        ledger = self.client.get(reverse("finance_vendor_ledger"),
                                 {"vendor": contractor.id}).context["ledger"]
        self.assertGreaterEqual(len(ledger["rows"]), 5)
        self.assertTrue(ledger["ties"])

        # TDS: the current quarter has rows.
        report = self.client.get(reverse("finance_tds")).context["report"]
        self.assertGreater(len(report["rows"]), 0)
        self.assertGreater(report["totals"]["tds"], 0)

        # Drawings: both sections of the overview, and a register with the five groups.
        context = self.client.get(reverse("drawings_home")).context
        self.assertEqual(len(context["live"]), 3)
        self.assertEqual(len(context["completed"]), 1)
        self.assertGreater(context["required"], 0)
        self.assertGreater(context["approved"], 0)
        self.assertGreater(context["completed"][0]["compliance"], 0)
        project = Project.objects.filter(name__startswith="Showcase — ",
                                         status=Project.Status.WON).first()
        groups = self.client.get(reverse("drawings_register", args=[project.id])).context["groups"]
        self.assertEqual({g["group"].code for g in groups}, {"ARC", "STR", "SUR", "PAS", "MEP"})
        # A revision is downloadable.
        revision = DrawingRevision.objects.filter(drawing__project=project).first()
        self.assertEqual(self.client.get(reverse("drawings_download", args=[revision.id]))
                         .status_code, 200)

    def test_running_it_twice_refuses_rather_than_doubling(self):
        self.seed_all()
        before = VendorInvoice.objects.count()
        err = StringIO()
        call_command("seed_finance_showcase", stderr=err)
        self.assertIn("--remove", err.getvalue())
        self.assertEqual(VendorInvoice.objects.count(), before)

    def test_remove_leaves_the_finance_and_drawings_tables_empty(self):
        self.seed_all()
        orders_before = PurchaseOrder.objects.exclude(number__startswith="WO-S").count()
        statuses_before = dict(PurchaseOrder.objects.exclude(number__startswith="WO-S")
                               .values_list("number", "status"))
        bom_lines_before = BomLine.objects.exclude(vendor__code__in=["VEN-S07", "VEN-S08"]).count()

        call_command("seed_finance_showcase", "--remove", stdout=StringIO())

        self.assertEqual(VendorInvoice.objects.count(), 0)
        self.assertEqual(VendorPayment.objects.count(), 0)
        self.assertEqual(RABill.objects.count(), 0)
        self.assertEqual(Drawing.objects.count(), 0)
        self.assertEqual(DrawingRevision.objects.count(), 0)
        self.assertEqual(Architect.objects.count(), 0)
        self.assertFalse(PurchaseOrder.objects.filter(number__startswith="WO-S").exists())
        self.assertFalse(Vendor.objects.filter(code__in=["VEN-S07", "VEN-S08"]).exists())
        self.assertFalse(Project.objects.filter(status=Project.Status.COMPLETED).exists())
        # seed_showcase's own rows are exactly as they were.
        self.assertEqual(PurchaseOrder.objects.count(), orders_before)
        self.assertEqual(dict(PurchaseOrder.objects.values_list("number", "status")), statuses_before)
        self.assertEqual(BomLine.objects.count(), bom_lines_before)
        self.assertEqual(Project.objects.filter(name__startswith="Showcase — ").count(), 3)

        # And the other two seeders can still take theirs away afterwards.
        call_command("seed_sales_showcase", "--remove", stdout=StringIO())
        call_command("seed_showcase", "--remove", stdout=StringIO())
        self.assertEqual(Project.objects.count(), 0)
        self.assertEqual(Vendor.objects.filter(code__startswith="VEN-S").count(), 0)
