"""
Capturing what a vendor actually charged, and using it next time.

>>> ANCHOR: VENDOR-RATE-CAPTURE <<<
Saahil, from his own review: "whenever a PO is created and is approved with the
vendor rate and the material, that is captured in a vendor material combination
so that value can be used as a reference for vendor rates in BOM. Was that not
the situation here?"

It was the situation described in the model's own docstring — "written back here
on approval" — and nothing ever did it. The table stayed empty on a live database
holding approved, delivered and paid orders, while the screen said rates "appear
as purchase orders are raised".

⚠⚠ THE FALLBACK CHANGE IS THE PART THAT MOVES MONEY, not the capture. A BOM line
   naming a vendor with no typed rate used to fall back to the planning rate and
   therefore always reported 0.0% variance — the plan measured against itself.
   It now falls back to the rate last paid. That is decision A of two put to him,
   and these tests are what say the ladder is typed → captured → planning and not
   some other order.
"""
from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from accounts.models import Role, UserProfile
from masters.models import (Activity, DocumentType, Material, MaterialGroup, Vendor,
                            VendorGroup, VendorRate)
from projects import bom_calc, po_service
from projects.bom_models import Bom, BomLine, PurchaseOrder, PurchaseOrderLine
from projects.models import Project

User = get_user_model()


class VendorRateFixture(TestCase):
    """Shared scaffolding: one project, one BOM line, one vendor to buy from."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(username="rate.boss", password="x")
        UserProfile.objects.update_or_create(
            user=cls.admin, defaults={"role": Role.ADMIN, "must_change_password": False})

        # ⚠ BUG 19 — migration 0003 seeds the real activity master, so RCC, PLM
        #   and sixteen others are taken before this runs. ZQ* is not a trade.
        cls.activity = Activity.objects.create(abbreviation="ZQR", name="Rate test activity",
                                               rate=D("100"), sort_order=904)
        group = MaterialGroup.objects.create(code="ZQR", name="Rate test group")
        cls.material = Material.objects.create(
            code="ZQR-ZQR-001", name="TEST CEMENT", group=group, home_activity=cls.activity,
            uom="Bag", estimation_rate=D("400"), gst_percent=D("28"))
        cls.other_material = Material.objects.create(
            code="ZQR-ZQR-002", name="TEST STEEL", group=group, home_activity=cls.activity,
            uom="Kg", estimation_rate=D("70"), gst_percent=D("18"))

        vendor_group = VendorGroup.objects.create(name="Rate test suppliers")
        cls.vendor = Vendor.objects.create(code="VEN-R99", name="Echo Traders", phone="9000000098",
                                           group=vendor_group, gst_number="24AAAAA0000A1Z5")
        cls.other_vendor = Vendor.objects.create(code="VEN-R98", name="Foxtrot Supply",
                                                 phone="9000000097", group=vendor_group,
                                                 gst_number="24BBBBB0000B1Z5")

        cls.project = Project.objects.create(name="Rate site", bua_sqft=D("10000"))
        cls.bom = Bom.objects.create(project=cls.project, generated_by=cls.admin)
        cls.line = BomLine.objects.create(
            bom=cls.bom, activity=cls.activity, material=cls.material,
            planned_qty=D("100"), vendor=cls.vendor, sort_order=1)

    def order_for(self, material=None, vendor=None, quantity="10", rate="340",
                  discount="0", document_type=DocumentType.PO, number=None,
                  bom_line=None):
        """A draft order with one line, ready to approve."""
        vendor = vendor or self.vendor
        if bom_line is None:
            bom_line = self.line if (material or self.material) == self.material else None
        if bom_line is None:
            bom_line = BomLine.objects.create(
                bom=self.bom, activity=self.activity, material=material,
                planned_qty=D("50"), vendor=vendor, sort_order=2)

        order = PurchaseOrder.objects.create(
            number=number or f"ZQR-{PurchaseOrder.objects.count() + 1:04d}",
            project=self.project, vendor=vendor, document_type=document_type,
            created_by=self.admin)
        PurchaseOrderLine.objects.create(
            purchase_order=order, bom_line=bom_line, quantity=D(quantity),
            rate=D(rate), discount_pct=D(discount), gst_percent=D("28"))
        return order


class ApprovalCapturesTheRate(VendorRateFixture):

    def test_approving_writes_the_vendor_and_material_row(self):
        po_service.approve(self.order_for(rate="340"), user=self.admin)

        captured = VendorRate.objects.get(vendor=self.vendor, material=self.material)
        self.assertEqual(captured.rate, D("340.00"))

    def test_a_draft_captures_nothing(self):
        """A document that may never be sent is not evidence of a price."""
        self.order_for(rate="340")
        self.assertFalse(VendorRate.objects.exists())

    def test_the_rate_is_net_of_the_line_discount(self):
        """
        ⚠ HIS DECISION, AND IT IS THE WHOLE COMPARISON. "340 with 5% off" and
          "323 flat" are the same purchase. Capturing the quoted figure would
          make a vendor who discounts look dearer than one who does not.
        """
        po_service.approve(self.order_for(rate="340", discount="5"), user=self.admin)

        self.assertEqual(VendorRate.objects.get().rate, D("323.00"))

    def test_a_second_order_replaces_the_row_rather_than_adding_one(self):
        """His words: "we should do like SAP, if the combination exist, we replace it"."""
        po_service.approve(self.order_for(rate="340"), user=self.admin)
        second = self.order_for(rate="365", bom_line=self.line)
        po_service.approve(second, user=self.admin)

        self.assertEqual(VendorRate.objects.count(), 1)
        row = VendorRate.objects.get()
        self.assertEqual(row.rate, D("365.00"))
        self.assertEqual(row.source_po_line.purchase_order, second)

    def test_the_row_says_which_order_proved_it(self):
        order = self.order_for(rate="340")
        po_service.approve(order, user=self.admin)

        self.assertEqual(VendorRate.objects.get().source_po_line.purchase_order, order)

    def test_two_vendors_for_one_material_are_two_rows(self):
        """The point of the table: comparing what each of them charges."""
        po_service.approve(self.order_for(rate="340"), user=self.admin)
        second_line = BomLine.objects.create(
            bom=self.bom, activity=self.activity, material=self.material,
            planned_qty=D("50"), vendor=self.other_vendor, sort_order=3)
        po_service.approve(self.order_for(rate="310", vendor=self.other_vendor,
                                          bom_line=second_line), user=self.admin)

        self.assertEqual(VendorRate.objects.filter(material=self.material).count(), 2)

    def test_a_work_order_captures_too(self):
        """A contractor's rate for a scope is the same question as a bag of cement."""
        po_service.approve(self.order_for(rate="250", document_type=DocumentType.WO),
                           user=self.admin)

        self.assertEqual(VendorRate.objects.get().rate, D("250.00"))

    def test_a_zero_quantity_line_does_not_divide_by_zero(self):
        """
        It should not survive validation. This is the only division in the write
        path, and an exception here would fail an approval that is otherwise good.
        """
        po_service.approve(self.order_for(quantity="0", rate="340"), user=self.admin)

        self.assertFalse(VendorRate.objects.exists())


