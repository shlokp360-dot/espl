"""
The RA bill ladder, rung by rung, on a worked example.

>>> ANCHOR: FIN-CALC <<<
⚠ AWKWARD NUMBERS ON PURPOSE — three lines at three GST rates, a line discount
  with a decimal in it, a deduction and a TDS rate with decimals, and a
  mobilisation advance that does not divide evenly into the contract. Round
  figures would pass against arithmetic that is quietly wrong.

⚠ EVERY EXPECTED FIGURE BELOW WAS WORKED OUT BY HAND (well — step by step with
  a calculator, half-up at each step) and typed in. A test that re-ran the
  ladder to get its expectations would be a second implementation free to be
  wrong in the same direction as the first.

THE FIXTURE
    Work order, three lines:
      L1  100 Nos @ 333.33   GST 18%  no discount
      L2   40 Nos @ 1249.99  GST 12%  5.5% discount
      L3   10 Nos @ 2000.00  GST 5%   no discount
    Order taxable 100,582.62. Deduction 2.35% post-tax, TDS 1.75% (194C),
    retention 0% (SWITCHED OFF — customer, 11 Sep 2026), mobilisation advance
    10,000, DLP 12 months.

    Bill 1: 50 / 20 / 4.5 certified.  Bill 2 (final): 50 / 20 / 5 certified.

⚠ ONE TEST KEEPS THE RETENTION RUNG HONEST: `TheLadderStillHandlesRetention`
  raises the same order at 10% and checks the rung, its base and the held
  figure. The feature is off; the arithmetic is not allowed to rot.
"""
from datetime import date
from decimal import Decimal as D

from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from accounts.testing import AuthedTestCase
from masters.models import Activity, DocumentType, Material, MaterialGroup, Vendor, VendorGroup
from projects.bom_models import Bom, BomLine, PurchaseOrder, PurchaseOrderLine, Receipt
from projects.models import Project
from projects import po_service
from projects.po_service import POError

from finance import calc, services
from finance.models import RABill, VendorPayment
from finance.services import FinanceError


class LadderFixture(AuthedTestCase):

    @classmethod
    def setUpTestData(cls):
        cls.activity = Activity.objects.create(abbreviation="ZQF", name="ZQ Finance activity",
                                               rate=D("100"), sort_order=931)
        group = MaterialGroup.objects.create(code="ZQF", name="ZQ Finance group")
        vendor_group = VendorGroup.objects.create(name="ZQ Finance contractors")
        cls.vendor = Vendor.objects.create(
            code="VEN-ZQF", name="ZQ Finance Contractor", phone="9000000371",
            group=vendor_group, gst_number="24AAAAA0000A1Z5",
            default_document_type=DocumentType.WO)
        cls.project = Project.objects.create(name="ZQ Finance site", bua_sqft=D("10000"),
                                             status=Project.Status.WON)
        cls.bom = Bom.objects.create(project=cls.project)
        cls.materials = []
        for index in range(1, 4):
            cls.materials.append(Material.objects.create(
                code=f"ZQF-ZQF-{index:03d}", name=f"ZQ FINANCE SCOPE {index}", group=group,
                home_activity=cls.activity, uom="Nos", estimation_rate=D("100"),
                gst_percent=D("18")))

    def setUp(self):
        super().setUp()
        self.wo = self.make_wo()

    def make_wo(self, number="ZQF-0001", doc_type=DocumentType.WO, approve=True,
                retention="0", tds_section="194C", vendor=None, project=None):
        order = PurchaseOrder.objects.create(
            number=number, project=project or self.project, vendor=vendor or self.vendor,
            document_type=doc_type, created_by=self.user, deduction_pct=D("2.35"),
            tds_pct=D("1.75"), tds_section=tds_section, retention_pct=D(retention),
            mobilisation_advance=D("10000"), dlp_months=12)
        for index, (qty, rate, gst, disc) in enumerate([
                ("100", "333.33", "18", "0"),
                ("40", "1249.99", "12", "5.5"),
                ("10", "2000", "5", "0")]):
            bom_line = BomLine.objects.create(
                bom=self.bom, activity=self.activity, material=self.materials[index],
                planned_qty=D("100"), vendor=self.vendor, sort_order=index)
            PurchaseOrderLine.objects.create(
                purchase_order=order, bom_line=bom_line, quantity=D(qty), rate=D(rate),
                discount_pct=D(disc), gst_percent=D(gst))
        if approve:
            po_service.approve(order, user=self.user)
        return order

    def line_ids(self, order):
        return [line.id for line in order.lines.order_by("id")]

    def bill(self, order, claimed, certified=None, is_final=False):
        ids = self.line_ids(order)
        bill = services.create_ra_bill(order, self.user, dict(zip(ids, claimed)),
                                       is_final=is_final, bill_date=date(2026, 9, 1))
        if certified is not None:
            line_ids = [line.id for line in bill.lines.order_by("id")]
            services.certify(bill, self.user, dict(zip(line_ids, certified)))
        return bill


