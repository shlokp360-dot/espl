"""
Splitting a document's money across its lines so it adds back exactly.

>>> ANCHOR: PO-LINE-SHARES <<<
Saahil, 16 Aug 2026, on what the accountant actually does with the export:
*"they filter the values and use that Excel to put it in tally... the header
discounts have to be distributed properly across all the line items that are
present on the PO so the numbers add up properly for them"* — and, on the
arithmetic: *"for ex 1000, if there is a value like thousand, then if it's split
by three line items per say, so it's 333, 333, and 334."*

⚠⚠ THE ONE PROPERTY THAT MATTERS IS THAT THE PARTS SUM TO THE WHOLE, EXACTLY.
   Everything else here is detail. A paisa of disagreement between the Excel and
   the purchase order is enough for somebody to distrust the file and re-key it
   by hand, which is precisely the work this export exists to remove.

⚠ SO THE SUM IS ASSERTED AGAINST `totals()`, NOT AGAINST A NUMBER TYPED INTO THE
  TEST. A hand-written expected total is a second implementation of the ladder,
  and it would be free to be wrong in the same direction as the code.
"""
from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import Role, UserProfile
from masters.models import (Activity, DocumentType, Material, MaterialGroup,
                            Vendor, VendorGroup)
from projects.bom_models import (Bom, BomLine, PurchaseOrder, PurchaseOrderLine,
                                 apportion)
from projects.models import Project

User = get_user_model()


class TheApportionmentItself(TestCase):
    """`apportion()` on its own, with no database in the way."""

    def test_saahils_example(self):
        """
        ⚠ HIS WORDS, AS A TEST. 1000 across three equal lines is 333.33, 333.33
          and 333.34 — and the odd paisa goes to the LAST line, because that is
          the one he described and it is what a reader checking the file expects.
        """
        self.assertEqual(apportion(D("1000"), [D("1"), D("1"), D("1")]),
                         [D("333.33"), D("333.33"), D("333.34")])

    def test_the_parts_always_sum_to_the_whole(self):
        """
        ⚠⚠ THE INVARIANT, over amounts and splits chosen to be awkward on
           purpose — thirds, sevenths, primes and a single paisa.
        """
        amounts = ["0", "0.01", "0.07", "1000", "1234.56", "99999.99", "7", "0.03"]
        splits = [[1], [1, 1], [1, 1, 1], [1, 2, 3], [1, 1, 1, 1, 1, 1, 1],
                  [17, 3, 5], [1, 999], [2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2]]
        for amount in amounts:
            for split in splits:
                shares = apportion(D(amount), [D(w) for w in split])
                self.assertEqual(sum(shares), D(amount),
                                 f"{amount} across {split} did not add back")

    def test_a_negative_total_still_adds_back(self):
        """`round_off` is regularly negative. It must not lose a paisa either."""
        for amount in ["-0.40", "-1000", "-0.01", "-33.33"]:
            shares = apportion(D(amount), [D(1), D(1), D(1)])
            self.assertEqual(sum(shares), D(amount))

    def test_no_share_is_more_than_a_paisa_off_its_true_proportion(self):
        """
        Adding back is necessary but not sufficient — putting the whole amount on
        one line would also add back, and would be nonsense.
        """
        weights = [D(1), D(2), D(3)]
        shares = apportion(D("1000"), weights)
        for share, weight in zip(shares, weights):
            exact = D("1000") * weight / sum(weights)
            self.assertLessEqual(abs(share - exact), D("0.01"))

    def test_zero_weights_split_evenly_rather_than_dividing_by_zero(self):
        shares = apportion(D("10"), [D(0), D(0), D(0)])
        self.assertEqual(sum(shares), D("10"))
        self.assertEqual(len(shares), 3)

    def test_no_lines_is_not_a_crash(self):
        self.assertEqual(apportion(D("100"), []), [])

    def test_a_single_line_takes_all_of_it(self):
        self.assertEqual(apportion(D("1234.56"), [D(1)]), [D("1234.56")])


