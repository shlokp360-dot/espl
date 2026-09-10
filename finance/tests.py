"""
The finance screens: they render with data, refuse the wrong role, do not grow
queries with the rows, export what is filtered, and keep the ⓘ panel format.

The money itself is proven in finance/test_ladder.py.
"""
import re
from datetime import date, timedelta
from decimal import Decimal as D
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.test import SimpleTestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from accounts.models import Role
from masters.models import DocumentType
from projects.bom_models import PurchaseOrder, Receipt
from projects import po_service

from finance import calc, services
from finance.models import RABill, VendorInvoice, VendorPayment
from finance.panels import PANELS
from finance.test_ladder import LadderFixture


class ScreenFixture(LadderFixture):
    """A work order with an approved bill and an open one, and a PO with an invoice."""

    def setUp(self):
        super().setUp()
        self.first = self.bill(self.wo, ["50", "20", "4.5"], ["50", "20", "4.5"])
        services.approve(self.first, self.user)
        self.second = self.bill(self.wo, ["50", "20", "5"])
        self.po = self.make_wo(number="ZQF-PO09", doc_type=DocumentType.PO)
        self.invoice = services.record_vendor_invoice(
            self.po, self.user, "INV-9", date(2026, 9, 1), "1000", "180", "1180")
        services.record_invoice_payment(self.invoice, self.user, "500", paid_on=date.today())
        services.record_advance(self.wo, self.user, "4000", paid_on=date.today())

    def get(self, name, *args, **params):
        response = self.client.get(reverse(name, args=args), params)
        self.assertEqual(response.status_code, 200, name)
        return response.content.decode()