class TheFirstBill(LadderFixture):

    def setUp(self):
        super().setUp()
        self.first = self.bill(self.wo, ["50", "20", "4.5"], ["50", "20", "4.5"])
        self.ladder = calc.bill_figures(self.first)

    def test_the_order_taxable_the_advance_is_spread_over(self):
        self.assertEqual(self.wo.totals()["taxable"], D("100582.62"))

    def test_line_figures(self):
        rows = self.ladder["lines"]
        self.assertEqual([r["gross"] for r in rows], [D("16666.50"), D("24999.80"), D("9000.00")])
        self.assertEqual([r["discount"] for r in rows], [D("0.00"), D("1374.99"), D("0.00")])
        self.assertEqual([r["taxable"] for r in rows], [D("16666.50"), D("23624.81"), D("9000.00")])
        self.assertEqual([r["gst"] for r in rows], [D("2999.97"), D("2834.98"), D("450.00")])

    def test_every_rung(self):
        ladder = self.ladder
        self.assertEqual(ladder["gross"], D("50666.30"))
        self.assertEqual(ladder["discount"], D("1374.99"))
        self.assertEqual(ladder["taxable"], D("49291.31"))
        self.assertEqual(ladder["gst"], D("6284.95"))
        self.assertEqual(ladder["cgst"], D("3142.48"))
        self.assertEqual(ladder["sgst"], D("3142.47"))
        self.assertEqual(ladder["invoice_value"], D("55576.26"))
        self.assertEqual(ladder["deduction"], D("1306.04"))          # 2.35% of invoice value
        self.assertEqual(ladder["retention"], D("0.00"))             # switched off
        self.assertEqual(ladder["advance_outstanding"], D("10000.00"))
        self.assertEqual(ladder["advance_recovery"], D("4900.58"))   # 49291.31 × 10000 ÷ 100582.62
        self.assertEqual(ladder["payable"], D("49370"))              # 49369.64 to the rupee
        self.assertEqual(ladder["round_off"], D("0.36"))
        self.assertEqual(ladder["tds"], D("862.60"))                 # 1.75% of taxable
        self.assertEqual(ladder["net_payable"], D("48507.40"))

    def test_line_figures_tie_to_the_bill(self):
        rows = self.ladder["lines"]
        for key in ("gross", "discount", "taxable", "gst"):
            self.assertEqual(sum(r[key] for r in rows), self.ladder[key], key)
        self.assertEqual(self.ladder["cgst"] + self.ladder["sgst"], self.ladder["gst"])
        self.assertEqual(self.ladder["taxable"] + self.ladder["gst"], self.ladder["invoice_value"])
        self.assertEqual(
            self.ladder["invoice_value"] - self.ladder["deduction"] - self.ladder["retention"]
            - self.ladder["advance_recovery"] + self.ladder["round_off"], self.ladder["payable"])
        self.assertEqual(self.ladder["payable"] - self.ladder["tds"], self.ladder["net_payable"])

    def test_the_claim_drives_the_ladder_until_certified(self):
        bill = RABill.objects.get(pk=self.first.pk)
        bill.lines.update(certified_qty=None)
        bill.lines.filter(po_line__quantity=D("100")).update(claimed_qty=D("60"))
        ladder = calc.bill_figures(bill)
        self.assertEqual(ladder["lines"][0]["qty"], D("60"))
        self.assertFalse(ladder["certified"])

    def test_bulk_matches_single(self):
        self.assertEqual(calc.bulk_bill_figures([self.first])[self.first.id]["net_payable"],
                         self.ladder["net_payable"])

    def test_nothing_counts_to_date_before_approval(self):
        summary = calc.cumulative(self.wo)
        self.assertEqual(summary["certified_to_date"], D("0"))
        self.assertEqual(summary["retention_held"], D("0"))
        self.assertEqual(summary["lines"][0]["certified_to_date"], D("0"))
        self.assertIsNone(summary["dlp_end"])