class TheSharesOnARealDocument(TestCase):
    """
    ⚠ AWKWARD NUMBERS ON PURPOSE — three lines that do not divide evenly, a
      deduction and a TDS percentage with decimals in them, and a GST rate that
      differs per line. Round figures would pass against arithmetic that is
      quietly wrong.
    """

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(username="zq.shares", password="x")
        UserProfile.objects.update_or_create(
            user=cls.admin, defaults={"role": Role.ADMIN, "must_change_password": False})

        # ⚠ BUG 19 — the real activity master is seeded by migration 0003.
        cls.activity = Activity.objects.create(abbreviation="ZQS", name="Share test activity",
                                               rate=D("100"), sort_order=908)
        group = MaterialGroup.objects.create(code="ZQS", name="Share test group")
        vendor_group = VendorGroup.objects.create(name="ZQ Share suppliers")
        cls.vendor = Vendor.objects.create(
            code="VEN-ZQS", name="ZQ Share Supplier", phone="9000000077",
            group=vendor_group, gst_number="24AAAAA0000A1Z5")

        cls.project = Project.objects.create(name="ZQ Share site", bua_sqft=D("10000"))
        cls.bom = Bom.objects.create(project=cls.project, generated_by=cls.admin)

        cls.order = PurchaseOrder.objects.create(
            number="ZQS-0001", project=cls.project, vendor=cls.vendor,
            document_type=DocumentType.PO, created_by=cls.admin,
            deduction_pct=D("2.35"), tds_pct=D("1.75"))

        for index, (qty, rate, gst, disc) in enumerate([
                ("3", "333.33", "18", "0"),
                ("7", "1249.99", "28", "5.5"),
                ("11", "77.77", "5", "0")], start=1):
            material = Material.objects.create(
                code=f"ZQS-ZQS-{index:03d}", name=f"ZQ SHARE MATERIAL {index}",
                group=group, home_activity=cls.activity, uom="Nos",
                estimation_rate=D("100"), gst_percent=D(gst))
            line = BomLine.objects.create(
                bom=cls.bom, activity=cls.activity, material=material,
                planned_qty=D("100"), vendor=cls.vendor, sort_order=index)
            PurchaseOrderLine.objects.create(
                purchase_order=cls.order, bom_line=line, quantity=D(qty),
                rate=D(rate), discount_pct=D(disc), gst_percent=D(gst))

    def test_one_share_per_line(self):
        self.assertEqual(len(self.order.line_shares()), 3)

    def test_the_deduction_adds_back_to_the_document(self):
        totals = self.order.totals()
        shares = self.order.line_shares()
        self.assertEqual(sum(s["deduction"] for s in shares), totals["deduction"])

    def test_the_tds_adds_back_to_the_document(self):
        """
        ⚠⚠ THIS IS THE ONE THAT WAS WRONG IN THE EXPORT. A three-line order used
           to print its TDS three times, so the accountant's SUM was triple.
        """
        totals = self.order.totals()
        shares = self.order.line_shares()
        self.assertEqual(sum(s["tds"] for s in shares), totals["tds"])

    def test_the_round_off_adds_back_to_the_document(self):
        totals = self.order.totals()
        shares = self.order.line_shares()
        self.assertEqual(sum(s["round_off"] for s in shares), totals["round_off"])

    def test_the_order_value_adds_back_to_the_document(self):
        totals = self.order.totals()
        shares = self.order.line_shares()
        self.assertEqual(sum(s["order_value"] for s in shares), totals["order_value"])

    def test_the_net_payable_adds_back_to_the_document(self):
        """The figure that actually leaves the bank, and the one he cares about."""
        totals = self.order.totals()
        shares = self.order.line_shares()
        self.assertEqual(sum(s["net_payable"] for s in shares), totals["net_payable"])

    def test_tds_is_apportioned_on_taxable_and_not_on_the_total(self):
        """
        ⚠⚠ THE BASES ARE NOT INTERCHANGEABLE. TDS is computed on the TAXABLE value
           and never on the GST, so its shares must follow taxable. The three
           lines here carry 18%, 28% and 5% GST, which makes the two bases give
           visibly different answers — with one GST rate this test would pass
           against the wrong base.
        """
        shares = self.order.line_shares()
        taxables = [s["line"].taxable for s in shares]
        expected = apportion(self.order.totals()["tds"], taxables)
        self.assertEqual([s["tds"] for s in shares], expected)

        totals_base = apportion(self.order.totals()["tds"],
                                [s["line"].total for s in shares])
        self.assertNotEqual(expected, totals_base,
                            "the fixture no longer tells the two bases apart")

    def test_deduction_is_apportioned_post_tax(self):
        """It is charged on the invoice value, so it rides on line totals."""
        shares = self.order.line_shares()
        expected = apportion(self.order.totals()["deduction"],
                             [s["line"].total for s in shares])
        self.assertEqual([s["deduction"] for s in shares], expected)

    def test_a_document_with_no_deduction_or_tds_shares_nothing(self):
        self.order.deduction_pct = D("0")
        self.order.tds_pct = D("0")
        self.order.save()
        shares = self.order.line_shares()
        self.assertEqual(sum(s["deduction"] for s in shares), D("0"))
        self.assertEqual(sum(s["tds"] for s in shares), D("0"))
        self.assertEqual(sum(s["order_value"] for s in shares),
                         self.order.totals()["order_value"])

    def test_a_single_line_document_gets_the_whole_figure(self):
        self.order.lines.exclude(id=self.order.lines.first().id).delete()
        totals = self.order.totals()
        share = self.order.line_shares()[0]
        self.assertEqual(share["tds"], totals["tds"])
        self.assertEqual(share["net_payable"], totals["net_payable"])

    def test_it_does_not_recompute_the_ladder(self):
        """
        ⚠ `PO-TOTALS` IS THE ONE IMPLEMENTATION. If `line_shares` derived the
          deduction itself it could disagree with the printed order, which is the
          failure this codebase keeps designing out. Changing the percentage must
          move the shares, because they come from `totals()`.
        """
        before = sum(s["deduction"] for s in self.order.line_shares())
        self.order.deduction_pct = D("5")
        self.order.save()
        after = sum(s["deduction"] for s in self.order.line_shares())
        self.assertNotEqual(before, after)
        self.assertEqual(after, self.order.totals()["deduction"])