class TheBomUsesTheCapturedRate(VendorRateFixture):
    """
    >>> ANCHOR: VENDOR-RATE-CAPTURE <<<
    The fallback ladder, which is where the money moves.
    """

    def setUp(self):
        VendorRate.objects.update_or_create(
            vendor=self.vendor, material=self.material, defaults={"rate": D("340")})

    def test_a_typed_rate_still_wins(self):
        """Nothing overrules what a person typed on the line."""
        self.line.vendor_rate = D("999")
        self.line.save(update_fields=["vendor_rate"])

        self.assertEqual(bom_calc.effective_vendor_rate(self.line), D("999"))

    def test_a_blank_rate_now_uses_what_the_vendor_last_charged(self):
        self.line.vendor_rate = None
        self.line.save(update_fields=["vendor_rate"])

        self.assertEqual(bom_calc.effective_vendor_rate(self.line), D("340"))

    def test_with_no_captured_rate_it_is_still_the_planning_rate(self):
        """The old behaviour survives untouched where there is nothing to improve on."""
        VendorRate.objects.all().delete()
        self.line.vendor_rate = None
        self.line.save(update_fields=["vendor_rate"])

        self.assertEqual(bom_calc.effective_vendor_rate(self.line), D("400"))

    def test_a_line_with_no_vendor_ignores_the_master_entirely(self):
        """Nothing has been agreed with anybody, so there is no last paid."""
        self.line.vendor = None
        self.line.vendor_rate = None
        self.line.save(update_fields=["vendor", "vendor_rate"])

        self.assertEqual(bom_calc.effective_vendor_rate(self.line), D("400"))

    def test_variance_stops_measuring_the_plan_against_itself(self):
        """
        ⚠ WHY HE RAISED IT. Every line on his screen read 0.0% because a blank
          rate fell back to the planning rate and was then compared against it.
          400 planned, 340 paid, is 15% under.
        """
        self.line.vendor_rate = None
        self.line.save(update_fields=["vendor_rate"])

        self.assertEqual(bom_calc.rate_variance(self.line), D("-0.15"))

    def test_the_benchmark_is_still_the_planning_rate(self):
        """Only the actual side of the comparison changed."""
        self.line.planned_rate = D("500")
        self.line.vendor_rate = None
        self.line.save(update_fields=["planned_rate", "vendor_rate"])

        # 500 planned for this project, 340 paid: 32% under. Not the master's 400.
        self.assertEqual(bom_calc.rate_variance(self.line), D("-0.32"))

    def test_po_value_follows_the_captured_rate(self):
        # ⚠ THE FIELD IS `order_qty_override`. Written from memory as
        #   `order_qty_typed` first, which is bug 21 again: read the model.
        self.line.vendor_rate = None
        self.line.order_qty_override = D("10")
        self.line.save(update_fields=["vendor_rate", "order_qty_override"])

        self.assertEqual(bom_calc.po_value(self.line), D("3400"))

    def test_figures_for_reports_the_rate_to_suggest(self):
        self.line.vendor_rate = None
        self.line.save(update_fields=["vendor_rate"])

        figures = bom_calc.figures_for([self.line])[0]
        self.assertEqual(figures["captured_rate"], D("340"))
        self.assertEqual(figures["vendor_rate"], D("340"))


