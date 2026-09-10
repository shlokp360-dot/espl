"""
The site engineer's stock column.

>>> ANCHOR: BOM-STOCK-ONLY <<<
Saahil: "if the site engineer can edit the site stock in the BOM table… they are
not allowed to change anything else or place an order, but they can just
maintain the stock for that particular BOM line."

⚠⚠ THESE TESTS ARE WHAT MAKES THE MATRIX ROW SAFE. `bom_save` now opens its door
   to a site engineer, because the grid is one form and their two cells arrive
   in the same POST as the vendor rates they may not touch. The permission table
   can only say "the door opened"; only these can say "and nothing else moved".

⚠ THE POSTS BELOW DELIBERATELY CARRY FIELDS THE ENGINEER NEVER SAW. Hiding an
  input is not a permission — a crafted request, or a page rendered before
  somebody's role changed, sends the lot. The refusal being tested is the one on
  the server.
"""
from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Role, UserProfile
from accounts.perms import MATRIX, role_can
from masters.models import Activity, Material, MaterialGroup, Vendor, VendorGroup
from projects.bom_models import Bom, BomLine
from projects.models import Project

User = get_user_model()


class ASiteEngineerWritesStockAndNothingElse(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(username="boss", password="x")
        UserProfile.objects.update_or_create(
            user=cls.admin, defaults={"role": Role.ADMIN, "must_change_password": False})
        cls.engineer = User.objects.create_user(username="site.eng", password="x")
        UserProfile.objects.update_or_create(
            user=cls.engineer, defaults={"role": Role.SITE, "must_change_password": False})

        # ⚠ BUG 19 — the activity master is seeded by migration 0003, so RCC and
        #   the rest are taken. ZQ* is not a trade and never will be.
        cls.activity = Activity.objects.create(abbreviation="ZQS", name="Stock test activity",
                                               rate=D("100"), sort_order=903)
        group = MaterialGroup.objects.create(code="ZQS", name="Stock test group")
        cls.material = Material.objects.create(
            code="ZQS-ZQS-001", name="TEST CEMENT", group=group, home_activity=cls.activity,
            uom="Bag", estimation_rate=D("400"), gst_percent=D("28"))

        vendor_group = VendorGroup.objects.create(name="Stock test suppliers")
        cls.vendor = Vendor.objects.create(code="VEN-S99", name="Delta", phone="9000000099",
                                           group=vendor_group, gst_number="24AAAAA0000A1Z5")

        cls.project = Project.objects.create(name="Stock site", bua_sqft=D("10000"))
        cls.bom = Bom.objects.create(project=cls.project, generated_by=cls.admin)
        cls.line = BomLine.objects.create(
            bom=cls.bom, activity=cls.activity, material=cls.material,
            planned_qty=D("100"), stock_qty=D("10"), min_qty=D("5"),
            vendor=cls.vendor, vendor_rate=D("400"), sort_order=1)

    def save_url(self):
        """
        ⚠ THE STOCK SCREEN POSTS TO ITS OWN ADDRESS, and that address calls the
          SAME _apply_edits the BOM does. Only the redirect differs — a site
          engineer cannot open bom_screen, so returning them there would answer
          403 after a successful save.
        """
        return reverse("stock_save", args=[self.project.id])

    def stock_url(self):
        return f"{reverse('stock_screen', args=[self.project.id])}?activity={self.activity.abbreviation}"

    def everything_post(self, **overrides):
        """One POST carrying every column the grid has, as the real form does."""
        body = {
            "activity": self.activity.abbreviation,
            f"stock-{self.line.id}": "42",
            f"min-{self.line.id}": "7",
            f"plan-{self.line.id}": "999",
            f"ord-{self.line.id}": "888",
            f"vrate-{self.line.id}": "1234",
            f"prate-{self.line.id}": "4321",
            f"vendor-{self.line.id}": "",
            f"remark-{self.line.id}": "typed by somebody who may not",
        }
        body.update(overrides)
        return body

    # ---------------------------------------------------------- the matrix

    def test_the_key_exists_and_is_narrower_than_bom_edit(self):
        self.assertIn("bom.stock", MATRIX)
        self.assertTrue(role_can(Role.SITE, "bom.stock"))
        self.assertFalse(role_can(Role.SITE, "bom.edit"))

    def test_the_engineer_cannot_post_purchase_orders(self):
        """⚠ THE WHOLE REASON bom.stock IS ITS OWN KEY."""
        self.assertFalse(role_can(Role.SITE, "bom.post"))
        self.assertFalse(role_can(Role.SITE, "bom.generate"))

    def test_an_accountant_gets_neither(self):
        """Nobody was handed this by accident — it is Site, not everybody."""
        self.assertFalse(role_can(Role.ACCOUNTANT, "bom.stock"))
        self.assertFalse(role_can(Role.ACCOUNTANT, "bom.view"))

    def test_the_full_grid_went_back_to_the_three_who_had_it(self):
        """⚠ THE REVERSAL, ASSERTED. bom.view must not have drifted wider."""
        self.assertEqual(MATRIX["bom.view"],
                         {Role.ADMIN, Role.PROJECT_MANAGER, Role.PURCHASE})

    # ---------------------------------------------------------- the screen

    def test_the_engineer_cannot_open_the_bill_of_materials_at_all(self):
        """
        ⚠ THIS TEST ASSERTED THE OPPOSITE FOR ONE COMMIT, AND THE REWRITE IS THE
          RECORD. Giving them the stock column first meant giving them bom.view —
          the whole buying grid read-only. Put to Saahil, he chose the narrow
          screen instead: "your suggestion of having only a BOM stock view is
          good." So the full grid is refused again.
        """
        self.client.force_login(self.engineer)
        self.assertEqual(
            self.client.get(reverse("bom_screen", args=[self.project.id])).status_code, 403)

    def test_the_engineer_opens_the_stock_screen(self):
        self.client.force_login(self.engineer)
        response = self.client.get(self.stock_url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["line"] for row in response.context["rows"]], [self.line])

    def test_the_stock_screen_carries_no_money_at_all(self):
        """
        ⚠⚠ THE WHOLE POINT OF THE SCREEN. Not greyed, not read-only — absent.
          A rupee figure appearing here later would be a regression nobody would
          think to look for, because the page would still work perfectly.
        """
        self.client.force_login(self.engineer)
        page = self.client.get(self.stock_url()).content.decode()
        table = page[page.index("<table"):page.index("</table>")]
        for forbidden in ("₹", "Vendor", "PO Value", "Order Qty", "Rate", "Plan Qty"):
            self.assertNotIn(forbidden, table,
                             f"the stock screen is showing {forbidden}")

    def test_only_the_stock_cells_are_typeable(self):
        self.client.force_login(self.engineer)
        page = self.client.get(self.stock_url()).content.decode()
        self.assertIn(f'name="stock-{self.line.id}"', page)
        self.assertIn(f'name="min-{self.line.id}"', page)
        for column in ("plan", "ord", "vrate", "prate", "vendor", "remark"):
            self.assertNotIn(f'name="{column}-{self.line.id}"', page,
                             f"a site engineer was offered the {column} input")

    def test_a_line_holding_nothing_is_still_listed(self):
        """⚠ A screen showing only what is on site cannot record an arrival."""
        self.line.stock_qty = D("0")
        self.line.save(update_fields=["stock_qty"])
        self.client.force_login(self.engineer)
        self.assertEqual(len(self.client.get(self.stock_url()).context["rows"]), 1)

    def test_the_low_flag_is_counted(self):
        self.line.stock_qty, self.line.min_qty = D("1"), D("5")
        self.line.save(update_fields=["stock_qty", "min_qty"])
        self.client.force_login(self.engineer)
        response = self.client.get(self.stock_url())
        self.assertEqual(response.context["low"], 1)
        self.assertTrue(response.context["rows"][0]["below_threshold"])

    # ---------------------------------------------- what actually gets written

    def test_their_stock_figure_is_written(self):
        self.client.force_login(self.engineer)
        self.client.post(self.save_url(), self.everything_post())
        self.line.refresh_from_db()
        self.assertEqual(self.line.stock_qty, D("42"))
        self.assertEqual(self.line.min_qty, D("7"))

    def test_everything_else_in_the_same_post_is_refused(self):
        """
        ⚠⚠ THE TEST THIS FILE EXISTS FOR. The POST carries the plan, the order
          quantity, both rates, the vendor and the remark. None of them may move.
        """
        self.client.force_login(self.engineer)
        self.client.post(self.save_url(), self.everything_post())
        self.line.refresh_from_db()
        self.assertEqual(self.line.planned_qty, D("100"))
        self.assertIsNone(self.line.order_qty_override)
        self.assertEqual(self.line.vendor_rate, D("400"))
        self.assertIsNone(self.line.planned_rate)
        self.assertEqual(self.line.vendor, self.vendor)
        self.assertEqual(self.line.remark, "")

    def test_the_vendor_is_not_cleared_by_a_blank_they_never_saw(self):
        """
        ⚠ NOT THE ORDINARY PATH — `_apply_edits` already skips a key that is not
          in the POST at all, so a browser that never rendered the vendor box
          cannot clear it. This covers the two cases that guard does not: a page
          rendered while somebody still held bom.edit and submitted after their
          role changed, and a hand-crafted POST. Both send `vendor-N=""`.

        ⚠ THE QUIETEST WAY THIS COULD HAVE GONE WRONG. A blank vendor box means
          "no vendor" to the save path, and an engineer's form has no vendor box
          at all — so an unguarded save would have UNSET the vendor on every row
          they touched, and nothing on screen would have said so.
        """
        self.client.force_login(self.engineer)
        self.client.post(self.save_url(), self.everything_post())
        self.line.refresh_from_db()
        self.assertIsNotNone(self.line.vendor)

    def test_an_admin_posting_the_same_body_moves_everything(self):
        """
        The other half of the proof: the refusal is the ROLE, not the code path.
        Posted to the BOM's own save, which is where an Admin actually is.
        """
        self.client.force_login(self.admin)
        self.client.post(reverse("bom_save", args=[self.project.id]), self.everything_post())
        self.line.refresh_from_db()
        self.assertEqual(self.line.stock_qty, D("42"))
        self.assertEqual(self.line.planned_qty, D("999"))
        self.assertEqual(self.line.vendor_rate, D("1234"))
        self.assertEqual(self.line.remark, "typed by somebody who may not")

    def test_the_engineer_cannot_add_or_remove_a_line(self):
        self.client.force_login(self.engineer)
        before = self.bom.lines.count()
        self.assertEqual(
            self.client.post(reverse("bom_add_lines", args=[self.project.id]),
                             {"activity": self.activity.abbreviation,
                              "material": [self.material.id]}).status_code, 403)
        self.assertEqual(
            self.client.post(reverse("bom_remove_line",
                                     args=[self.project.id, self.line.id])).status_code, 403)
        self.assertEqual(self.bom.lines.count(), before)

    def test_stock_still_changes_what_the_system_advises_buying(self):
        """
        ⚠ THIS IS WHY IT IS A NAMED KEY AND NOT A CONVENIENCE. `suggested_order_qty`
          subtracts stock, so the engineer is moving the figure the purchase
          manager reads. That is the point of letting them keep it honest.
        """
        from projects import bom_calc
        self.client.force_login(self.engineer)
        # ⚠ figures_for TAKES A LIST AND RETURNS A LIST, in the same order — it
        #   asks the database three questions in total rather than three per
        #   row. Read the signature; do not assume it is keyed by id.
        def suggestion():
            return bom_calc.figures_for([self.line])[0]["suggested_order_qty"]

        before = suggestion()
        self.client.post(self.save_url(), self.everything_post(**{f"stock-{self.line.id}": "90"}))
        self.line.refresh_from_db()
        self.assertLess(suggestion(), before)
