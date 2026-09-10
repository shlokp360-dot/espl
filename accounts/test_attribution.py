"""
Who raised a document, who took delivery, and who paid it.

⚠ THE MATRIX HANDS THESE THREE STEPS TO THREE DIFFERENT ROLES ON PURPOSE, so
  recording only the timestamp threw away the half of the record somebody
  actually asks about later: not "when was this paid" but "who paid it".
"""
from decimal import Decimal as D

from django.urls import reverse

from accounts.models import Role
from accounts.testing import AuthedTestCase
from masters.models import Material, MaterialGroup, Vendor
from projects import po_service
from projects.bom_models import Bom, BomLine, PurchaseOrder
from projects.models import Activity, Project


class WhoDidWhatToADocument(AuthedTestCase):
    def setUp(self):
        super().setUp()
        self.rcc = Activity.objects.get(abbreviation="RCC")
        group = MaterialGroup.objects.create(code="CEM", name="Cement & Binders")
        self.cement = Material.objects.create(
            code="RCC-CEM-001", name="CEMENT OPC", group=group, uom="Bag",
            estimation_rate=D("289.06"), gst_percent=D("28"), home_activity=self.rcc)
        # ⚠ `gst_number`, not `gstin` — the model spells it out, and `code` is
        #   required because a vendor's code is assigned rather than derived.
        self.vendor = Vendor.objects.create(
            code="VEN-900", name="Shree Cement Depot", phone="9000000001",
            gst_number="24AAACS1234A1Z5")
        self.project = Project.objects.create(
            code="PRJ-000900", name="Bhudarpura", bua_sqft=D("20000"),
            status=Project.Status.WON)
        bom = Bom.objects.create(project=self.project)
        line = BomLine.objects.create(
            bom=bom, activity=self.rcc, material=self.cement, planned_qty=D("100"),
            vendor=self.vendor, vendor_rate=D("290"))
        line.order_qty_override = D("50")
        line.save(update_fields=["order_qty_override"])

        self.purchase = self.make_user("pur", role=Role.PURCHASE, name="Purchase Person")
        self.accountant = self.make_user("acc", role=Role.ACCOUNTANT, name="Accounts Person")
        self.site = self.make_user("sitey", role=Role.SITE, name="Site Person")

        self.order = po_service.generate_purchase_orders(bom, user=self.purchase)[0]

    def advance(self, who, target):
        self.client.force_login(who)
        return self.client.post(
            reverse("po_advance", args=[self.project.id, self.order.id]), {"to": target})

    def test_the_person_who_posted_it_is_recorded(self):
        self.assertEqual(self.order.created_by, self.purchase)

    def test_the_admin_who_approved_it_is_recorded(self):
        self.advance(self.user, PurchaseOrder.Status.APPROVED)
        self.order.refresh_from_db()
        self.assertEqual(self.order.approved_by, self.user)

    def test_the_site_engineer_who_took_delivery_is_recorded(self):
        self.advance(self.user, PurchaseOrder.Status.APPROVED)
        self.advance(self.site, PurchaseOrder.Status.DELIVERED)
        self.order.refresh_from_db()
        self.assertEqual(self.order.delivered_by, self.site)
        # ⚠ And it is somebody OTHER than the approver, which is the point.
        self.assertNotEqual(self.order.delivered_by, self.order.approved_by)

    def test_the_accountant_who_paid_it_is_recorded(self):
        self.advance(self.user, PurchaseOrder.Status.APPROVED)
        self.advance(self.site, PurchaseOrder.Status.DELIVERED)
        self.advance(self.accountant, PurchaseOrder.Status.PAID)
        self.order.refresh_from_db()
        self.assertEqual(self.order.paid_by, self.accountant)

    def test_all_three_names_appear_on_the_document_screen(self):
        self.advance(self.user, PurchaseOrder.Status.APPROVED)
        self.advance(self.site, PurchaseOrder.Status.DELIVERED)
        self.advance(self.accountant, PurchaseOrder.Status.PAID)
        self.client.force_login(self.user)
        body = self.client.get(
            reverse("po_detail", args=[self.project.id, self.order.id])).content.decode()
        self.assertIn("Purchase Person", body)
        self.assertIn("Test Admin", body)
        self.assertIn("Site Person", body)
        self.assertIn("Accounts Person", body)

    def test_a_document_with_no_names_shows_dates_and_no_invented_people(self):
        """
        ⚠ EVERY DOCUMENT RAISED BEFORE THIS COMMIT HAS THREE EMPTY COLUMNS, and
          nothing backfills them. The screen must show the date it does know and
          stay quiet about the person it does not.
        """
        PurchaseOrder.objects.filter(pk=self.order.pk).update(created_by=None)
        self.client.force_login(self.user)
        body = self.client.get(
            reverse("po_detail", args=[self.project.id, self.order.id])).content.decode()
        self.assertNotIn("by None", body)
        self.assertIn("Raised", body)

    def test_the_printed_document_still_carries_no_names(self):
        """
        ⚠ THE PRINT FORMAT IS SIGNED OFF. Only the approval DATE prints, as it
          always has. Putting a name on it would mean re-approving that layout,
          which nobody has asked for — so this reads the print template itself
          rather than rendering a PDF, because CI deliberately does not install
          WeasyPrint.
        """
        from django.conf import settings

        template = (settings.BASE_DIR / "templates" / "projects" / "po_pdf.html").read_text(
            encoding="utf-8")
        for forbidden in ("approved_by", "delivered_by", "paid_by", "created_by"):
            self.assertNotIn(
                forbidden, template,
                f"{forbidden} reached the signed-off print format — that layout needs "
                f"re-approving before a name goes on it")