class TheSecondAndFinalBill(LadderFixture):

    def setUp(self):
        super().setUp()
        self.first = self.bill(self.wo, ["50", "20", "4.5"], ["50", "20", "4.5"])
        services.approve(self.first, self.user)

    def test_receipts_equal_the_certified_quantities(self):
        received = {r.po_line_id: r.quantity for r in Receipt.objects.filter(
            po_line__purchase_order=self.wo)}
        ids = self.line_ids(self.wo)
        self.assertEqual([received[i] for i in ids], [D("50"), D("20"), D("4.5")])
        self.assertTrue(all(r.source == Receipt.Source.RA_BILL
                            for r in Receipt.objects.filter(po_line__purchase_order=self.wo)))

    def test_cumulative_after_the_first_bill(self):
        summary = calc.cumulative(self.wo)
        self.assertEqual(summary["certified_to_date"], D("49291.31"))
        self.assertEqual(summary["billed_to_date"], D("55576.26"))
        self.assertEqual(summary["retention_held"], D("0.00"))
        self.assertEqual(summary["advance_recovered"], D("4900.58"))
        self.assertEqual(summary["advance_outstanding"], D("5099.42"))
        self.assertEqual([row["remaining"] for row in summary["lines"]],
                         [D("50"), D("20"), D("5.5")])
        self.assertEqual(summary["payable_now"], D("48507.40"))
        self.assertEqual(self.wo.status, PurchaseOrder.Status.APPROVED)   # not final

    def test_over_certification_is_refused_naming_the_line_and_the_excess(self):
        second = self.bill(self.wo, ["50", "20", "6"])
        ids = [line.id for line in second.lines.order_by("id")]
        with self.assertRaises(FinanceError) as refusal:
            services.certify(second, self.user, dict(zip(ids, ["50", "20", "6"])))
        message = str(refusal.exception)
        self.assertIn("ZQF-ZQF-003", message)
        self.assertIn("0.500", message)          # 4.5 + 6 = 10.5, over by 0.5
        self.assertEqual(RABill.objects.get(pk=second.pk).status, RABill.Status.DRAFT)

    def test_the_final_bill_recovers_the_whole_advance_remainder(self):
        second = self.bill(self.wo, ["50", "20", "5"], ["50", "20", "5"], is_final=True)
        ladder = calc.bill_figures(second)
        self.assertEqual(ladder["gross"], D("51666.30"))
        self.assertEqual(ladder["taxable"], D("50291.31"))
        self.assertEqual(ladder["gst"], D("6334.95"))
        self.assertEqual(ladder["invoice_value"], D("56626.26"))
        self.assertEqual(ladder["deduction"], D("1330.72"))
        self.assertEqual(ladder["retention"], D("0.00"))
        self.assertEqual(ladder["advance_outstanding"], D("5099.42"))
        # Pro rata would be 5000.00; a final bill takes whatever is left.
        self.assertEqual(ladder["advance_recovery"], D("5099.42"))
        self.assertEqual(ladder["payable"], D("50196"))              # 50196.12 to the rupee
        self.assertEqual(ladder["round_off"], D("-0.12"))
        self.assertEqual(ladder["tds"], D("880.10"))
        self.assertEqual(ladder["net_payable"], D("49315.90"))

    def test_the_final_bill_flips_the_work_order_to_completed_then_paid(self):
        second = self.bill(self.wo, ["50", "20", "5"], ["50", "20", "5"], is_final=True)
        services.approve(second, self.user)
        self.wo.refresh_from_db()
        self.assertEqual(self.wo.status, PurchaseOrder.Status.DELIVERED)
        self.assertEqual(self.wo.delivered_by, self.user)
        self.assertIsNotNone(self.wo.delivered_at)
        # Receipts are the certified quantities, not the ordered ones.
        received = {r.po_line_id: sum(x.quantity for x in Receipt.objects.filter(po_line=r.po_line))
                    for r in Receipt.objects.filter(po_line__purchase_order=self.wo)}
        self.assertEqual([received[i] for i in self.line_ids(self.wo)],
                         [D("100"), D("40"), D("9.5")])

        summary = calc.cumulative(self.wo)
        self.assertEqual(summary["retention_held"], D("0.00"))
        self.assertEqual(summary["advance_recovered"], D("10000.00"))
        self.assertEqual(summary["dlp_end"], calc._add_months(timezone.now().date(), 12))

        # Pay the first bill in two parts, the second in one.
        services.record_ra_payment(self.first, self.user, "20000", paid_on=date(2026, 9, 5),
                                   reference="UTR1")
        self.first.refresh_from_db()
        self.assertEqual(self.first.status, RABill.Status.APPROVED)
        services.record_ra_payment(self.first, self.user, "28507.40", paid_on=date(2026, 9, 6),
                                   tds_amount="862.60")
        self.first.refresh_from_db()
        self.assertEqual(self.first.status, RABill.Status.PAID)
        self.wo.refresh_from_db()
        self.assertEqual(self.wo.status, PurchaseOrder.Status.DELIVERED)    # second unpaid

        with self.assertRaises(FinanceError):
            services.record_ra_payment(second, self.user, "49315.91")       # a paisa too much
        services.record_ra_payment(second, self.user, "49315.90", tds_amount="880.10")
        self.wo.refresh_from_db()
        self.assertEqual(self.wo.status, PurchaseOrder.Status.PAID)
        self.assertEqual(self.wo.paid_by, self.user)
        summary = calc.cumulative(self.wo)
        self.assertEqual(summary["paid_to_date"], D("97823.30"))
        self.assertEqual(summary["tds_withheld"], D("1742.70"))
        self.assertEqual(summary["payable_now"], D("0"))

    def test_no_bill_after_the_final_one(self):
        second = self.bill(self.wo, ["50", "20", "5"], ["50", "20", "5"], is_final=True)
        services.approve(second, self.user)
        with self.assertRaises(FinanceError) as refusal:
            self.bill(self.wo, ["1", "0", "0"])
        self.assertIn("final", str(refusal.exception))

    def test_approved_bill_figures_do_not_move_when_a_late_advance_is_paid(self):
        before = calc.bill_figures(self.first)["net_payable"]
        services.record_advance(self.wo, self.user, "10000", paid_on=date(2026, 9, 2))
        self.assertEqual(calc.bill_figures(self.first)["net_payable"], before)
        summary = calc.cumulative(self.wo)
        self.assertEqual(summary["advance_paid"], D("10000.00"))
        self.assertEqual(summary["advance_recovered"], D("4900.58"))


