"""
The quick corrections from Saahil's own walkthrough of the built app.

⚠ EVERY TEST HERE EXISTS BECAUSE HE FOUND SOMETHING ON SCREEN. His review is
  the record; these are the parts of it that are arithmetic or behaviour rather
  than wording, and wording alone is not worth a test.

  #11  the export followed nothing — it always wrote all 705
  #21  the per-project purchase-order screens had no status filter
       (the cross-project register already had one, which is why this was
        missed the first time it was written down)
"""
from decimal import Decimal as D
from io import BytesIO

from django.contrib.auth import get_user_model
from django.test import TestCase
from openpyxl import load_workbook

from accounts.models import Role, UserProfile
from masters.models import Activity, Material, MaterialGroup, Vendor, VendorGroup
from projects.bom_models import PurchaseOrder
from projects.models import Project

User = get_user_model()

# ⚠ THE SHEET'S FIRST DATA ROW IS 3, NOT 4. Row 1 and row 2 are the two note
#   rows inserted above the headings — and getting this wrong while checking the
#   export by hand made a correct file look as if it had lost a row. Bug 10 was
#   the same off-by-one from the other direction.
FIRST_DATA_ROW = 3


def _codes(response):
    """The material or vendor codes actually written into a downloaded sheet."""
    sheet = load_workbook(BytesIO(response.content)).active
    return [row[0] for row in sheet.iter_rows(min_row=FIRST_DATA_ROW, values_only=True)
            if row[0]]