class TheScreensRender(ScreenFixture):

    def test_home(self):
        html = self.get("finance_home")
        self.assertIn("Payable now", html)
        self.assertIn(self.wo.number, html)
        self.assertIn(self.second.number, html)             # the open bill
        self.assertNotIn("{{", html)
        self.assertNotIn("{%", html)

    def test_ra_bill_register_and_filters(self):
        html = self.get("finance_ra_bills")
        self.assertIn(self.first.number, html)
        self.assertIn(self.second.number, html)
        html = self.get("finance_ra_bills", status="approved")
        self.assertIn(self.first.number, html)
        self.assertNotIn(self.second.number, html)
        html = self.get("finance_ra_bills", project=str(self.project.pk), vendor=str(self.vendor.pk))
        self.assertIn(self.first.number, html)
        self.get("finance_ra_bills", project="abc")          # guarded, not a crash

    def test_work_order_screen(self):
        html = self.get("finance_wo", self.wo.pk)
        self.assertIn("49,291", html)                        # certified to date
        self.assertIn("4,929", html)                         # retention held
        self.assertIn(self.second.number, html)
        self.assertIn("is draft", html)                      # the open-bill note
        self.assertIn("4,000", html)                         # the advance paid

    def test_the_bill_screen_open_and_locked(self):
        html = self.get("finance_ra_bill", self.second.pk)
        self.assertIn('name="cert-', html)
        self.assertIn("Certify", html)
        self.assertNotIn("Download PDF", html)
        html = self.get("finance_ra_bill", self.first.pk)
        self.assertNotIn('name="cert-', html)
        self.assertIn("Download PDF", html)
        self.assertIn("43,578", html)                        # net payable
        self.assertIn("Record payment", html)
        self.assertIn("locked", html)

    def test_pdf_refused_on_an_open_bill(self):
        response = self.client.get(reverse("finance_ra_bill_pdf", args=[self.second.pk]))
        self.assertEqual(response.status_code, 302)

    def test_pdf_on_an_approved_bill(self):
        try:
            import weasyprint  # noqa: F401
        except ImportError:
            self.skipTest("WeasyPrint is not installed here")
        response = self.client.get(reverse("finance_ra_bill_pdf", args=[self.first.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_retention_invoices_po_and_payments(self):
        self.assertIn(self.wo.number, self.get("finance_retention"))
        html = self.get("finance_invoices")
        self.assertIn(self.invoice.number, html)
        self.assertIn("Part-paid", html)
        self.assertIn(self.invoice.number, self.get("finance_invoices", status="part_paid"))
        self.assertNotIn(self.invoice.number, self.get("finance_invoices", status="settled"))
        html = self.get("finance_po", self.po.pk)
        self.assertIn("Record invoice", html)
        self.assertIn(self.invoice.vendor_invoice_no, html)
        html = self.get("finance_payments")
        self.assertIn("PV-", html)
        self.assertIn("Excel for Tally", html)
        self.get("finance_ra_bill_pay", self.first.pk)
        self.get("finance_ra_bill_discard", self.second.pk)
        self.get("finance_invoice_new", self.po.pk)
        self.get("finance_po_pay", self.po.pk)
        self.get("finance_po_pay", self.po.pk, kind="advance")

    def test_finance_po_refuses_a_work_order_and_finance_wo_a_purchase_order(self):
        self.assertEqual(self.client.get(reverse("finance_po", args=[self.wo.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("finance_wo", args=[self.po.pk])).status_code, 404)

    def test_po_detail_carries_the_finance_links_and_wo_terms(self):
        html = self.client.get(reverse("po_detail", args=[self.project.pk, self.wo.pk])).content.decode()
        self.assertIn(reverse("finance_wo", args=[self.wo.pk]), html)
        self.assertIn("Retention", html)
        self.assertIn("Defect liability period", html)
        html = self.client.get(reverse("po_detail", args=[self.project.pk, self.po.pk])).content.decode()
        self.assertIn(reverse("finance_po", args=[self.po.pk]), html)
        self.assertNotIn("Defect liability period", html)
        draft = self.make_wo(number="ZQF-DRF", approve=False)
        html = self.client.get(reverse("po_detail", args=[self.project.pk, draft.pk])).content.decode()
        self.assertIn('name="retention"', html)
        self.assertIn('name="dlp_months"', html)
        self.assertIn('name="mobilisation_advance"', html)
        self.assertNotIn("finance/wo/", html)                 # not on a draft

    def test_po_save_writes_the_wo_terms(self):
        draft = self.make_wo(number="ZQF-DRF2", approve=False)
        self.client.post(reverse("po_save", args=[self.project.pk, draft.pk]),
                         {"retention": "7.5", "dlp_months": "18", "mobilisation_advance": "5000"})
        draft.refresh_from_db()
        self.assertEqual((draft.retention_pct, draft.dlp_months, draft.mobilisation_advance),
                         (D("7.50"), 18, D("5000.00")))
        self.client.post(reverse("po_save", args=[self.project.pk, draft.pk]),
                         {"retention": "80"})
        draft.refresh_from_db()
        self.assertEqual(draft.retention_pct, D("7.50"))      # refused, unchanged

    def test_po_advance_paid_button_is_refused_on_a_billed_work_order(self):
        self.wo.status = PurchaseOrder.Status.DELIVERED
        self.wo.save()
        self.client.post(reverse("po_advance", args=[self.project.pk, self.wo.pk]), {"to": "paid"})
        self.wo.refresh_from_db()
        self.assertEqual(self.wo.status, PurchaseOrder.Status.DELIVERED)


class TheWritesThroughTheScreens(ScreenFixture):

    def line_ids(self, bill):
        return [line.id for line in bill.lines.order_by("id")]

    def test_save_certify_approve_pay_through_the_forms(self):
        ids = self.line_ids(self.second)
        post = {f"claim-{ids[0]}": "50", f"claim-{ids[1]}": "20", f"claim-{ids[2]}": "5",
                f"cert-{ids[0]}": "50", f"cert-{ids[1]}": "20", f"cert-{ids[2]}": "5",
                "is_final": "1", "contractor_ref": "C-2", "bill_date": "2026-09-02",
                "note": "closing", "action": "certify"}
        self.client.post(reverse("finance_ra_bill_save", args=[self.second.pk]), post)
        self.second.refresh_from_db()
        self.assertEqual(self.second.status, RABill.Status.CERTIFIED)
        self.assertTrue(self.second.is_final)
        self.assertEqual(self.second.contractor_ref, "C-2")

        self.client.post(reverse("finance_ra_bill_approve", args=[self.second.pk]))
        self.second.refresh_from_db()
        self.assertEqual(self.second.status, RABill.Status.APPROVED)
        self.wo.refresh_from_db()
        self.assertEqual(self.wo.status, PurchaseOrder.Status.DELIVERED)
        self.assertEqual(Receipt.objects.filter(source=Receipt.Source.RA_BILL).count(), 6)

        response = self.client.post(reverse("finance_ra_bill_pay", args=[self.second.pk]),
                                    {"amount": "44286.90", "tds_amount": "880.10",
                                     "paid_on": "2026-09-10", "mode": "neft", "reference": "U1"})
        self.assertEqual(response.status_code, 302)
        self.second.refresh_from_db()
        self.assertEqual(self.second.status, RABill.Status.PAID)

    def test_over_certification_through_the_form_leaves_the_bill_a_draft(self):
        ids = self.line_ids(self.second)
        post = {f"cert-{ids[0]}": "50", f"cert-{ids[1]}": "20", f"cert-{ids[2]}": "9",
                "action": "certify"}
        response = self.client.post(reverse("finance_ra_bill_save", args=[self.second.pk]), post,
                                    follow=True)
        self.assertIn("over the order", response.content.decode())
        self.second.refresh_from_db()
        self.assertEqual(self.second.status, RABill.Status.DRAFT)

    def test_new_bill_discard_and_release_through_the_forms(self):
        services.discard_draft(self.second)
        ids = [line.id for line in self.wo.lines.order_by("id")]
        response = self.client.post(reverse("finance_ra_bill_new", args=[self.wo.pk]),
                                    {f"claim-{ids[0]}": "10", "bill_date": "2026-09-03"})
        bill = RABill.objects.get(purchase_order=self.wo, status=RABill.Status.DRAFT)
        self.assertRedirects(response, reverse("finance_ra_bill", args=[bill.pk]))
        self.assertEqual(bill.lines.count(), 1)
        self.client.post(reverse("finance_ra_bill_discard", args=[bill.pk]))
        self.assertFalse(RABill.objects.filter(pk=bill.pk).exists())

        response = self.client.post(reverse("finance_retention_release", args=[self.wo.pk]),
                                    {"amount": "100", "released_on": "2026-09-10"}, follow=True)
        self.assertIn("defect liability", response.content.decode())
        self.client.post(reverse("finance_retention_release", args=[self.wo.pk]),
                         {"amount": "100", "released_on": "2026-09-10", "override": "1",
                          "note": "agreed early"})
        self.assertEqual(calc.cumulative(self.wo)["retention_released"], D("100.00"))

    def test_invoice_and_payment_forms(self):
        response = self.client.post(reverse("finance_invoice_new", args=[self.po.pk]),
                                    {"vendor_invoice_no": "INV-10", "invoice_date": "2026-09-04",
                                     "taxable": "200", "gst": "36", "total": "236"})
        self.assertRedirects(response, reverse("finance_po", args=[self.po.pk]))
        invoice = VendorInvoice.objects.get(vendor_invoice_no="INV-10")
        response = self.client.post(reverse("finance_invoice_new", args=[self.po.pk]),
                                    {"vendor_invoice_no": "INV-11", "invoice_date": "2026-09-04",
                                     "taxable": "200", "gst": "36", "total": "237"})
        self.assertEqual(response.status_code, 200)          # refused, form redrawn
        self.assertFalse(VendorInvoice.objects.filter(vendor_invoice_no="INV-11").exists())

        self.client.post(reverse("finance_po_pay", args=[self.po.pk]),
                         {"kind": "against_invoice", "invoice": str(invoice.pk), "amount": "236",
                          "paid_on": "2026-09-05", "mode": "upi"})
        self.assertEqual(calc.bulk_invoice_figures([invoice])[invoice.pk]["status"], "settled")
        self.client.post(reverse("finance_po_pay", args=[self.po.pk]),
                         {"kind": "advance", "amount": "300", "paid_on": "2026-09-05", "mode": "cash"})
        self.assertEqual(VendorPayment.objects.filter(purchase_order=self.po,
                                                      kind=VendorPayment.Kind.ADVANCE).count(), 1)


class TheExports(ScreenFixture):

    def sheet(self, response):
        from io import BytesIO
        from openpyxl import load_workbook
        self.assertEqual(response.status_code, 200)
        return load_workbook(BytesIO(response.content))

    def test_ra_bill_excel_carries_the_ladder_and_the_lines(self):
        book = self.sheet(self.client.post(reverse("finance_ra_bills_excel"), {}))
        bills = book["RA bills"]
        rows = list(bills.iter_rows(values_only=True))
        headings = list(rows[0])
        by_number = {row[0]: dict(zip(headings, row)) for row in rows[1:]}
        first = by_number[self.first.number]
        self.assertEqual(D(str(first["Net payable"])), D("43578.40"))
        self.assertEqual(D(str(first["Retention"])), D("4929.13"))
        self.assertEqual(D(str(first["Advance recovery"])), D("4900.58"))
        lines = list(book["Lines"].iter_rows(values_only=True))
        self.assertEqual(len(lines), 1 + 6)                  # two bills, three lines each
        # The filter reaches the export.
        book = self.sheet(self.client.post(reverse("finance_ra_bills_excel"), {"status": "draft"}))
        self.assertEqual(len(list(book["RA bills"].iter_rows(values_only=True))), 2)

    def test_payments_excel_has_the_tally_columns(self):
        book = self.sheet(self.client.post(reverse("finance_payments_excel"),
                                           {"from": "2026-01-01", "to": "2030-01-01"}))
        rows = list(book.active.iter_rows(values_only=True))
        self.assertEqual(list(rows[0]), ["Date", "PV number", "Vendor", "GSTIN", "Project",
                                         "Document", "Kind", "Amount", "TDS", "Mode", "Reference"])
        self.assertEqual(len(rows), 1 + VendorPayment.objects.count())


class WhoMayOpenWhat(ScreenFixture):

    def as_role(self, role):
        user = self.make_user(f"zq.{role}", role=role)
        self.client.force_login(user)

    def status(self, name, *args):
        return self.client.get(reverse(name, args=args)).status_code

    def test_site_reaches_the_work_order_and_the_bill_but_not_the_books(self):
        self.as_role(Role.SITE)
        self.assertEqual(self.status("finance_wo", self.wo.pk), 200)
        self.assertEqual(self.status("finance_ra_bill", self.second.pk), 200)
        for name in ("finance_home", "finance_ra_bills", "finance_retention", "finance_invoices",
                     "finance_payments"):
            self.assertEqual(self.status(name), 403, name)
        self.assertEqual(self.status("finance_po", self.po.pk), 403)
        self.assertEqual(self.status("finance_ra_bill_pdf", self.first.pk), 403)

    def test_purchase_and_compliance_are_refused_everywhere(self):
        for role in (Role.PURCHASE, Role.COMPLIANCE):
            self.as_role(role)
            self.assertEqual(self.status("finance_home"), 403)
            self.assertEqual(self.status("finance_wo", self.wo.pk), 403)
            self.assertEqual(self.status("finance_ra_bill", self.second.pk), 403)

    def test_the_accountant_pays_but_does_not_certify_or_approve(self):
        self.as_role(Role.ACCOUNTANT)
        self.assertEqual(self.status("finance_home"), 200)
        self.assertEqual(self.status("finance_ra_bill_pay", self.first.pk), 200)
        self.assertEqual(self.status("finance_invoice_new", self.po.pk), 200)
        self.assertEqual(self.client.post(reverse("finance_ra_bill_save", args=[self.second.pk]),
                                          {}).status_code, 403)
        self.assertEqual(self.client.post(reverse("finance_ra_bill_approve",
                                                  args=[self.second.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("finance_retention_release",
                                                  args=[self.wo.pk]), {}).status_code, 403)
        self.assertEqual(self.status("finance_ra_bill_discard", self.second.pk), 403)

    def test_the_project_manager_certifies_and_approves_but_does_not_pay(self):
        self.as_role(Role.PROJECT_MANAGER)
        self.assertEqual(self.status("finance_ra_bill_pay", self.first.pk), 403)
        self.assertEqual(self.status("finance_invoice_new", self.po.pk), 403)
        self.assertEqual(self.status("finance_po_pay", self.po.pk), 403)
        self.assertEqual(self.client.post(reverse("finance_ra_bill_approve",
                                                  args=[self.second.pk])).status_code, 302)

    def test_the_buttons_hide_for_the_role_that_cannot_press_them(self):
        self.as_role(Role.ACCOUNTANT)
        html = self.client.get(reverse("finance_ra_bill", args=[self.second.pk])).content.decode()
        self.assertNotIn("Certify", html)
        self.assertNotIn('name="cert-', html)
        self.as_role(Role.SITE)
        html = self.client.get(reverse("finance_ra_bill", args=[self.first.pk])).content.decode()
        self.assertNotIn("Record payment", html)
        self.assertNotIn("Download PDF", html)


class TheQueryShape(LadderFixture):
    """Query counts must not grow with the rows — FIN-CALC-BULK."""

    def fill(self, count):
        start = PurchaseOrder.objects.count()
        for index in range(start, start + count):
            wo = self.make_wo(number=f"ZQF-Q{index:03d}")
            bill = self.bill(wo, ["100", "40", "10"], ["100", "40", "10"], is_final=True)
            services.approve(bill, self.user)
            services.record_ra_payment(bill, self.user, "1000", paid_on=date.today())
            po = self.make_wo(number=f"ZQF-QP{index:03d}", doc_type=DocumentType.PO)
            invoice = services.record_vendor_invoice(po, self.user, f"I-{index}", date.today(),
                                                     "100", "18", "118")
            services.record_invoice_payment(invoice, self.user, "50", paid_on=date.today())

    def count(self, name, params=None):
        with CaptureQueriesContext(connection) as context:
            response = self.client.get(reverse(name), params or {})
        self.assertEqual(response.status_code, 200, name)
        return len(context.captured_queries)

    def test_registers_do_not_grow_with_the_rows(self):
        self.fill(3)
        screens = ["finance_home", "finance_ra_bills", "finance_retention", "finance_invoices",
                   "finance_payments"]
        small = {name: self.count(name) for name in screens}
        self.fill(20)
        for name in screens:
            with self.subTest(screen=name):
                self.assertLess(self.count(name) - small[name], 10)

    def test_the_work_order_and_bill_screens_are_flat(self):
        for index in range(6):
            bill = self.bill(self.wo, ["10", "5", "1"], ["10", "5", "1"])
            services.approve(bill, self.user)
            services.record_ra_payment(bill, self.user, "100", paid_on=date.today())
        with CaptureQueriesContext(connection) as context:
            self.assertEqual(self.client.get(reverse("finance_wo", args=[self.wo.pk])).status_code, 200)
        self.assertLess(len(context.captured_queries), 25)
        with CaptureQueriesContext(connection) as context:
            self.assertEqual(self.client.get(reverse("finance_ra_bill", args=[bill.pk])).status_code, 200)
        self.assertLess(len(context.captured_queries), 25)


class FinancePanelsKeepTheFormat(SimpleTestCase):

    def test_steps_are_between_twenty_and_thirty_words(self):
        for key, panel in PANELS.items():
            for number, entry in enumerate(panel["steps"], 1):
                with self.subTest(panel=key, step=number):
                    self.assertGreaterEqual(len(entry["text"].split()), 20)
                    self.assertLessEqual(len(entry["text"].split()), 30)

    def test_labels_and_step_counts(self):
        for key, panel in PANELS.items():
            with self.subTest(panel=key):
                self.assertTrue(panel["title"])
                self.assertGreaterEqual(len(panel["steps"]), 3)
                for entry in panel["steps"]:
                    self.assertLessEqual(len(entry["label"].split()), 2)
                    self.assertNotIn("<", entry["text"])
                    self.assertNotIn("**", entry["text"])

    def test_perms_name_real_finance_keys(self):
        from accounts.perms import MATRIX
        for key, panel in PANELS.items():
            for entry in panel["steps"]:
                if entry["perm"]:
                    self.assertIn(entry["perm"], MATRIX)
                    self.assertTrue(entry["perm"].startswith("finance."))

    def test_every_key_a_finance_template_uses_exists_and_nothing_more(self):
        folder = Path(settings.BASE_DIR) / "templates" / "finance"
        used = set()
        for path in folder.glob("*.html"):
            used.update(re.findall(r'{% info(?:button|panel) "([^"]+)" %}',
                                   path.read_text(encoding="utf-8")))
        self.assertTrue(used)
        self.assertEqual(used - set(PANELS), set())
        self.assertEqual(set(PANELS) - used, set())