class TheLadderStillHandlesRetention(LadderFixture):
    """
    ⚠ THE ONE RETENTION TEST. Retention is switched off (customer, 11 Sep
      2026) — no screen sets it, no screen shows it when zero — but the rung is
      still in the ladder for orders billed at 10% before that date, and this
      test keeps its arithmetic honest: on the WORK VALUE, ex-GST, held per
      approved bill, and shown on the bill screen only when it is not zero.
    """

    def test_a_non_zero_retention_flows_through_the_ladder_and_the_screens(self):
        held = self.make_wo(number="ZQF-RET", retention="10")
        first = self.bill(held, ["50", "20", "4.5"], ["50", "20", "4.5"])
        ladder = calc.bill_figures(first)
        self.assertEqual(ladder["retention"], D("4929.13"))          # 10% of TAXABLE 49291.31
        self.assertEqual(ladder["retention"], calc._money(ladder["taxable"] / 10))
        self.assertNotEqual(ladder["retention"], calc._money(ladder["invoice_value"] / 10))
        self.assertEqual(ladder["payable"], D("44441"))              # 49369.64 − 4929.13 = 44440.51
        self.assertEqual(ladder["round_off"], D("0.49"))
        self.assertEqual(ladder["net_payable"], D("43578.40"))
        services.approve(first, self.user)
        summary = calc.cumulative(held)
        self.assertEqual(summary["retention_held"], D("4929.13"))
        self.assertEqual(summary["retention_balance"], D("4929.13"))
        # The bill screen prints the rung only because it is not zero …
        html = self.client.get(reverse("finance_ra_bill", args=[first.pk])).content.decode()
        self.assertIn("Less: retention @ 10", html)
        # … and not at all on the default (0%) order.
        zero = self.bill(self.wo, ["50", "20", "4.5"], ["50", "20", "4.5"])
        html = self.client.get(reverse("finance_ra_bill", args=[zero.pk])).content.decode()
        self.assertNotIn("Less: retention", html)