class TheExportFollowsWhatTheScreenIsShowing(TestCase):
    """
    >>> ANCHOR: MASTER-EXPORT-FOLLOWS-FILTERS <<<
    Saahil: "when I wanted to download, it was only giving me an option to
    download all of them. Can we not select a few and then download those?"

    The four filters on the list ARE the selection, so there is no second way to
    choose and nothing to keep in step.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="pm", password="x")
        UserProfile.objects.update_or_create(
            user=cls.user, defaults={"role": Role.ADMIN, "must_change_password": False})

        # ⚠ BUG 19 — TEST FIXTURES COLLIDE ON A UNIQUE FIELD. Migration 0003
        #   seeds the real activity master, so RCC, PLM and sixteen others are
        #   already taken before a single test runs. These two abbreviations are
        #   deliberately not trades.
        steel = Activity.objects.create(abbreviation="ZQA", name="Test trade A",
                                        rate=D("100"), sort_order=901)
        plumb = Activity.objects.create(abbreviation="ZQB", name="Test trade B",
                                        rate=D("100"), sort_order=902)
        bars = MaterialGroup.objects.create(code="ZQA", name="Test group A")
        pipes = MaterialGroup.objects.create(code="ZQB", name="Test group B")

        for code, group, activity, active in (
            ("ZQA-ZQA-001", bars, steel, True),
            ("ZQA-ZQA-002", bars, steel, True),
            ("ZQB-ZQB-001", pipes, plumb, True),
            ("ZQB-ZQB-002", pipes, plumb, False),
        ):
            Material.objects.create(
                code=code, name=f"Material {code}", group=group, home_activity=activity,
                uom="Nos", estimation_rate=D("100"), gst_percent=D("18"), is_active=active)

        group = VendorGroup.objects.create(name="Suppliers")
        Vendor.objects.create(code="VEN-001", name="Alpha Traders", phone="9000000001",
                              group=group, gst_number="24AAAAA0000A1Z5")
        Vendor.objects.create(code="VEN-002", name="Beta Supplies", phone="9000000002",
                              group=group, gst_number="")

    def setUp(self):
        self.client.force_login(self.user)

    def test_no_filter_still_means_the_whole_master(self):
        """⚠ THE OLD BEHAVIOUR IS THE DEFAULT, not a special case."""
        codes = _codes(self.client.post("/masters/materials/export/"))
        self.assertEqual(sorted(codes), ["ZQA-ZQA-001", "ZQA-ZQA-002", "ZQB-ZQB-001"])

    def test_a_group_filter_narrows_the_file(self):
        codes = _codes(self.client.post("/masters/materials/export/?group=ZQA"))
        self.assertEqual(sorted(codes), ["ZQA-ZQA-001", "ZQA-ZQA-002"])

    def test_the_inactive_filter_reaches_the_file_too(self):
        """The one filter that ADDS rows rather than removing them."""
        codes = _codes(self.client.post("/masters/materials/export/?show=all"))
        self.assertIn("ZQB-ZQB-002", codes)

    def test_the_search_box_narrows_the_file(self):
        """⚠ SEARCH IS APPLIED IN PYTHON, so the export receives a list, not a
        queryset. Both have to work."""
        codes = _codes(self.client.post("/masters/materials/export/?q=ZQB-ZQB-001"))
        self.assertEqual(codes, ["ZQB-ZQB-001"])

    def test_the_file_agrees_with_the_screen(self):
        """
        ⚠⚠ THE FAULT WORTH CATCHING. A sheet that quietly disagrees with the
          table it was downloaded from is bug 24 in spreadsheet form: it opens
          perfectly and says something else.
        """
        page = self.client.get("/masters/materials/?group=ZQA")
        self.assertEqual(page.context["matched"], 2)
        self.assertEqual(len(_codes(self.client.post("/masters/materials/export/?group=ZQA"))), 2)

    def test_the_button_says_which_it_will_do(self):
        self.assertFalse(self.client.get("/masters/materials/").context["filtered"])
        self.assertTrue(self.client.get("/masters/materials/?group=ZQA").context["filtered"])

    def test_vendors_follow_their_filters_as_well(self):
        codes = _codes(self.client.post("/masters/vendors/export/?nogst=1"))
        self.assertEqual(codes, ["VEN-002"])

    def test_the_blank_template_is_still_blank(self):
        """⚠ A TEMPLATE MUST NOT PICK UP THE FILTERS. It has no rows at all."""
        self.assertEqual(_codes(self.client.post("/masters/materials/template/")), [])


class ThePerProjectOrdersScreenFiltersOnStatus(TestCase):
    """
    >>> ANCHOR: PO-STATUS-FILTER <<<
    Saahil: "when I open the PO, it showed a lot of drafts, approved, paid…
    there should be an option for the user to filter the PO based on the status."

    ⚠ THE CROSS-PROJECT REGISTER ALREADY HAD THIS. These two screens did not,
      which is exactly why the register having it was not the answer.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="pm2", password="x")
        UserProfile.objects.update_or_create(
            user=cls.user, defaults={"role": Role.ADMIN, "must_change_password": False})

        cls.project = Project.objects.create(name="Bhudarpura", bua_sqft=D("10000"))
        group = VendorGroup.objects.create(name="Suppliers")
        cls.vendor = Vendor.objects.create(code="VEN-010", name="Gamma", phone="9000000010",
                                           group=group, gst_number="24AAAAA0000A1Z5")
        cls.by_status = {}
        for status in (PurchaseOrder.Status.DRAFT, PurchaseOrder.Status.APPROVED,
                       PurchaseOrder.Status.DELIVERED, PurchaseOrder.Status.PAID):
            cls.by_status[status] = PurchaseOrder.objects.create(
                number=f"PO-{status[:3].upper()}1", project=cls.project,
                vendor=cls.vendor, status=status)

    def setUp(self):
        self.client.force_login(self.user)

    def _listed(self, query=""):
        url = f"/projects/{self.project.id}/orders/vendor/{self.vendor.id}/{query}"
        return {row["order"].status for row in self.client.get(url).context["rows"]}

    def test_no_filter_shows_every_status(self):
        self.assertEqual(len(self._listed()), 4)

    def test_one_status_shows_only_that_status(self):
        self.assertEqual(self._listed("?status=draft"), {PurchaseOrder.Status.DRAFT})

    def test_not_paid_yet_is_approved_and_delivered_together(self):
        """
        ⚠ "unpaid" IS A QUESTION, NOT A STATUS. It is the one people actually
          ask, and inventing a sixth state on the document to express it would
          have been the wrong answer to a filtering problem.
        """
        self.assertEqual(self._listed("?status=unpaid"),
                         {PurchaseOrder.Status.APPROVED, PurchaseOrder.Status.DELIVERED})

    def test_a_draft_is_never_unpaid(self):
        """A draft is not owed to anybody — nothing has been committed."""
        self.assertNotIn(PurchaseOrder.Status.DRAFT, self._listed("?status=unpaid"))

    def test_the_buckets_add_up_to_everything(self):
        """⚠ THE SAME SHAPE AS THE SETTLEMENT TEST: the parts must equal the whole."""
        parts = sum(len(self._listed(f"?status={s}")) for s in ("draft", "approved",
                                                                "delivered", "paid"))
        self.assertEqual(parts, len(self._listed()))

    def test_nonsense_is_ignored_rather_than_emptying_the_screen(self):
        """A filter nobody can produce should not look like "no documents"."""
        self.assertEqual(len(self._listed("?status=banana")), 4)

    def test_an_empty_status_is_never_offered(self):
        """
        ⚠ AN EMPTY FILTER OPTION IS A PROMISE THE SCREEN CANNOT KEEP — the rule
          the register's dropdowns already follow.
        """
        self.by_status[PurchaseOrder.Status.PAID].delete()
        offered = dict(self.client.get(f"/projects/{self.project.id}/orders/").context["statuses"])
        self.assertNotIn(PurchaseOrder.Status.PAID, offered)
        self.assertIn(PurchaseOrder.Status.DRAFT, offered)

    def test_the_filter_survives_the_drill_down(self):
        """Narrowing on level 1 and opening a vendor must keep the narrowing."""
        level1 = self.client.get(f"/projects/{self.project.id}/orders/?status=paid")
        self.assertEqual(level1.context["applied"]["status"], "paid")
        self.assertEqual(self._listed("?status=paid"), {PurchaseOrder.Status.PAID})