class TheLookupDoesNotGrowWithTheRows(VendorRateFixture):
    """
    >>> ANCHOR: BOM-CALC-BULK <<<
    ⚠⚠ THE REASON THIS TEST EXISTS. effective_vendor_rate is called for every row
       on the BOM screen. A lookup inside it is one query per row, which is bugs
       3, 9 and 10 — and the 618-query screen that taught this codebase the
       lesson in the first place. The count below must not move with the number
       of lines.
    """

    #: ⚠ BUG 19 AGAIN, AND I WROTE IT AGAIN. Two calls in one test reused
    #: ZQR-ZQR-100 upwards and collided on the material code's unique
    #: constraint. A counter that never rewinds is the fix.
    made = 0

    def make_lines(self, how_many):
        lines = []
        for _ in range(how_many):
            index = self.__class__.made
            self.__class__.made += 1
            material = Material.objects.create(
                code=f"ZQR-ZQR-1{index:03d}", name=f"TEST MATERIAL {index}",
                group=MaterialGroup.objects.get(code="ZQR"), home_activity=self.activity,
                uom="Bag", estimation_rate=D("400"), gst_percent=D("28"))
            lines.append(BomLine.objects.create(
                bom=self.bom, activity=self.activity, material=material,
                planned_qty=D("10"), vendor=self.vendor, sort_order=100 + index))
            VendorRate.objects.create(vendor=self.vendor, material=material, rate=D("340"))
        return lines

    def test_one_query_whether_there_are_three_lines_or_thirty(self):
        # ⚠ THE ROWS ARE MADE OUTSIDE THE BLOCK. Creating them inside counts the
        #   INSERTs as if the lookup had made them — which is how this test first
        #   read "13 queries" and looked like a real regression.
        three = self.make_lines(3)
        thirty = self.make_lines(30)

        with self.assertNumQueries(1):
            bom_calc.bulk_vendor_rates(three)

        with self.assertNumQueries(1):
            bom_calc.bulk_vendor_rates(thirty)

    def test_lines_without_a_vendor_ask_nothing_at_all(self):
        for line in self.make_lines(5):
            line.vendor = None
            line.save(update_fields=["vendor"])
        # ⚠ list() OUTSIDE THE BLOCK. A queryset is lazy, so evaluating it inside
        #   would count fetching the lines as a query the lookup made.
        lines = list(BomLine.objects.filter(vendor__isnull=True))

        with self.assertNumQueries(0):
            bom_calc.bulk_vendor_rates(lines)


class TheBackfill(VendorRateFixture):

    def test_it_reads_orders_already_approved(self):
        order = self.order_for(rate="340")
        order.status = PurchaseOrder.Status.APPROVED
        order.approved_at = timezone.now()
        order.save(update_fields=["status", "approved_at"])

        call_command("backfill_vendor_rates")

        self.assertEqual(VendorRate.objects.get().rate, D("340.00"))

    def test_the_newest_order_wins(self):
        """
        ⚠ OLDEST FIRST, so the most recent document is the one left standing.
          Processing in an arbitrary order would leave whichever happened to come
          last, and "last processed" is not "most recent".
        """
        older = self.order_for(rate="300", number="ZQR-OLD")
        older.status = PurchaseOrder.Status.APPROVED
        older.approved_at = timezone.now() - timezone.timedelta(days=30)
        older.save(update_fields=["status", "approved_at"])

        newer = self.order_for(rate="365", number="ZQR-NEW", bom_line=self.line)
        newer.status = PurchaseOrder.Status.PAID
        newer.approved_at = timezone.now()
        newer.save(update_fields=["status", "approved_at"])

        call_command("backfill_vendor_rates")

        self.assertEqual(VendorRate.objects.get().rate, D("365.00"))

    def test_drafts_are_left_out(self):
        self.order_for(rate="340")

        call_command("backfill_vendor_rates")

        self.assertFalse(VendorRate.objects.exists())

    def test_running_it_twice_changes_nothing(self):
        order = self.order_for(rate="340")
        order.status = PurchaseOrder.Status.APPROVED
        order.approved_at = timezone.now()
        order.save(update_fields=["status", "approved_at"])

        call_command("backfill_vendor_rates")
        call_command("backfill_vendor_rates")

        self.assertEqual(VendorRate.objects.count(), 1)

    def test_dry_run_writes_nothing(self):
        order = self.order_for(rate="340")
        order.status = PurchaseOrder.Status.APPROVED
        order.approved_at = timezone.now()
        order.save(update_fields=["status", "approved_at"])

        call_command("backfill_vendor_rates", "--dry-run")

        self.assertFalse(VendorRate.objects.exists())