class MonthArithmetic(LadderFixture):

    def test_month_arithmetic_at_the_ends_of_months(self):
        self.assertEqual(calc._add_months(date(2026, 1, 31), 1), date(2026, 2, 28))
        self.assertEqual(calc._add_months(date(2028, 1, 31), 1), date(2028, 2, 29))
        self.assertEqual(calc._add_months(date(2026, 11, 15), 14), date(2028, 1, 15))
        self.assertEqual(calc._add_months(date(2026, 3, 31), 0), date(2026, 3, 31))

    def test_fiscal_quarters_run_april_to_march(self):
        quarters = calc.fiscal_quarters(date(2026, 9, 11))
        self.assertEqual(quarters[0][0], "2026-2")                   # Jul–Sep 2026, current
        self.assertEqual((quarters[0][2], quarters[0][3]), (date(2026, 7, 1), date(2026, 9, 30)))
        self.assertEqual(quarters[1][0], "2026-1")                   # Apr–Jun 2026
        self.assertEqual(quarters[2][0], "2025-4")                   # Jan–Mar 2026, last FY
        self.assertEqual((quarters[2][2], quarters[2][3]), (date(2026, 1, 1), date(2026, 3, 31)))
        self.assertEqual(len(quarters), 6)                           # 2 this FY + 4 last
        self.assertEqual(calc.quarter_bounds(date(2026, 9, 11), "nonsense")[0], "2026-2")
        self.assertEqual(calc.quarter_bounds(date(2026, 9, 11), "2025-4")[2], date(2026, 1, 1))


class ServiceRules(LadderFixture):

    def test_refuses_a_purchase_order(self):
        po = self.make_wo(number="ZQF-PO01", doc_type=DocumentType.PO)
        with self.assertRaises(FinanceError):
            self.bill(po, ["1", "1", "1"])

    def test_refuses_an_unapproved_work_order(self):
        draft = self.make_wo(number="ZQF-DRAFT", approve=False)
        with self.assertRaises(FinanceError):
            self.bill(draft, ["1", "1", "1"])

    def test_one_open_bill_at_a_time(self):
        self.bill(self.wo, ["1", "1", "1"])
        with self.assertRaises(FinanceError) as refusal:
            self.bill(self.wo, ["1", "1", "1"])
        self.assertIn("RA-", str(refusal.exception))

    def test_a_bill_of_nothing_is_refused(self):
        with self.assertRaises(FinanceError):
            self.bill(self.wo, ["0", "0", "0"])

    def test_numbers_and_sequence(self):
        first = self.bill(self.wo, ["1", "1", "1"])
        self.assertRegex(first.number, r"^RA-\d{6}$")
        self.assertEqual(first.sequence, 1)
        number = services.discard_draft(first)
        second = self.bill(self.wo, ["1", "1", "1"])
        self.assertNotEqual(second.number, number)            # never reused
        self.assertEqual(second.sequence, 1)                  # nothing counted before it

    def test_approve_needs_certified_and_every_line(self):
        bill = self.bill(self.wo, ["1", "1", "1"])
        with self.assertRaises(FinanceError):
            services.approve(bill, self.user)
        ids = [line.id for line in bill.lines.order_by("id")]
        with self.assertRaises(FinanceError) as refusal:
            services.certify(bill, self.user, {ids[0]: "1"})
        self.assertIn("no certified quantity", str(refusal.exception))

    def test_frozen_copies_from_the_po_line(self):
        bill = self.bill(self.wo, ["1", "1", "1"])
        line = bill.lines.order_by("id")[1]
        self.assertEqual((line.rate, line.gst_percent, line.discount_pct),
                         (D("1249.99"), D("12.00"), D("5.50")))

    def test_the_po_screen_buttons_are_refused_once_ra_bills_exist(self):
        self.bill(self.wo, ["1", "1", "1"])
        with self.assertRaises(POError) as refusal:
            po_service.mark_delivered(self.wo, user=self.user)
        self.assertIn("RA bills", str(refusal.exception))
        self.wo.status = PurchaseOrder.Status.DELIVERED
        self.wo.save()
        with self.assertRaises(POError):
            po_service.mark_paid(self.wo, user=self.user)

    def test_a_payment_needs_an_approved_bill(self):
        bill = self.bill(self.wo, ["1", "1", "1"], ["1", "1", "1"])
        with self.assertRaises(FinanceError):
            services.record_ra_payment(bill, self.user, "10")

    def test_work_order_terms_are_validated_on_a_draft(self):
        draft = self.make_wo(number="ZQF-TERMS", approve=False)
        for field, bad in (("retention_pct", "51"), ("dlp_months", "61"),
                           ("mobilisation_advance", "-1"), ("mobilisation_advance", "100582.63")):
            with self.assertRaises(POError, msg=field):
                po_service.update_draft_document(draft, **{field: bad})
        po_service.update_draft_document(draft, retention_pct="5", dlp_months="6",
                                         mobilisation_advance="100582.62")
        draft.refresh_from_db()
        self.assertEqual((draft.retention_pct, draft.dlp_months, draft.mobilisation_advance),
                         (D("5.00"), 6, D("100582.62")))


class VendorInvoicesOnAPurchaseOrder(LadderFixture):

    def setUp(self):
        super().setUp()
        self.po = self.make_wo(number="ZQF-PO02", doc_type=DocumentType.PO)

    def test_invoice_arithmetic_is_checked_to_the_paisa(self):
        with self.assertRaises(FinanceError):
            services.record_vendor_invoice(self.po, self.user, "INV-1", date(2026, 9, 1),
                                           "1000", "180", "1180.01")
        with self.assertRaises(FinanceError):
            services.record_vendor_invoice(self.wo, self.user, "INV-1", date(2026, 9, 1),
                                           "1000", "180", "1180")
        invoice = services.record_vendor_invoice(self.po, self.user, "INV-1", date(2026, 9, 1),
                                                 "1000", "180", "1180")
        self.assertRegex(invoice.number, r"^VB-\d{6}$")
        with self.assertRaises(FinanceError):                    # the same invoice twice
            services.record_vendor_invoice(self.po, self.user, "inv-1", date(2026, 9, 1),
                                           "1000", "180", "1180")

    def test_settlement_and_the_paid_flip(self):
        invoice = services.record_vendor_invoice(self.po, self.user, "INV-2", date(2026, 9, 1),
                                                 "100582.62", "12500", "113082.62")
        settlement = calc.po_settlement(self.po)
        self.assertEqual(settlement["invoiced_total"], D("113082.62"))
        self.assertEqual(settlement["order_value"], self.po.totals()["order_value"])
        self.assertEqual(settlement["net_payable"], self.po.totals()["net_payable"])
        self.assertTrue(settlement["over_invoiced"])          # 113,082.62 > order value
        self.assertEqual(settlement["invoices"][invoice.id]["status"], "open")

        services.record_advance(self.po, self.user, "10000", paid_on=date(2026, 9, 2))
        services.record_invoice_payment(invoice, self.user, "50000", paid_on=date(2026, 9, 3),
                                        tds_amount="1760.20")
        settlement = calc.po_settlement(self.po)
        self.assertEqual(settlement["paid_total"], D("60000.00"))
        self.assertEqual(settlement["tds_withheld"], D("1760.20"))
        self.assertEqual(settlement["invoices"][invoice.id]["status"], "part_paid")
        self.assertEqual(settlement["invoices"][invoice.id]["balance"], D("61322.42"))
        self.assertEqual(settlement["balance"], settlement["net_payable"] - D("60000"))

        # Not delivered yet → no flip, whatever is paid.
        net = self.po.totals()["net_payable"]
        services.record_invoice_payment(invoice, self.user, str(net - D("60000")),
                                        paid_on=date(2026, 9, 4))
        self.po.refresh_from_db()
        self.assertEqual(self.po.status, PurchaseOrder.Status.APPROVED)

        po_service.mark_delivered(self.po, user=self.user)
        services.record_invoice_payment(invoice, self.user, "1", paid_on=date(2026, 9, 5))
        self.po.refresh_from_db()
        self.assertEqual(self.po.status, PurchaseOrder.Status.PAID)
        self.assertEqual(self.po.paid_by, self.user)

    def test_a_payment_cannot_exceed_the_invoice(self):
        invoice = services.record_vendor_invoice(self.po, self.user, "INV-3", date(2026, 9, 1),
                                                 "100", "18", "118")
        with self.assertRaises(FinanceError):
            services.record_invoice_payment(invoice, self.user, "118.01")
        services.record_invoice_payment(invoice, self.user, "100", tds_amount="18")
        self.assertEqual(calc.bulk_invoice_figures([invoice])[invoice.id]["status"], "settled")
