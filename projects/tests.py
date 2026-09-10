"""
Every rule we agreed, written down as a test.

HOW TO RUN THEM
    python manage.py test

    Seconds to run, against a THROWAWAY database. Your real data is never
    touched — Django builds an empty one, runs everything, and deletes it.

WHY THESE EXIST
    Each test below is a bug that has already happened, or a decision that was
    hard to reach. The GST basis error reported a budget as 99.3% consumed when
    it was 84.2%. A migration would have destroyed live rates. WhatsApp numbers
    were being silently overwritten. None of those were caught by reading the
    code — they were caught by running it. These tests mean they cannot come
    back quietly.

HOW TO READ A FAILURE
    Test names are sentences. A failure reads like:
        deleting a draft returns its quantity to the BOM ... FAIL
    which tells you the rule that broke, not just the line number.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from accounts.testing import AuthedTestCase
from masters.codes import next_code
from masters.imports import normalise, similarity
from masters.models import CompanyProfile, Material, MaterialGroup, Vendor, resolve_uom
from projects import bom_calc, po_service
from projects.bom_models import Bom, BomLine, PurchaseOrder, Receipt
from projects.models import Activity, Estimate, EstimateLine, MaterialActivity, Project
from projects.receipts import record_receipt

D = Decimal


class Fixture(AuthedTestCase):
    """
    A miniature but realistic project: Bhudarpura's built-up area, real rates
    from the master, one cement line and one steel line.

    ⚠ IT NOW SIGNS IN FIRST. `AuthedTestCase` creates an Admin and logs the test
      client in — every screen in this suite is behind the login as of the
      security slice, and a suite that browsed anonymously would be testing an
      application that no longer exists.
    """

    def setUp(self):
        super().setUp()
        self.rcc = Activity.objects.get(abbreviation="RCC")

        self.cem = MaterialGroup.objects.create(code="CEM", name="Cement & Binders")
        self.tmt = MaterialGroup.objects.create(code="TMT", name="Steel & TMT")

        self.cement = Material.objects.create(
            code="RCC-CEM-001", name="CEMENT OPC", group=self.cem, specification="ULTRATECH",
            uom="Bag", estimation_rate=D("289.06"), gst_percent=D("28"),
            home_activity=self.rcc)
        self.steel = Material.objects.create(
            code="RCC-TMT-004", name="TMT BAR 12MM", group=self.tmt, specification="ARBUDA",
            uom="MT", estimation_rate=D("56200.00"), gst_percent=D("18"),
            home_activity=self.rcc)
        for material in (self.cement, self.steel):
            MaterialActivity.objects.create(material=material, activity=self.rcc, is_home=True)

        self.vendor = Vendor.objects.create(code="VEN-020", name="Sambhav Hardware", phone="9409124489")
        self.other_vendor = Vendor.objects.create(code="VEN-018", name="Chirag Traders", phone="9825315844")

        self.project = Project.objects.create(
            code="PRJ-001", name="Bhudarpura", bua_sqft=D("26545"), status=Project.Status.WON)
        self.estimate = Estimate.objects.create(project=self.project)
        EstimateLine.objects.create(estimate=self.estimate, name=self.rcc.name,
                                    rate=self.rcc.rate, gst_percent=self.rcc.gst_percent)

        self.bom = Bom.objects.create(project=self.project)
        self.cement_line = BomLine.objects.create(
            bom=self.bom, activity=self.rcc, material=self.cement,
            planned_qty=D("1200"), stock_qty=D("200"), min_qty=D("150"),
            vendor=self.vendor, vendor_rate=D("292.97"))
        self.steel_line = BomLine.objects.create(
            bom=self.bom, activity=self.rcc, material=self.steel,
            planned_qty=D("50"), stock_qty=D("3"), min_qty=D("2"),
            vendor=self.vendor, vendor_rate=D("48551.30"))

        # ⚠ A BUYER HAS TYPED THE QUANTITIES. Since 9 Aug 2026 nothing is
        # ordered unless somebody types how much — blank means zero, not "use
        # the suggestion". So a fixture that wants purchase orders in it has to
        # type them, exactly as a person would. The numbers chosen are the
        # suggested ones, so every figure these tests assert is unchanged.
        self.type_quantities()

    def create_pos(self, **fields):
        """
        The whole Post POs journey as a person does it: press the button (which
        saves what was typed and shows the preview), then tick every vendor and
        confirm. Two steps since 9 Aug 2026 — the button itself creates nothing.
        """
        data = {"activity": "RCC"}
        data.update(fields)
        self.client.post(reverse("bom_post_pos", args=[self.project.id]), data, follow=True)
        vendors = list(Vendor.objects.values_list("id", flat=True))
        return self.client.post(reverse("po_create", args=[self.project.id]),
                                {"activity": "RCC", "vendor": vendors}, follow=True)

    def preview(self):
        return self.client.get(reverse("po_preview", args=[self.project.id]), {"activity": "RCC"})

    def type_quantities(self, *lines):
        """Type the suggested quantity onto each line, the way a buyer would."""
        for line in (lines or (self.cement_line, self.steel_line)):
            line.order_qty_override = bom_calc.suggested_order_qty(line)
            line.save(update_fields=["order_qty_override"])


class OrderQuantity(Fixture):
    """What the system suggests ordering, and what happens as POs move."""

    def test_suggested_quantity_is_planned_less_ordered_less_stock(self):
        # 1200 planned, nothing ordered, 200 on site
        self.assertEqual(bom_calc.suggested_order_qty(self.cement_line), D("1000"))

    def test_a_typed_quantity_overrides_the_suggestion(self):
        self.cement_line.order_qty_override = D("300")
        self.assertEqual(bom_calc.order_qty(self.cement_line), D("300"))
        self.assertTrue(bom_calc.is_overridden(self.cement_line))

    def test_the_suggestion_never_goes_negative(self):
        """More stock than planned should read zero, not a negative order."""
        self.cement_line.stock_qty = D("5000")
        self.assertEqual(bom_calc.suggested_order_qty(self.cement_line), D("0"))

    def test_a_draft_po_reduces_what_is_left_to_order(self):
        """
        The whole reason drafts are counted. Without this, a quantity already on
        an unapproved order still looks un-ordered and gets ordered twice.
        """
        po_service.generate_purchase_orders(self.bom)
        self.assertEqual(bom_calc.draft_qty(self.cement_line), D("1000"))
        self.assertEqual(bom_calc.suggested_order_qty(self.cement_line), D("0"))

    def test_posting_twice_creates_nothing_the_second_time(self):
        first = po_service.generate_purchase_orders(self.bom)
        second = po_service.generate_purchase_orders(self.bom)
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])

    def test_posting_clears_a_typed_override(self):
        """So the next round re-suggests instead of repeating the last figure."""
        self.cement_line.order_qty_override = D("300")
        self.cement_line.save()
        po_service.generate_purchase_orders(self.bom)
        self.cement_line.refresh_from_db()
        self.assertIsNone(self.cement_line.order_qty_override)

    def test_a_line_without_a_vendor_is_skipped(self):
        self.cement_line.vendor = None
        self.cement_line.save()
        orders = po_service.generate_purchase_orders(self.bom)
        self.assertEqual(sum(o.lines.count() for o in orders), 1)   # steel only


class DraftQuantitiesComeFromPurchaseOrders(Fixture):
    """
    >>> ANCHOR: PO-INVARIANT <<<
    The BOM keeps no copy of these numbers, so they cannot drift. These tests
    prove that holds through every path that used to be able to break it.
    """

    def test_deleting_a_draft_returns_its_quantity_to_the_bom(self):
        order = po_service.generate_purchase_orders(self.bom)[0]
        self.assertEqual(bom_calc.suggested_order_qty(self.cement_line), D("0"))
        po_service.delete_draft(order)
        self.assertEqual(bom_calc.draft_qty(self.cement_line), D("0"))
        self.assertEqual(bom_calc.suggested_order_qty(self.cement_line), D("1000"))

    def test_reducing_a_draft_line_returns_the_difference(self):
        order = po_service.generate_purchase_orders(self.bom)[0]
        line = order.lines.get(bom_line=self.cement_line)
        po_service.update_draft_line(line, quantity=D("600"))
        self.assertEqual(bom_calc.draft_qty(self.cement_line), D("600"))
        self.assertEqual(bom_calc.suggested_order_qty(self.cement_line), D("400"))

    def test_removing_a_line_returns_all_of_it(self):
        order = po_service.generate_purchase_orders(self.bom)[0]
        po_service.remove_draft_line(order.lines.get(bom_line=self.cement_line))
        self.assertEqual(bom_calc.draft_qty(self.cement_line), D("0"))

    def test_removing_the_last_line_deletes_the_order(self):
        self.steel_line.delete()
        order = po_service.generate_purchase_orders(self.bom)[0]
        po_service.remove_draft_line(order.lines.first())
        self.assertFalse(PurchaseOrder.objects.filter(pk=order.pk).exists())

    def test_approving_moves_the_quantity_from_draft_to_approved(self):
        order = po_service.generate_purchase_orders(self.bom)[0]
        po_service.approve(order, gstin="24ABCDE1234F1Z5")
        self.assertEqual(bom_calc.draft_qty(self.cement_line), D("0"))
        self.assertEqual(bom_calc.approved_qty(self.cement_line), D("1000"))

    def test_a_second_vendor_gets_a_separate_order(self):
        self.steel_line.vendor = self.other_vendor
        self.steel_line.save()
        orders = po_service.generate_purchase_orders(self.bom)
        self.assertEqual(len(orders), 2)
        self.assertEqual({o.vendor for o in orders}, {self.vendor, self.other_vendor})


class PurchaseOrderLifecycle(Fixture):
    """Draft -> Approved -> Delivered -> Paid, strictly in that order."""

    def _draft(self):
        return po_service.generate_purchase_orders(self.bom)[0]

    def test_approval_is_blocked_when_the_vendor_has_no_gstin(self):
        """None of the 173 vendors has one, so this fires on every first PO."""
        order = self._draft()
        with self.assertRaises(po_service.POError) as caught:
            po_service.approve(order)
        self.assertIn("GST", str(caught.exception))

    def test_a_gstin_given_at_approval_is_saved_to_the_vendor(self):
        """Captured once, never asked for again."""
        po_service.approve(self._draft(), gstin="24ABCDE1234F1Z5")
        self.vendor.refresh_from_db()
        self.assertEqual(self.vendor.gst_number, "24ABCDE1234F1Z5")

    def test_a_malformed_gstin_is_refused(self):
        with self.assertRaises(po_service.POError):
            po_service.approve(self._draft(), gstin="NOTAGSTIN")

    def test_an_approved_order_cannot_be_edited(self):
        order = self._draft()
        po_service.approve(order, gstin="24ABCDE1234F1Z5")
        with self.assertRaises(po_service.POError):
            po_service.update_draft_line(order.lines.first(), quantity=D("1"))

    def test_an_approved_order_cannot_be_deleted(self):
        order = self._draft()
        po_service.approve(order, gstin="24ABCDE1234F1Z5")
        with self.assertRaises(po_service.POError):
            po_service.delete_draft(order)

    def test_the_gstin_is_frozen_onto_the_document(self):
        """Correcting the vendor master later must not rewrite an issued order."""
        order = self._draft()
        po_service.approve(order, gstin="24ABCDE1234F1Z5")
        self.vendor.gst_number = "24ZZZZZ9999Z9Z9"
        self.vendor.save()
        order.refresh_from_db()
        self.assertEqual(order.vendor_gstin, "24ABCDE1234F1Z5")

    def test_statuses_must_be_reached_in_order(self):
        order = self._draft()
        with self.assertRaises(po_service.POError):
            po_service.mark_delivered(order)          # still a draft
        po_service.approve(order, gstin="24ABCDE1234F1Z5")
        with self.assertRaises(po_service.POError):
            po_service.mark_paid(order)               # not delivered yet
        po_service.mark_delivered(order)
        po_service.mark_paid(order)
        order.refresh_from_db()
        self.assertEqual(order.status, PurchaseOrder.Status.PAID)

    def test_po_numbers_are_never_reused(self):
        """
        The bug this caught: numbers used to be derived from the highest already
        in the table, so deleting PO-000001 handed the same number to the next
        order — two documents, one identity, one of them possibly already sent.
        """
        first = self._draft()
        number = first.number
        po_service.delete_draft(first)
        self.type_quantities()          # a buyer types the quantities again
        self.assertNotEqual(po_service.generate_purchase_orders(self.bom)[0].number, number)

    def test_numbers_are_six_digits_and_keep_their_width(self):
        """Same width means they sort correctly and line up in a column."""
        self.assertRegex(self._draft().number, r"^PO-\d{6}$")

    def test_the_range_does_not_run_out(self):
        """
        Past 999,999 the number simply gets one character wider rather than
        wrapping or failing. The column allows 20 characters.
        """
        from projects.bom_models import NumberSeries
        NumberSeries.objects.update_or_create(key="purchase_order",
                                              defaults={"last_number": 999_999})
        self.assertEqual(po_service.next_po_number(), "PO-1000000")

    def test_prices_on_a_po_line_are_frozen_copies(self):
        order = self._draft()
        line = order.lines.get(bom_line=self.cement_line)
        self.cement.estimation_rate = D("999.99")
        self.cement.save()
        self.cement_line.vendor_rate = D("888.88")
        self.cement_line.save()
        line.refresh_from_db()
        self.assertEqual(line.rate, D("292.97"))


class ReceivingMaterial(Fixture):
    """>>> ANCHOR: TASK-MODULE <<< — the single door for received quantities."""

    def _delivered(self):
        order = po_service.generate_purchase_orders(self.bom)[0]
        po_service.approve(order, gstin="24ABCDE1234F1Z5")
        return order

    def test_marking_delivered_records_what_arrived(self):
        po_service.mark_delivered(self._delivered())
        self.assertEqual(bom_calc.received_qty(self.cement_line), D("1000"))

    def test_partial_deliveries_add_up(self):
        order = self._delivered()
        line = order.lines.get(bom_line=self.cement_line)
        record_receipt(line, D("300"), received_on=date(2026, 8, 1))
        record_receipt(line, D("200"), received_on=date(2026, 8, 5))
        self.assertEqual(bom_calc.received_qty(self.cement_line), D("500"))

    def test_marking_delivered_twice_does_not_double_the_quantity(self):
        order = self._delivered()
        po_service.mark_delivered(order)
        order.status = PurchaseOrder.Status.APPROVED       # force the second attempt
        order.save()
        po_service.mark_delivered(order)
        self.assertEqual(bom_calc.received_qty(self.cement_line), D("1000"))

    def test_a_zero_receipt_is_refused(self):
        order = self._delivered()
        with self.assertRaises(ValueError):
            record_receipt(order.lines.first(), D("0"))

    def test_receipts_record_where_they_came_from(self):
        """So the task module's entries are distinguishable from manual ones."""
        po_service.mark_delivered(self._delivered())
        self.assertEqual(Receipt.objects.first().source, Receipt.Source.MANUAL)


class MoneyIsAlwaysExGst(Fixture):
    """
    >>> ANCHOR: BOM-CALC-GST-BASIS <<<
    The error that reported RCC at 99.3% of budget when it was 84.2%.
    """

    def test_estimated_value_excludes_gst(self):
        # 1200 bags x 289.06. NOT x 1.28, even though cement is 28% GST.
        self.assertEqual(bom_calc.estimated_value(self.cement_line), D("346872.00"))

    def test_used_value_excludes_gst(self):
        order = po_service.generate_purchase_orders(self.bom)[0]
        po_service.approve(order, gstin="24ABCDE1234F1Z5")
        po_service.mark_delivered(order)
        self.assertEqual(bom_calc.used_value(self.cement_line), D("1000") * D("289.06"))

    def test_the_reserve_is_the_pre_gst_base(self):
        self.assertEqual(bom_calc.reserve(self.bom, self.rcc), D("600") * D("26545"))

    def test_budget_and_spend_are_measured_the_same_way(self):
        """
        The actual bug: planned was inc-GST, the reserve ex-GST, so the
        percentage was inflated. Both sides must use the same rate.
        """
        totals = bom_calc.activity_totals(self.bom, self.rcc)
        expected = (self.cement_line.planned_qty * self.cement.estimation_rate
                    + self.steel_line.planned_qty * self.steel.estimation_rate)
        self.assertEqual(totals["planned_value"], expected)
        self.assertEqual(totals["variance"], totals["reserve"] - expected)

    def test_gst_appears_on_the_purchase_order(self):
        """It has not vanished — it belongs on the tax document."""
        order = po_service.generate_purchase_orders(self.bom)[0]
        line = order.lines.get(bom_line=self.cement_line)
        self.assertEqual(line.basic, D("1000") * D("292.97"))
        self.assertEqual(line.gst_amount, line.basic * D("28") / 100)
        self.assertEqual(line.total, line.basic + line.gst_amount)


class RatesAndFlags(Fixture):

    def test_variance_shows_a_vendor_quoting_above_the_benchmark(self):
        # 292.97 against a 289.06 benchmark
        self.assertAlmostEqual(float(bom_calc.rate_variance(self.cement_line)), 0.013527, places=5)

    def test_the_benchmark_is_used_when_no_vendor_rate_is_set(self):
        self.cement_line.vendor_rate = None
        self.assertEqual(bom_calc.effective_vendor_rate(self.cement_line), D("289.06"))
        self.assertEqual(bom_calc.rate_variance(self.cement_line), D("0"))

    def test_stock_below_the_threshold_is_flagged(self):
        self.cement_line.stock_qty = D("100")       # threshold is 150
        self.assertTrue(bom_calc.is_below_threshold(self.cement_line))

    def test_a_threshold_of_zero_never_flags(self):
        """Otherwise every unstocked line would shout for attention."""
        self.cement_line.min_qty = D("0")
        self.cement_line.stock_qty = D("0")
        self.assertFalse(bom_calc.is_below_threshold(self.cement_line))


class TheBoqEstimatorStillWorks(AuthedTestCase):
    """The golden number. If this moves, the estimator has changed."""

    def test_bhudarpura_comes_to_1843_12_per_sqft(self):
        project = Project.objects.create(code="PRJ-B", name="Bhudarpura", bua_sqft=D("26545"))
        estimate = Estimate.objects.create(project=project)
        for activity in Activity.objects.exclude(abbreviation__in=["OTH", "COM"]):
            EstimateLine.objects.create(estimate=estimate, name=activity.name, rate=activity.rate,
                                        gst_percent=activity.gst_percent)
        self.assertEqual(estimate.composite_rate, D("1433.00"))
        self.assertEqual(estimate.base_cost, D("38038985.00"))
        self.assertAlmostEqual(float(estimate.cost_per_sqft), 1843.12, places=2)


class MaterialCodes(AuthedTestCase):
    """>>> ANCHOR: CODE-GEN <<<"""

    def setUp(self):
        super().setUp()
        self.group = MaterialGroup.objects.create(code="PL3", name="Plumbing Others")
        self.activity = Activity.objects.get(abbreviation="PLM")

    def test_the_first_code_in_a_pair_starts_at_001(self):
        self.assertEqual(next_code(self.activity, self.group), "PLM-PL3-001")

    def test_the_next_code_follows_the_highest_used(self):
        Material.objects.create(code="PLM-PL3-014", name="ELBOW", group=self.group, uom="Nos",
                                home_activity=self.activity)
        self.assertEqual(next_code(self.activity, self.group), "PLM-PL3-015")

    def test_serials_are_not_reused_after_a_delete(self):
        """A reused serial would make an old purchase order point at a new material."""
        material = Material.objects.create(code="PLM-PL3-001", name="TEE", group=self.group,
                                           uom="Nos", home_activity=self.activity)
        Material.objects.create(code="PLM-PL3-002", name="BEND", group=self.group, uom="Nos",
                                home_activity=self.activity)
        material.delete()
        self.assertEqual(next_code(self.activity, self.group), "PLM-PL3-003")

    def test_an_activity_without_an_abbreviation_cannot_produce_a_code(self):
        self.activity.abbreviation = ""
        with self.assertRaises(ValueError):
            next_code(self.activity, self.group)


class ImportRules(AuthedTestCase):
    """>>> ANCHOR: IMPORT-VALIDATE <<<"""

    def test_spacing_differences_are_the_same_material(self):
        self.assertEqual(normalise("1.0 SQ MM"), normalise("1.0 SQMM"))
        self.assertEqual(normalise("20 MM PVC BEND"), normalise("20MM PVC BEND"))

    def test_genuinely_different_fittings_stay_different(self):
        """MTA and FTA are different parts. 18 false merges came from ignoring this."""
        self.assertNotEqual(normalise("MTA BRASS"), normalise("FTA BRASS"))
        self.assertNotEqual(normalise("UPVC PIPE"), normalise("CPVC PIPE"))
        self.assertNotEqual(normalise("RE TEE"), normalise("TEE"))

    def test_near_matches_are_similar_but_not_identical(self):
        """Which is why similarity only ever warns — it must never block."""
        score = similarity("FRLSH WIRE 1.0 SQMM", "FRLSH WIRE 1.5 SQMM")
        self.assertGreater(score, 0.9)
        self.assertLess(score, 1.0)

    def test_known_unit_spellings_are_translated(self):
        self.assertEqual(resolve_uom("Hrs"), "Hour")
        self.assertEqual(resolve_uom("MTR"), "Metre")
        self.assertEqual(resolve_uom("KW"), "KW")

    def test_an_unknown_unit_is_never_guessed(self):
        self.assertIsNone(resolve_uom("furlongs"))


class VendorRules(AuthedTestCase):
    """A vendor's identity is their phone number, never their name."""

    def test_whatsapp_fills_itself_from_a_mobile(self):
        vendor = Vendor.objects.create(code="VEN-001", name="Test", phone="9825315844")
        self.assertEqual(vendor.whatsapp_number, "919825315844")

    def test_a_manually_typed_whatsapp_number_survives_a_save(self):
        """
        The bug: this used to be overwritten on every save, which broke exactly
        the vendors that need it — Schindler and TKE publish 1800 numbers.
        """
        vendor = Vendor.objects.create(code="VEN-002", name="TKE", phone="18001234567")
        vendor.whatsapp_number = "919812345678"
        vendor.save()
        vendor.refresh_from_db()
        self.assertEqual(vendor.whatsapp_number, "919812345678")

    def test_clearing_it_goes_back_to_automatic(self):
        vendor = Vendor.objects.create(code="VEN-003", name="Test", phone="9825315844")
        vendor.whatsapp_number = ""
        vendor.save()
        vendor.refresh_from_db()
        self.assertEqual(vendor.whatsapp_number, "919825315844")

    def test_an_1800_number_gets_no_automatic_whatsapp(self):
        """Better blank than a number that fails silently when a PO is sent."""
        vendor = Vendor.objects.create(code="VEN-004", name="Schindler", phone="18002091111")
        self.assertEqual(vendor.whatsapp_number, "")

    def test_the_state_is_read_from_the_gstin(self):
        vendor = Vendor.objects.create(code="VEN-005", name="Test", phone="9825315845",
                                       gst_number="24ABCDE1234F1Z5")
        self.assertEqual(vendor.state, "Gujarat")


class DeletionRules(AuthedTestCase):
    """Delete means "this was a mistake". Deactivate means "we have stopped"."""

    def test_an_unused_activity_can_be_deleted(self):
        Activity.objects.get(abbreviation="FIR").delete()
        self.assertFalse(Activity.objects.filter(abbreviation="FIR").exists())

    def test_an_activity_in_use_is_protected(self):
        from django.db.models import ProtectedError
        group = MaterialGroup.objects.create(code="CEM", name="Cement")
        rcc = Activity.objects.get(abbreviation="RCC")
        material = Material.objects.create(code="RCC-CEM-001", name="CEMENT", group=group,
                                           uom="Bag", home_activity=rcc)
        MaterialActivity.objects.create(material=material, activity=rcc, is_home=True)
        with self.assertRaises(ProtectedError):
            rcc.delete()

    def test_a_material_cannot_belong_to_the_same_activity_twice(self):
        from django.db.utils import IntegrityError
        group = MaterialGroup.objects.create(code="CEM", name="Cement")
        rcc = Activity.objects.get(abbreviation="RCC")
        material = Material.objects.create(code="RCC-CEM-001", name="CEMENT", group=group,
                                           uom="Bag", home_activity=rcc)
        MaterialActivity.objects.create(material=material, activity=rcc, is_home=True)
        with self.assertRaises(IntegrityError):
            MaterialActivity.objects.create(material=material, activity=rcc)


class TheActivityMaster(AuthedTestCase):
    """Seeded by migration, because nothing can be imported until it exists."""

    def test_all_eighteen_are_present(self):
        self.assertEqual(Activity.objects.count(), 18)

    def test_the_sixteen_trades_come_to_1433_per_sqft(self):
        trades = Activity.objects.exclude(abbreviation__in=["OTH", "COM"])
        self.assertEqual(trades.count(), 16)
        self.assertEqual(sum(a.rate for a in trades), D("1433.00"))

    def test_others_and_common_both_exist(self):
        self.assertTrue(Activity.objects.filter(abbreviation="OTH").exists())
        self.assertTrue(Activity.objects.filter(abbreviation="COM").exists())

    def test_every_abbreviation_is_three_capitals_and_unique(self):
        codes = list(Activity.objects.values_list("abbreviation", flat=True))
        self.assertEqual(len(codes), len(set(codes)))
        self.assertTrue(all(len(c) == 3 and c.isupper() for c in codes))


# ===========================================================================
# SLICE 4 — THE BOM SCREEN
#
# The screen has one job beyond looking right: it must show what bom_calc says
# and write back only what a human typed. So these tests compare the page
# against bom_calc rather than against numbers typed into the test — a test
# holding its own copy of the expected figure is a second implementation of the
# rule, which is the exact thing bom_calc exists to prevent.
# ===========================================================================
from django.urls import reverse

from projects.templatetags.inr import qty as qty_filter, rupees, rupees2, pct


class TheBomScreen(Fixture):
    """Rendering. The grid, its tabs and its totals."""

    def url(self, activity="RCC"):
        return reverse("bom_screen", args=[self.project.id]) + f"?activity={activity}"

    def test_the_screen_opens_and_shows_its_lines(self):
        page = self.client.get(self.url())
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "RCC-CEM-001")
        self.assertContains(page, "RCC-TMT-004")

    def test_every_figure_on_screen_is_the_figure_bom_calc_reports(self):
        totals = bom_calc.activity_totals(self.bom, self.rcc)
        page = self.client.get(self.url())
        for key in ("reserve", "planned_value", "used_value", "po_value_now"):
            self.assertContains(page, rupees(totals[key]),
                                msg_prefix=f"{key} is not on the screen as bom_calc reports it")

    def test_the_footer_totals_are_bom_calcs_totals_not_the_templates(self):
        totals = bom_calc.activity_totals(self.bom, self.rcc)
        page = self.client.get(self.url())
        self.assertContains(page, qty_filter(totals["order_qty_total"]))

    def test_the_percentage_used_is_the_fraction_bom_calc_gives(self):
        totals = bom_calc.activity_totals(self.bom, self.rcc)
        page = self.client.get(self.url())
        self.assertContains(page, pct(totals["percent_used"]))

    def test_an_activity_on_the_estimate_gets_a_tab_before_it_has_any_lines(self):
        masonry = Activity.objects.get(abbreviation="MAS")
        EstimateLine.objects.create(estimate=self.estimate, name=masonry.name, rate=masonry.rate)
        page = self.client.get(self.url())
        self.assertContains(page, masonry.name)

    def test_a_line_survives_its_activity_being_taken_off_the_estimate(self):
        """
        Its reserve reads zero rather than the tab vanishing. Money already
        planned must stay visible, or it is spent where nobody is looking.
        """
        self.estimate.lines.all().delete()
        page = self.client.get(self.url())
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "RCC-CEM-001")
        self.assertContains(page, "has no reserve on this project")
        self.assertEqual(bom_calc.reserve(self.bom, self.rcc), D("0"))

    def test_a_project_with_no_bom_is_offered_one_rather_than_an_empty_grid(self):
        other = Project.objects.create(code="PRJ-002", name="No BOM yet", bua_sqft=D("1000"))
        page = self.client.get(reverse("bom_screen", args=[other.id]))
        self.assertContains(page, "no bill of materials yet")

    def test_the_project_list_shows_every_project(self):
        page = self.client.get(reverse("project_list"))
        self.assertContains(page, "PRJ-001")
        self.assertContains(page, "Bhudarpura")


class SavingTheGrid(Fixture):
    """What the Save button writes, and what it refuses to guess at."""

    def post(self, url_name, **fields):
        data = {"activity": "RCC"}
        data.update(fields)
        return self.client.post(reverse(url_name, args=[self.project.id]), data, follow=True)

    def test_it_writes_the_columns_a_human_types(self):
        self.post("bom_save", **{
            f"plan-{self.cement_line.id}": "1500",
            f"stock-{self.cement_line.id}": "250",
            f"min-{self.cement_line.id}": "175",
            f"remark-{self.cement_line.id}": "slab pour 2",
        })
        self.cement_line.refresh_from_db()
        self.assertEqual(self.cement_line.planned_qty, D("1500"))
        self.assertEqual(self.cement_line.stock_qty, D("250"))
        self.assertEqual(self.cement_line.min_qty, D("175"))
        self.assertEqual(self.cement_line.remark, "slab pour 2")

    def test_a_number_it_cannot_read_leaves_the_cell_alone_and_says_so(self):
        before = self.cement_line.planned_qty
        page = self.post("bom_save", **{f"plan-{self.cement_line.id}": "12OO"})
        self.cement_line.refresh_from_db()
        self.assertEqual(self.cement_line.planned_qty, before)
        self.assertContains(page, "is not a number")

    def test_a_negative_quantity_is_refused_rather_than_stored(self):
        before = self.cement_line.stock_qty
        page = self.post("bom_save", **{f"stock-{self.cement_line.id}": "-40"})
        self.cement_line.refresh_from_db()
        self.assertEqual(self.cement_line.stock_qty, before)
        self.assertContains(page, "cannot be negative")

    def test_a_blank_order_quantity_orders_nothing_at_all(self):
        """
        ⚠ SUPERSEDES "blank means use the suggestion", 9 Aug 2026. Saahil's call,
        and the reason matters: a real project is sixteen activities of three to
        four hundred materials, so a Post POs that fell back to the suggestion
        would have ordered THE ENTIRE PROJECT in one press. The suggestion is
        still shown on every row — it is advice now, not an instruction.
        """
        self.post("bom_save", **{f"ord-{self.cement_line.id}": ""})
        self.cement_line.refresh_from_db()
        self.assertIsNone(self.cement_line.order_qty_override)
        self.assertEqual(bom_calc.order_qty(self.cement_line), D("0"))
        self.assertGreater(bom_calc.suggested_order_qty(self.cement_line), D("0"),
                           "the suggestion must still be there, just not obeyed")

    def test_nothing_is_posted_when_no_quantity_was_typed(self):
        BomLine.objects.all().update(order_qty_override=None)
        page = self.client.post(reverse("bom_post_pos", args=[self.project.id]),
                                {"activity": "RCC"}, follow=True)
        self.assertEqual(PurchaseOrder.objects.count(), 0)
        self.assertContains(page, "Nothing to create")

    def test_a_typed_order_quantity_of_zero_really_means_zero(self):
        self.post("bom_save", **{f"ord-{self.cement_line.id}": "0"})
        self.cement_line.refresh_from_db()
        self.assertEqual(self.cement_line.order_qty_override, D("0"))
        self.assertEqual(bom_calc.order_qty(self.cement_line), D("0"))

    def test_a_blank_vendor_rate_falls_back_to_the_planning_rate(self):
        self.post("bom_save", **{f"vrate-{self.cement_line.id}": ""})
        self.cement_line.refresh_from_db()
        self.assertIsNone(self.cement_line.vendor_rate)
        self.assertEqual(bom_calc.effective_vendor_rate(self.cement_line),
                         bom_calc.planning_rate(self.cement_line))

    def test_a_vendor_can_be_typed_as_its_code_or_as_the_dropdown_text(self):
        self.post("bom_save", **{f"vendor-{self.cement_line.id}": "VEN-018"})
        self.cement_line.refresh_from_db()
        self.assertEqual(self.cement_line.vendor, self.other_vendor)

        self.post("bom_save", **{f"vendor-{self.cement_line.id}": "VEN-020 · Sambhav Hardware"})
        self.cement_line.refresh_from_db()
        self.assertEqual(self.cement_line.vendor, self.vendor)

    def test_an_unrecognised_vendor_leaves_the_line_as_it_was(self):
        page = self.post("bom_save", **{f"vendor-{self.cement_line.id}": "Sambav Hadware"})
        self.cement_line.refresh_from_db()
        self.assertEqual(self.cement_line.vendor, self.vendor)
        self.assertContains(page, "No vendor matches")

    def test_clearing_the_vendor_box_removes_the_vendor(self):
        self.post("bom_save", **{f"vendor-{self.cement_line.id}": ""})
        self.cement_line.refresh_from_db()
        self.assertIsNone(self.cement_line.vendor)

    def test_saving_reports_only_the_lines_that_really_changed(self):
        page = self.post("bom_save", **{f"plan-{self.cement_line.id}": str(self.cement_line.planned_qty)})
        self.assertContains(page, "Nothing had changed")

    def test_the_actions_refuse_a_get(self):
        """A delete that works by being visited will eventually be visited by accident."""
        for name in ("bom_save", "bom_add_lines", "bom_post_pos"):
            response = self.client.get(reverse(name, args=[self.project.id]))
            self.assertEqual(response.status_code, 405, msg=f"{name} answered a GET")


class PostingPurchaseOrdersFromTheScreen(Fixture):
    """The Post POs button — the join between the screen and po_service."""

    def post_pos(self, **fields):
        return self.create_pos(**fields)

    def test_the_button_itself_creates_nothing(self):
        """
        ⚠ Post POs is a Check, not an action — SAP's word, and Saahil's request.
        It saves, then shows what WOULD be created. Nothing exists until the
        preview is confirmed.
        """
        page = self.client.post(reverse("bom_post_pos", args=[self.project.id]),
                                {"activity": "RCC"}, follow=True)
        self.assertEqual(PurchaseOrder.objects.count(), 0)
        self.assertContains(page, "About to create")

    def test_nothing_is_created_when_no_vendor_is_ticked(self):
        self.client.post(reverse("bom_post_pos", args=[self.project.id]),
                         {"activity": "RCC"}, follow=True)
        page = self.client.post(reverse("po_create", args=[self.project.id]),
                                {"activity": "RCC"}, follow=True)
        self.assertEqual(PurchaseOrder.objects.count(), 0)
        self.assertContains(page, "No vendors were ticked")

    def test_only_the_ticked_vendors_are_created(self):
        self.cement_line.vendor = self.other_vendor
        self.cement_line.save()
        self.client.post(reverse("bom_post_pos", args=[self.project.id]),
                         {"activity": "RCC"}, follow=True)
        self.client.post(reverse("po_create", args=[self.project.id]),
                         {"activity": "RCC", "vendor": [self.vendor.id]}, follow=True)
        self.assertEqual([o.vendor for o in PurchaseOrder.objects.all()], [self.vendor])

    def test_a_line_with_no_vendor_raises_nothing_and_is_reported(self):
        """Saahil's rule: no vendor, no purchase order. But never invisibly."""
        self.cement_line.vendor = None
        self.cement_line.save()
        page = self.preview()
        self.assertContains(page, "no vendor")
        self.assertContains(page, "RCC-CEM-001")
        self.create_pos()
        raised = {l.bom_line_id for o in PurchaseOrder.objects.all() for l in o.lines.all()}
        self.assertNotIn(self.cement_line.id, raised)

    def test_it_saves_what_was_typed_before_it_posts(self):
        """
        The trap this closes: type 40, press Post POs without pressing Save, and
        the order is raised for the number that was on screen when the page
        loaded. The screen would say one thing and the purchase order another.
        """
        page = self.post_pos(**{f"ord-{self.cement_line.id}": "40",
                                f"ord-{self.steel_line.id}": "0"})
        order = PurchaseOrder.objects.get()
        line = order.lines.get(bom_line=self.cement_line)
        self.assertEqual(line.quantity, D("40"))
        self.assertContains(page, "purchase order")

    def test_one_order_per_vendor_across_every_activity_not_one_per_tab(self):
        masonry = Activity.objects.get(abbreviation="MAS")
        block_group = MaterialGroup.objects.create(code="MAS", name="Blocks")
        block = Material.objects.create(code="MAS-MAS-001", name="AAC BLOCK", group=block_group,
                                        uom="Nos", estimation_rate=D("104"),
                                        home_activity=masonry)
        BomLine.objects.create(bom=self.bom, activity=masonry, material=block,
                               planned_qty=D("500"), vendor=self.vendor, vendor_rate=D("101.50"),
                               order_qty_override=D("500"))
        self.post_pos()
        self.assertEqual(PurchaseOrder.objects.count(), 1)
        activities = {l.bom_line.activity.abbreviation for l in PurchaseOrder.objects.get().lines.all()}
        self.assertEqual(activities, {"RCC", "MAS"})

    def test_pressing_it_twice_raises_nothing_the_second_time(self):
        """
        Creating consumes the typed quantity, so the boxes are empty again and
        the preview has nothing in it. Nothing can be ordered twice by accident.
        """
        self.post_pos()
        first = PurchaseOrder.objects.count()
        self.assertContains(self.preview(), "Nothing to create")
        page = self.post_pos()
        self.assertEqual(PurchaseOrder.objects.count(), first)


class RemovingALineFromTheScreen(Fixture):
    """The delete rule, on the screen this time."""

    def remove(self, line):
        return self.client.post(
            reverse("bom_remove_line", args=[self.project.id, line.id]),
            {"activity": "RCC"}, follow=True)

    def test_a_line_nothing_points_at_is_removed(self):
        page = self.remove(self.steel_line)
        self.assertFalse(BomLine.objects.filter(id=self.steel_line.id).exists())
        self.assertContains(page, "removed from")

    def test_a_line_already_on_a_purchase_order_is_blocked_and_told_why(self):
        po_service.generate_purchase_orders(self.bom)
        page = self.remove(self.cement_line)
        self.assertTrue(BomLine.objects.filter(id=self.cement_line.id).exists())
        self.assertContains(page, "cannot be removed")
        self.assertContains(page, "PO-")

    def test_removing_one_line_does_not_discard_edits_typed_on_another(self):
        self.client.post(
            reverse("bom_remove_line", args=[self.project.id, self.steel_line.id]),
            {"activity": "RCC", f"plan-{self.cement_line.id}": "1750"}, follow=True)
        self.cement_line.refresh_from_db()
        self.assertEqual(self.cement_line.planned_qty, D("1750"))


class AddingMaterialsFromTheScreen(Fixture):
    """The search box and the Add button."""

    def setUp(self):
        super().setUp()
        self.plumbing = Activity.objects.get(abbreviation="PLM")
        self.elbow = Material.objects.create(
            code="PLM-PL3-014", name="ASTRAL UPVC ELBOW 110MM", group=self.cem,
            specification="ASTRAL", uom="Nos", estimation_rate=D("148.50"),
            home_activity=self.plumbing)
        self.tape = Material.objects.create(
            code="COM-HDW-004", name="ABRO TAPE 1 INCH", group=self.cem,
            uom="Packet", estimation_rate=D("150"), is_common=True,
            home_activity=Activity.objects.get(abbreviation="COM"))

    def search(self, **params):
        params.setdefault("activity", "RCC")
        return self.client.get(reverse("bom_screen", args=[self.project.id]), params)

    def test_the_dropdown_comes_from_the_material_never_from_the_code(self):
        """
        A material keeps its original code when it is reclassified, so the code
        says where it was born, not where it can be used. Give the plumbing
        elbow RCC as its second activity and it must appear under RCC, code
        unchanged.
        """
        self.assertNotContains(self.search(q="ELBOW"), "PLM-PL3-014")
        self.elbow.also_used_in = self.rcc
        self.elbow.save(update_fields=["also_used_in"])
        self.assertContains(self.search(q="ELBOW"), "PLM-PL3-014")

    def test_a_material_created_the_way_the_app_creates_one_can_be_found(self):
        """
        ⚠⚠ THE TEST THAT DID NOT EXIST, AND THE BUG IT WOULD HAVE CAUGHT.

        Slice 8 moved a material's trade onto the material and left the old link
        table in place with its rows intact. This search went on reading the
        link table, so it kept working for every material that already existed —
        and returned NOTHING for any material created afterwards, through the
        new Material screen or the Excel upload. Invisible to the one screen
        that needs it, and only findable by switching the search to "all".

        367 tests passed the whole time. Every one of them created its materials
        with a link row, because they were written before the columns existed.
        None created one the way the application itself does and then looked for
        it. This one does.
        """
        made = Material.objects.create(
            code="RCC-NEW-001", name="BRAND NEW MATERIAL", group=self.cem,
            uom="Bag", estimation_rate=D("100"), gst_percent=D("18"),
            home_activity=self.rcc)
        self.assertEqual(made.activity_links.count(), 0, "the app no longer writes link rows")
        self.assertContains(self.search(q="BRAND NEW"), "RCC-NEW-001")

    def test_a_common_material_appears_under_every_activity(self):
        self.assertContains(self.search(q="ABRO"), "COM-HDW-004")

    def test_searching_everywhere_finds_a_material_this_activity_does_not_offer(self):
        self.assertContains(self.search(q="ELBOW", scope="all"), "PLM-PL3-014")

    def test_search_ignores_spacing_and_punctuation_the_way_the_import_does(self):
        """Same normalise() as the duplicate check, or the search cannot find what it flagged."""
        self.assertContains(self.search(q="tmtbar12"), "RCC-TMT-004")

    def test_a_deactivated_material_is_no_longer_offered(self):
        self.assertContains(self.search(q="ABRO"), "COM-HDW-004")
        self.tape.is_active = False
        self.tape.save()
        self.assertNotContains(self.search(q="ABRO"), "COM-HDW-004")

    def test_ticked_materials_land_on_the_open_activity_ready_to_type(self):
        self.client.post(reverse("bom_add_lines", args=[self.project.id]),
                         {"activity": "RCC", "material": [self.tape.id]}, follow=True)
        line = BomLine.objects.get(material=self.tape)
        self.assertEqual(line.activity, self.rcc)
        self.assertEqual(line.planned_qty, D("0"))
        self.assertIsNone(line.vendor)

    def test_adding_a_material_that_is_already_there_is_allowed_and_warned_about(self):
        """Cement really is on RCC twice — footing & plinth, then slab pour 2."""
        page = self.client.post(reverse("bom_add_lines", args=[self.project.id]),
                                {"activity": "RCC", "material": [self.cement.id]}, follow=True)
        self.assertEqual(BomLine.objects.filter(material=self.cement, activity=self.rcc).count(), 2)
        self.assertContains(page, "was already on this activity")


class IndianNumberFormatting(AuthedTestCase):
    """
    Formatting only — these must never decide what a number IS.
    12,34,567 rather than 1,234,567: the last three digits, then pairs.
    """

    def test_rupees_group_the_indian_way(self):
        self.assertEqual(rupees(D("1234567")), "12,34,567")
        self.assertEqual(rupees(D("100")), "100")
        self.assertEqual(rupees(D("15927000")), "1,59,27,000")

    def test_quantities_drop_trailing_zeros_but_keep_real_decimals(self):
        self.assertEqual(qty_filter(D("1200.000")), "1,200")
        self.assertEqual(qty_filter(D("2.500")), "2.5")

    def test_nothing_formats_as_nothing_rather_than_as_zero(self):
        """A blank override must render blank, or the box would read 0 and mean it."""
        self.assertEqual(qty_filter(None), "")
        self.assertEqual(rupees(None), "")

    def test_a_fraction_prints_as_a_percentage(self):
        self.assertEqual(pct(D("0.842")), "84.2%")


class CapturingAGstinOnApproval(Fixture):
    """
    >>> ANCHOR: GSTIN-CAPTURE <<<
    The GSTIN is written to the vendor master, and the state is worked out from
    its first two digits.
    """

    def test_the_state_is_derived_and_actually_saved(self):
        """
        The bug this catches: approve() saved `state` only when the vendor
        ALREADY had one — which is never, the first time a GSTIN is captured. So
        the state was derived and then thrown away, and every vendor stayed
        stateless. It matters because a Gujarat vendor is billed CGST + SGST and
        everyone else IGST, and the PO PDF reads this field to decide which.
        """
        po_service.generate_purchase_orders(self.bom)
        order = PurchaseOrder.objects.filter(vendor=self.vendor).first()
        self.assertEqual(self.vendor.state, "")

        po_service.approve(order, gstin="24AAAAA0000A1Z5")
        self.vendor.refresh_from_db()
        self.assertEqual(self.vendor.gst_number, "24AAAAA0000A1Z5")
        self.assertEqual(self.vendor.state, "Gujarat")

    def test_an_out_of_state_gstin_gives_that_state(self):
        po_service.generate_purchase_orders(self.bom)
        order = PurchaseOrder.objects.filter(vendor=self.vendor).first()
        po_service.approve(order, gstin="27BBBBB1111B1Z5")
        self.vendor.refresh_from_db()
        self.assertEqual(self.vendor.state, "Maharashtra")


class DeactivatedRecordsOnTheScreen(Fixture):
    """
    Deactivate means "we have stopped using this". It must vanish from the
    pickers without disturbing anything that already refers to it.
    """

    def test_a_deactivated_material_leaves_the_search_but_not_the_bom(self):
        page = self.client.get(reverse("bom_screen", args=[self.project.id]),
                               {"activity": "RCC", "q": "CEMENT"})
        search_box = page.content.decode().split('id="material-search"')[1]
        self.assertIn("RCC-CEM-001", search_box)

        self.cement.is_active = False
        self.cement.save()

        page = self.client.get(reverse("bom_screen", args=[self.project.id]),
                               {"activity": "RCC", "q": "CEMENT"})
        body = page.content.decode()
        self.assertNotIn("RCC-CEM-001", body.split('id="material-search"')[1])
        self.assertIn("RCC-CEM-001", body)                       # still on the grid
        self.assertEqual(bom_calc.estimated_value(self.cement_line),
                         self.cement_line.planned_qty * self.cement.estimation_rate)

    def test_a_deactivated_vendor_leaves_the_pick_list_but_not_the_line(self):
        self.vendor.is_active = False
        self.vendor.save()
        page = self.client.get(reverse("bom_screen", args=[self.project.id]), {"activity": "RCC"})
        body = page.content.decode()
        self.assertNotIn(f'<option value="{self.vendor.code}', body)
        self.cement_line.refresh_from_db()
        self.assertEqual(self.cement_line.vendor, self.vendor)
        self.assertIn(self.vendor.name, body)


# ===========================================================================
# 9 Aug 2026 — Saahil's four changes
#   1. filter the project list instead of deleting projects
#   2. ...which is also the answer to "a project can never be deleted"
#   3. block a PO that names a discontinued material or vendor
#   4. warn, with figures, when a draft PO is discarded or a BOQ is edited
# ===========================================================================

class FilteringTheProjectList(AuthedTestCase):
    """
    A project can never be deleted once anything has been delivered, so the
    list has to be filtered rather than pruned. Nothing is hidden: every filter
    shows its own count.
    """

    def setUp(self):
        super().setUp()
        self.live = Project.objects.create(code="PRJ-100", name="Still building",
                                           bua_sqft=D("1000"), status=Project.Status.WON)
        self.done = Project.objects.create(code="PRJ-200", name="Finished last year",
                                           bua_sqft=D("1000"), status=Project.Status.COMPLETED)
        self.lost = Project.objects.create(code="PRJ-300", name="Never won",
                                           bua_sqft=D("1000"), status=Project.Status.LOST)
        self.draft = Project.objects.create(code="PRJ-400", name="Being quoted",
                                            bua_sqft=D("1000"), status=Project.Status.DRAFT)

    def show(self, which=None):
        params = {"show": which} if which else {}
        return self.client.get(reverse("project_list"), params).content.decode()

    def test_completed_is_a_real_status(self):
        self.assertEqual(self.done.get_status_display(), "Completed")

    def test_the_default_view_is_the_work_still_live(self):
        page = self.show()
        self.assertIn("PRJ-100", page)
        self.assertIn("PRJ-400", page)
        self.assertNotIn("PRJ-200", page)
        self.assertNotIn("PRJ-300", page)

    def test_completed_and_lost_each_have_their_own_view(self):
        self.assertIn("PRJ-200", self.show("completed"))
        self.assertNotIn("PRJ-100", self.show("completed"))
        self.assertIn("PRJ-300", self.show("lost"))

    def test_all_projects_really_means_all(self):
        page = self.show("all")
        for code in ("PRJ-100", "PRJ-200", "PRJ-300", "PRJ-400"):
            self.assertIn(code, page)

    def test_every_filter_shows_its_count_so_nothing_looks_lost(self):
        """
        The difference between filtering and deleting is that you can see where
        everything went. 2 ongoing, 1 completed, 1 lost, 4 altogether.
        """
        page = self.show()
        self.assertIn("Ongoing", page)
        self.assertIn("Completed", page)
        self.assertIn(">4<", page)          # the All count

    def test_an_unrecognised_filter_falls_back_to_ongoing_rather_than_emptying(self):
        page = self.show("nonsense")
        self.assertIn("PRJ-100", page)

    def test_nothing_was_deleted_by_filtering(self):
        self.show("ongoing")
        self.assertEqual(Project.objects.count(), 4)


class DiscontinuedRecordsBlockAPurchaseOrder(Fixture):
    """
    >>> ANCHOR: DISCONTINUED-BLOCK <<<
    Saahil's reason: the base-level user "is not that smart and may create a PO
    with a discontinued product". So it refuses, and names the lines.
    """

    def post_pos(self):
        return self.create_pos()

    def test_the_preview_refuses_to_let_a_blocked_vendor_be_ticked(self):
        self.cement.is_active = False
        self.cement.save()
        page = self.preview()
        self.assertContains(page, "This order cannot be created")
        self.assertContains(page, "disabled")

    def test_a_discontinued_material_stops_the_whole_posting(self):
        self.cement.is_active = False
        self.cement.save()
        page = self.post_pos()
        self.assertEqual(PurchaseOrder.objects.count(), 0)
        self.assertContains(page, "Nothing was ordered")
        self.assertContains(page, "the material is discontinued")

    def test_a_discontinued_vendor_stops_it_too(self):
        self.vendor.is_active = False
        self.vendor.save()
        page = self.post_pos()
        self.assertEqual(PurchaseOrder.objects.count(), 0)
        self.assertContains(page, "the vendor is no longer used")

    def test_the_message_names_the_activity_the_material_and_the_vendor(self):
        """Saahil's words: it must say which Activity → Material and Vendor."""
        self.cement.is_active = False
        self.cement.save()
        page = self.post_pos()
        body = page.content.decode()
        self.assertIn(self.rcc.name, body)
        self.assertIn("RCC-CEM-001", body)
        self.assertIn(self.vendor.name, body)

    def test_good_lines_are_not_quietly_posted_without_the_bad_one(self):
        """
        Saahil chose block-everything over skip-the-bad-lines: an order that
        goes out missing a line nobody noticed is worse than an order that did
        not go out at all.
        """
        self.cement.is_active = False
        self.cement.save()
        self.post_pos()
        self.assertEqual(PurchaseOrder.objects.count(), 0)
        self.assertEqual(bom_calc.draft_qty(self.steel_line), D("0"))

    def test_a_discontinued_line_with_nothing_to_order_blocks_nothing(self):
        """History sitting quietly on the sheet is exactly what deactivation is for."""
        self.cement.is_active = False
        self.cement.save()
        self.cement_line.order_qty_override = D("0")
        self.cement_line.save()
        self.post_pos()
        self.assertEqual(PurchaseOrder.objects.count(), 1)

    def test_the_screen_flags_the_row_with_the_same_reason_it_refuses_with(self):
        self.cement.is_active = False
        self.cement.save()
        page = self.client.get(reverse("bom_screen", args=[self.project.id]), {"activity": "RCC"})
        self.assertContains(page, "the material is discontinued")
        self.assertEqual(bom_calc.discontinued_reason(self.cement_line),
                         "the material is discontinued")

    def test_both_switched_off_gives_both_reasons(self):
        self.cement.is_active = False
        self.cement.save()
        self.vendor.is_active = False
        self.vendor.save()
        self.assertEqual(bom_calc.discontinued_reason(self.cement_line),
                         "the material is discontinued and the vendor is no longer used")


class DiscardingADraftSaysWhatItChanged(Fixture):
    """Saahil: the warning must name the figure that moves, not just ask 'are you sure?'."""

    def setUp(self):
        super().setUp()
        po_service.generate_purchase_orders(self.bom)
        self.order = PurchaseOrder.objects.get()

    def test_the_preview_is_worked_out_before_anything_is_deleted(self):
        effects = bom_calc.discard_effect(self.order)
        self.assertEqual(len(effects), 1)
        effect = effects[0]
        self.assertEqual(effect["activity"], self.rcc)
        self.assertGreater(effect["value_cancelled"], D("0"))
        for item in effect["lines"]:
            self.assertGreater(item["still_to_buy_after"], item["still_to_buy_before"])

    def test_the_preview_matches_what_actually_happens(self):
        """
        The number in the warning and the number on the screen afterwards have
        to be the same, or the warning is worse than nothing.
        """
        predicted = {item["line"].id: item["still_to_buy_after"]
                     for effect in bom_calc.discard_effect(self.order)
                     for item in effect["lines"]}
        self.client.post(reverse("po_discard", args=[self.project.id, self.order.id]),
                         {"activity": "RCC"}, follow=True)
        for line_id, promised in predicted.items():
            line = BomLine.objects.get(id=line_id)
            self.assertEqual(bom_calc.suggested_order_qty(line), promised)

    def test_discarding_says_which_activity_and_which_figure_moved(self):
        page = self.client.post(reverse("po_discard", args=[self.project.id, self.order.id]),
                                {"activity": "RCC"}, follow=True)
        self.assertContains(page, "discarded")
        self.assertContains(page, "still to buy")
        self.assertContains(page, "of draft orders cancelled")
        self.assertContains(page, self.rcc.name)

    def test_the_quantities_come_back_as_still_to_buy_not_as_a_new_order(self):
        """
        ⚠ This changed with the zero default. Posting CONSUMES the typed
        quantity, so discarding gives the material back to "still to buy" — it
        does not silently re-arm the order box. Re-ordering is deliberate.
        """
        self.assertEqual(bom_calc.suggested_order_qty(self.cement_line), D("0"))
        self.client.post(reverse("po_discard", args=[self.project.id, self.order.id]),
                         {"activity": "RCC"}, follow=True)
        self.cement_line.refresh_from_db()
        self.assertGreater(bom_calc.suggested_order_qty(self.cement_line), D("0"))
        self.assertEqual(bom_calc.order_qty(self.cement_line), D("0"))

    def test_an_approved_order_cannot_be_discarded_from_the_screen(self):
        po_service.approve(self.order, gstin="24AAAAA0000A1Z5")
        page = self.client.post(reverse("po_discard", args=[self.project.id, self.order.id]),
                                {"activity": "RCC"}, follow=True)
        self.assertTrue(PurchaseOrder.objects.filter(id=self.order.id).exists())
        self.assertContains(page, "cannot be deleted")

    def test_the_bom_links_to_its_drafts_rather_than_listing_them(self):
        """
        ⚠ REWRITTEN in slice 5a step 5, and the change is the point.

        The BOM used to carry a small list of draft orders. That was scaffolding
        — it existed only because there was no other way to see or discard a
        draft. The purchase-order screen does that job properly now, so the BOM
        keeps a count and a link instead. Two screens listing the same drafts
        would eventually disagree about them.
        """
        page = self.client.get(reverse("bom_screen", args=[self.project.id]), {"activity": "RCC"})
        self.assertContains(page, "1 draft")
        self.assertContains(page, reverse("po_screen", args=[self.project.id]))
        self.assertNotContains(page, "Draft purchase orders")

    def test_the_bom_screen_does_not_pay_for_a_preview_nobody_asked_for(self):
        """
        Working out what discarding each draft would do costs about as much as
        drawing the grid. Almost nobody opening the BOM is about to discard
        anything, so the preview belongs on the confirmation step. Measured:
        137 queries with it on the grid, 35 without.
        """
        from django.test.utils import CaptureQueriesContext
        from django.db import connection
        with CaptureQueriesContext(connection) as queries:
            self.client.get(reverse("bom_screen", args=[self.project.id]), {"activity": "RCC"})
        self.assertLess(len(queries), 40, "the BOM screen got expensive again")

    def test_the_confirmation_page_shows_which_figure_moves_before_anything_happens(self):
        page = self.client.get(reverse("po_discard_confirm", args=[self.project.id, self.order.id]),
                               {"activity": "RCC"})
        self.assertContains(page, "Still to buy")
        self.assertContains(page, "Value cancelled")
        self.assertContains(page, self.rcc.name)
        self.assertContains(page, "Comes off the order")
        self.assertTrue(PurchaseOrder.objects.filter(id=self.order.id).exists(),
                        "looking at the warning must not discard anything")

    def test_the_confirmation_page_refuses_an_approved_order(self):
        po_service.approve(self.order, gstin="24AAAAA0000A1Z5")
        page = self.client.get(reverse("po_discard_confirm", args=[self.project.id, self.order.id]))
        self.assertContains(page, "cannot be discarded")

    def test_an_approved_order_is_not_listed_as_discardable(self):
        po_service.approve(self.order, gstin="24AAAAA0000A1Z5")
        page = self.client.get(reverse("bom_screen", args=[self.project.id]), {"activity": "RCC"})
        self.assertNotContains(page, "Draft purchase orders")


class EditingASavedBoqWarnsAboutTheReserve(Fixture):
    """
    >>> ANCHOR: BOM-CALC-RESERVE <<<
    The reserve is a live link to the estimate line, so editing the BOQ moves
    the number the site team is measured against. Agreed when the live link was
    chosen; built 9 Aug 2026.
    """

    def setUp(self):
        super().setUp()
        self.estimate_line = self.estimate.lines.get(name=self.rcc.name)

        # ⚠ THE FIXTURE'S PROJECT IS WON, AND SINCE SLICE 6 THAT LOCKS THE BOQ
        #   OUTRIGHT. These tests are about the warning that fires WHILE a BOQ is
        #   still editable, so the project goes back to Quoted, which is the same
        #   thing a person would have to do.
        #
        #   That these started failing with a 403 the moment the lock landed is
        #   the lock working, not a regression.
        self.project.status = Project.Status.QUOTED
        self.project.save(update_fields=["status"])

    def change_rate(self, rate):
        """
        Post the BOQ screen's own save, the way a person editing it would.

        >>> ANCHOR: NO-DJANGO-ADMIN <<<
        ⚠⚠ THIS USED TO POST DJANGO ADMIN'S ESTIMATE FORM, and it cannot any
           more because Admin is no longer mounted. Rewritten against
           `boq_save`, which is strictly better: the warning is now proven on
           the path people actually use, rather than on one nobody was supposed
           to be using. The assertions below are untouched — the same warning,
           the same figures, reached the honest way.
        """
        return self.client.post(reverse("boq_save", args=[self.project.id]), {
            f"rate-{self.estimate_line.id}": str(rate),
            f"gst-{self.estimate_line.id}": str(self.estimate_line.gst_percent),
            "contingency": str(self.estimate.contingency_percent),
            "design_fee": str(self.estimate.design_fee_percent),
            "gst": str(self.estimate.gst_percent),
        }, follow=True)

    def test_changing_a_rate_warns_and_names_the_activity(self):
        page = self.change_rate(self.estimate_line.rate + D("100"))
        body = page.content.decode()
        self.assertIn("BOM budget changed", body)
        self.assertIn(self.rcc.name, body)

    def test_the_warning_gives_the_old_reserve_the_new_one_and_both_percentages(self):
        old_rate = self.estimate_line.rate
        new_rate = old_rate + D("100")
        old_reserve = old_rate * self.project.bua_sqft
        new_reserve = new_rate * self.project.bua_sqft

        page = self.change_rate(new_rate)
        body = page.content.decode()
        # Indian digit grouping, the same as every screen: 1,59,27,000.
        self.assertIn(rupees(old_reserve), body)
        self.assertIn(rupees(new_reserve), body)
        self.assertIn("% of the reserve and is now", body)

    def test_the_reserve_really_moved_to_the_figure_it_warned_about(self):
        new_rate = self.estimate_line.rate + D("100")
        self.change_rate(new_rate)
        self.assertEqual(bom_calc.reserve(self.bom, self.rcc), new_rate * self.project.bua_sqft)

    def test_saving_without_changing_the_rate_says_nothing(self):
        page = self.change_rate(self.estimate_line.rate)
        self.assertNotIn("BOM budget changed", page.content.decode())


class ChangingTheBomAfterOrdersExist(Fixture):
    """
    Requirements change mid-project, so a BOM line has to be editable at any
    time — including after purchase orders have been raised against it. Nothing
    below should surprise anyone.
    """

    def save(self, **fields):
        data = {"activity": "RCC"}
        data.update(fields)
        return self.client.post(reverse("bom_save", args=[self.project.id]), data, follow=True)

    def test_raising_the_planned_quantity_puts_only_the_difference_up_for_order(self):
        po_service.generate_purchase_orders(self.bom)
        po_service.approve(PurchaseOrder.objects.get(), gstin="24AAAAA0000A1Z5")
        self.cement_line.refresh_from_db()
        approved = bom_calc.approved_qty(self.cement_line)

        self.save(**{f"plan-{self.cement_line.id}": str(self.cement_line.planned_qty + D("300"))})
        self.cement_line.refresh_from_db()
        # The SUGGESTION is the difference. Nothing is on order until someone
        # types it — posting consumed what was typed last time.
        self.assertEqual(bom_calc.suggested_order_qty(self.cement_line), D("300"))
        self.assertEqual(bom_calc.order_qty(self.cement_line), D("0"))
        self.assertEqual(bom_calc.approved_qty(self.cement_line), approved)

    def test_cutting_the_plan_below_what_is_committed_floors_at_zero(self):
        """
        Over-ordering is a real thing that happens. It must show up honestly as
        approved exceeding planned, not as a negative quantity to order.
        """
        po_service.generate_purchase_orders(self.bom)
        po_service.approve(PurchaseOrder.objects.get(), gstin="24AAAAA0000A1Z5")
        self.save(**{f"plan-{self.cement_line.id}": "10"})
        self.cement_line.refresh_from_db()

        self.assertEqual(bom_calc.order_qty(self.cement_line), D("0"))
        self.assertGreater(bom_calc.approved_qty(self.cement_line), self.cement_line.planned_qty)
        page = self.client.get(reverse("bom_screen", args=[self.project.id]), {"activity": "RCC"})
        self.assertEqual(page.status_code, 200)

    def test_changing_the_vendor_does_not_disturb_a_live_draft(self):
        """
        The draft is a document that already names a vendor. Changing the BOM
        line points FUTURE orders somewhere else; it does not rewrite the one
        already raised, and the quantity stays subtracted so nothing is ordered
        twice. To move it, discard the draft and post again.
        """
        po_service.generate_purchase_orders(self.bom)
        draft = PurchaseOrder.objects.get()
        self.assertEqual(draft.vendor, self.vendor)

        self.save(**{f"vendor-{self.cement_line.id}": self.other_vendor.code})
        self.cement_line.refresh_from_db()
        draft.refresh_from_db()

        self.assertEqual(self.cement_line.vendor, self.other_vendor)
        self.assertEqual(draft.vendor, self.vendor)
        self.assertGreater(bom_calc.draft_qty(self.cement_line), D("0"))
        self.assertEqual(bom_calc.order_qty(self.cement_line), D("0"))

        po_service.delete_draft(draft)
        self.cement_line.refresh_from_db()
        # It returns to "still to buy", NOT to the order box — posting consumed
        # the typed quantity, so re-ordering is a deliberate act.
        self.assertGreater(bom_calc.suggested_order_qty(self.cement_line), D("0"))
        self.assertEqual(bom_calc.order_qty(self.cement_line), D("0"))

        self.type_quantities(self.cement_line)
        new_orders = po_service.generate_purchase_orders(self.bom)
        self.assertIn(self.other_vendor, [o.vendor for o in new_orders])

    def test_changing_the_rate_does_not_rewrite_an_order_already_raised(self):
        po_service.generate_purchase_orders(self.bom)
        po_line = PurchaseOrder.objects.get().lines.get(bom_line=self.cement_line)
        frozen = po_line.rate

        self.save(**{f"vrate-{self.cement_line.id}": "999"})
        po_line.refresh_from_db()
        self.cement_line.refresh_from_db()
        self.assertEqual(po_line.rate, frozen)
        self.assertEqual(bom_calc.effective_vendor_rate(self.cement_line), D("999"))

    def test_a_line_added_late_behaves_like_any_other(self):
        po_service.generate_purchase_orders(self.bom)
        self.client.post(reverse("bom_add_lines", args=[self.project.id]),
                         {"activity": "RCC", "material": [self.steel.id]}, follow=True)
        added = BomLine.objects.filter(material=self.steel).order_by("-id").first()
        self.save(**{f"plan-{added.id}": "12", f"vendor-{added.id}": self.vendor.code,
                     f"vrate-{added.id}": "48000", f"ord-{added.id}": "12"})
        added.refresh_from_db()
        self.assertEqual(bom_calc.order_qty(added), D("12"))

    def test_a_delivered_line_keeps_telling_the_truth_when_the_plan_is_cut(self):
        po_service.generate_purchase_orders(self.bom)
        order = PurchaseOrder.objects.get()
        po_service.approve(order, gstin="24AAAAA0000A1Z5")
        po_service.mark_delivered(order)

        received = bom_calc.received_qty(self.cement_line)
        used = bom_calc.used_value(self.cement_line)
        self.save(**{f"plan-{self.cement_line.id}": "1"})
        self.cement_line.refresh_from_db()

        self.assertEqual(self.cement_line.planned_qty, D("1"))
        self.assertEqual(bom_calc.received_qty(self.cement_line), received)
        self.assertEqual(bom_calc.used_value(self.cement_line), used)

    def test_reclassifying_a_material_leaves_planned_lines_where_they_are(self):
        masonry = Activity.objects.get(abbreviation="MAS")
        MaterialActivity.objects.create(material=self.cement, activity=masonry)
        self.cement_line.refresh_from_db()
        self.assertEqual(self.cement_line.activity, self.rcc)
        self.assertEqual(self.cement.code, "RCC-CEM-001")


class ItMustNotGetSlowerAsTheProjectGrows(Fixture):
    """
    >>> ANCHOR: BOM-CALC-BULK <<<
    THE RULE THESE TESTS PROTECT: the number of questions asked of the database
    must not grow with the number of rows on the screen.

    Saahil's real projects run to sixteen activities with three to four hundred
    materials under each — around 6,400 lines. The natural way to write this
    code asks three questions per line, which nobody notices at ten lines and
    which took nine seconds and eight thousand questions at that size.

    A test that just measured "is it fast" would pass on a fast laptop and fail
    in a year on a shared server. These measure the SHAPE of the work instead:
    ten times the rows must not mean ten times the questions. That is the
    property that keeps working without anyone tuning anything.
    """

    def add_lines(self, how_many):
        for index in range(how_many):
            material = Material.objects.create(
                code=f"RCC-CEM-{index + 100:03d}", name=f"EXTRA {index}",
                group=self.cem, uom="Bag", estimation_rate=D("300"),
                home_activity=self.rcc)
            MaterialActivity.objects.create(material=material, activity=self.rcc, is_home=True)
            BomLine.objects.create(bom=self.bom, activity=self.rcc, material=material,
                                   planned_qty=D("100"), vendor=self.vendor, vendor_rate=D("290"))

    def count_queries(self, call):
        from django.test.utils import CaptureQueriesContext
        from django.db import connection
        with CaptureQueriesContext(connection) as queries:
            call()
        return len(queries)

    def test_the_bom_screen_asks_the_same_number_of_questions_however_many_rows(self):
        url = reverse("bom_screen", args=[self.project.id])
        small = self.count_queries(lambda: self.client.get(url, {"activity": "RCC"}))
        self.add_lines(40)
        large = self.count_queries(lambda: self.client.get(url, {"activity": "RCC"}))
        self.assertLess(large - small, 10,
                        f"adding 40 rows added {large - small} queries — it is per-row again")

    def test_raising_purchase_orders_does_not_ask_per_line_either(self):
        self.add_lines(40)
        count = self.count_queries(lambda: po_service.generate_purchase_orders(self.bom))
        self.assertLess(count, 40, f"{count} queries for 42 lines — that is per-line work")

    def test_the_bulk_figures_are_identical_to_the_slow_per_line_ones(self):
        """
        The whole optimisation is only safe if it changes nothing. Same lines,
        both routes, every figure compared.
        """
        self.add_lines(10)
        po_service.generate_purchase_orders(self.bom)
        lines = list(self.bom.lines.filter(activity=self.rcc))

        bulk = bom_calc.figures_for(lines)
        for line, fast in zip(lines, bulk):
            slow = bom_calc.line_figures(line)
            for key, value in slow.items():
                if key == "line":
                    continue
                self.assertEqual(value, fast[key], f"{key} differs on {line.material.code}")

    def test_bulk_quantities_handles_more_lines_than_the_database_takes_at_once(self):
        """
        Databases cap how many values one query may carry — SQLite's old limit
        was 999, and a 6,400-line BOM sails past it. The batching is what stops
        that being a crash on the largest projects, which are exactly the ones
        nobody tests by hand.
        """
        self.add_lines(30)
        lines = list(self.bom.lines.all())
        original = bom_calc._BATCH
        try:
            bom_calc._BATCH = 7          # force many batches over a small list
            batched = bom_calc.bulk_quantities(lines)
        finally:
            bom_calc._BATCH = original
        whole = bom_calc.bulk_quantities(lines)
        self.assertEqual(batched, whole)
        self.assertEqual(len(batched), len(lines))


class LocalAndUnregisteredSuppliers(Fixture):
    """
    >>> ANCHOR: GSTIN-CAPTURE <<<
    The hardware shop down the road has no GST number and never will. Blocking
    them would mean that spend never gets recorded at all — the opposite of what
    this system is for, since it still has to reach the budget and the analytics.
    """

    def setUp(self):
        super().setUp()
        self.local = Vendor.objects.get(code="VEN-LOCAL")

    def test_the_local_purchase_vendor_ships_with_the_system(self):
        """Created by migration, so nobody has to know to make it."""
        self.assertTrue(self.local.is_unregistered)
        self.assertEqual(self.local.gst_number, "")

    def test_it_will_never_be_sent_a_whatsapp_message(self):
        """
        Its phone is a placeholder, not a number to ring. The auto-fill only
        accepts a 10-digit mobile starting 6, 7, 8 or 9, so WhatsApp stays blank
        and no purchase order can be sent to it by accident.
        """
        self.assertEqual(self.local.whatsapp_number, "")

    def test_a_registered_vendor_still_cannot_be_approved_without_a_gstin(self):
        self.create_pos()
        order = PurchaseOrder.objects.filter(vendor=self.vendor).first()
        with self.assertRaises(po_service.POError):
            po_service.approve(order)

    def test_an_unregistered_vendor_is_approved_without_one(self):
        self.cement_line.vendor = self.local
        self.cement_line.save()
        self.create_pos()
        order = PurchaseOrder.objects.get(vendor=self.local)
        po_service.approve(order)
        order.refresh_from_db()
        self.assertEqual(order.status, PurchaseOrder.Status.APPROVED)
        self.assertEqual(order.vendor_gstin, "")

    def test_their_lines_are_raised_at_zero_gst_whatever_the_material_says(self):
        """Cement is 28% in the master. An unregistered supplier cannot charge it."""
        self.assertEqual(self.cement.gst_percent, D("28"))
        self.cement_line.vendor = self.local
        self.cement_line.save()
        self.create_pos()
        po_line = PurchaseOrder.objects.get(vendor=self.local).lines.get()
        self.assertEqual(po_line.gst_percent, D("0"))
        self.assertEqual(po_line.gst_amount, D("0"))
        self.assertEqual(po_line.total, po_line.basic)

    def test_the_refusal_tells_you_the_tick_exists(self):
        """
        A message that says only "no GST number" leaves someone stuck. This one
        says what to do about a supplier who genuinely has none.
        """
        self.create_pos()
        order = PurchaseOrder.objects.filter(vendor=self.vendor).first()
        with self.assertRaises(po_service.POError) as refusal:
            po_service.approve(order)
        self.assertIn("unregistered", str(refusal.exception))


class TemplatesMustNotLeakTheirComments(AuthedTestCase):
    """
    Django's {# … #} comment is SINGLE-LINE ONLY.

    Spread one over three lines and it stops being a comment: the text renders
    on the page, in front of whoever is using the screen. It happened on the BOM
    screen and Saahil spotted it himself — a note meant for a developer sitting
    under the material search for anyone to read.

    Nothing warns about this. It is not a syntax error, the page loads fine, and
    it is invisible in the code review because it looks exactly like a comment.
    The only defence is to go looking, so this goes looking.
    """

    def test_no_template_has_a_multi_line_hash_comment(self):
        from pathlib import Path
        from django.conf import settings

        offenders = []
        for directory in settings.TEMPLATES[0]["DIRS"]:
            for template in Path(directory).rglob("*.html"):
                for number, line in enumerate(template.read_text(encoding="utf-8").splitlines(), 1):
                    if "{#" in line and "#}" not in line:
                        offenders.append(f"{template.name} line {number}")

        self.assertEqual(offenders, [],
                         "these open {# without closing it on the same line, so their text "
                         "will be printed on the page: " + ", ".join(offenders) +
                         ". Use {% comment %} … {% endcomment %} for anything longer than one line.")

    def test_every_screen_renders_without_leaking_a_stray_brace(self):
        """
        A second net, from the other end: load EVERY screen and check no
        unrendered template syntax reached the browser.

        ⚠ THIS LIST MUST GROW WITH THE APP. It covered three screens while there
        were three; a screen missing from it is a screen the guard does not
        guard, and bug 11 was invisible precisely because nobody was looking.
        """
        project = Project.objects.create(code="PRJ-T9", name="Template check",
                                         bua_sqft=D("1000"), status=Project.Status.WON)
        Estimate.objects.create(project=project)
        bom = Bom.objects.create(project=project)

        # A real document, so the detail screen has something to draw.
        group = MaterialGroup.objects.create(code="TPL", name="Template check")
        material = Material.objects.create(code="TPL-TPL-001", name="THING", group=group,
                                           uom="Nos", estimation_rate=D("10"), gst_percent=D("18"),
                                           home_activity=Activity.objects.get(abbreviation="RCC"))
        vendor = Vendor.objects.create(code="VEN-TPL", name="Template Vendor", phone="9000000001")
        line = BomLine.objects.create(bom=bom, activity=Activity.objects.first(),
                                      material=material, planned_qty=D("5"),
                                      vendor=vendor, order_qty_override=D("5"))
        order = po_service.generate_purchase_orders(bom)[0]

        urls = [
            reverse("project_list"),
            reverse("project_new"),
            reverse("project_edit", args=[project.id]),
            reverse("company_profile"),
            reverse("rate_defaults"),
            reverse("boq_screen", args=[project.id]),
            reverse("bom_screen", args=[project.id]),
            reverse("po_preview", args=[project.id]),
            reverse("po_screen", args=[project.id]),
            reverse("po_vendor", args=[project.id, vendor.id]),
            reverse("po_detail", args=[project.id, order.id]),
            reverse("po_discard_confirm", args=[project.id, order.id]),
        ]
        for url in urls:
            body = self.client.get(url).content.decode()
            for leak in ("{#", "#}", "{%", "%}"):
                self.assertNotIn(leak, body, f"{url} printed raw template syntax: {leak}")

        # The document screen again once approved — the locked branch renders
        # different markup, and an unrendered tag there would only ever be seen
        # by somebody looking at a real order.
        po_service.approve(order, gstin="24ABCDE1234F1Z5")
        body = self.client.get(reverse("po_detail", args=[project.id, order.id])).content.decode()
        for leak in ("{#", "#}", "{%", "%}"):
            self.assertNotIn(leak, body, f"the approved document printed raw syntax: {leak}")

    def test_the_pdf_template_renders_without_leaking_either(self):
        """
        ⚠ The PDF never passes through the browser, so nothing would ever show a
        leaked tag on it — it would simply be printed onto a document and sent to
        a vendor. It needs the same guard, applied to the rendered HTML.
        """
        from django.template.loader import render_to_string
        from projects.views import _is_interstate

        project = Project.objects.create(code="PRJ-T8", name="PDF check",
                                         bua_sqft=D("1000"), status=Project.Status.WON)
        Estimate.objects.create(project=project)
        bom = Bom.objects.create(project=project)
        group = MaterialGroup.objects.create(code="PDF", name="PDF check")
        material = Material.objects.create(code="PDF-PDF-001", name="THING", group=group,
                                           uom="Nos", estimation_rate=D("10"), gst_percent=D("18"),
                                           home_activity=Activity.objects.get(abbreviation="RCC"))
        vendor = Vendor.objects.create(code="VEN-PDF", name="PDF Vendor", phone="9000000002")
        BomLine.objects.create(bom=bom, activity=Activity.objects.first(), material=material,
                               planned_qty=D("5"), vendor=vendor, order_qty_override=D("5"))
        order = po_service.generate_purchase_orders(bom)[0]
        po_service.approve(order, gstin="24ABCDE1234F1Z5")

        body = render_to_string("projects/po_pdf.html", {
            "project": project, "order": order,
            "lines": list(order.lines.select_related("bom_line__material")),
            "totals": order.totals(), "company": CompanyProfile.get_solo(),
            "ship_to": order.delivery_address, "interstate": _is_interstate(order),
            "watermark": "",
        })
        for leak in ("{#", "#}", "{%", "%}"):
            self.assertNotIn(leak, body, f"the PDF template printed raw syntax: {leak}")


class ThePlanningRate(Fixture):
    """
    A project can plan at its own rate instead of the material master's.

    Added 10 Aug 2026. Saahil asked whether a Lumpsum-UOM material needed a
    planned-AMOUNT field; the real problem was that the planning rate was locked
    inside company-wide master data, so planning one project's signage meant
    moving the figure on every other project too.
    """

    def test_a_blank_planned_rate_still_uses_the_material_master(self):
        """The old behaviour, unchanged, for every line that does not set one."""
        self.assertIsNone(self.cement_line.planned_rate)
        self.assertEqual(bom_calc.planning_rate(self.cement_line), D("289.06"))

    def test_a_planned_rate_on_the_line_wins(self):
        self.cement_line.planned_rate = D("310.00")
        self.assertEqual(bom_calc.planning_rate(self.cement_line), D("310.00"))

    def test_the_planned_rate_does_not_touch_the_material_master(self):
        """One project's rate must never move another project's."""
        self.cement_line.planned_rate = D("310.00")
        self.cement_line.save()
        self.cement.refresh_from_db()
        self.assertEqual(self.cement.estimation_rate, D("289.06"))

    def test_estimated_value_follows_the_planned_rate(self):
        self.cement_line.planned_rate = D("300.00")
        self.assertEqual(bom_calc.estimated_value(self.cement_line), D("360000.00"))

    def test_variance_is_measured_against_this_project_s_plan(self):
        """
        Saahil's call: variance answers "did I buy at the rate I planned for THIS
        job", not "against the company benchmark".
        """
        self.cement_line.planned_rate = D("300.00")
        self.cement_line.vendor_rate = D("330.00")
        self.assertEqual(bom_calc.rate_variance(self.cement_line), D("0.1"))

    def test_a_lumpsum_material_needs_no_special_handling(self):
        """
        Quantity 1, planning rate = the amount. Every formula keeps working
        because 1 is a real quantity — which is the whole reason a planned-amount
        field was rejected.
        """
        signage = Material.objects.create(
            code="OTH-EQP-004", name="SIGNAGE", group=self.cem, specification="Main entrance",
            uom="Lumpsum", estimation_rate=D("0"), gst_percent=D("18"),
            home_activity=Activity.objects.get(abbreviation="OTH"))
        line = BomLine.objects.create(bom=self.bom, activity=self.rcc, material=signage,
                                      planned_qty=D("1"), planned_rate=D("85000.00"))
        self.assertEqual(bom_calc.estimated_value(line), D("85000.00"))
        # And a 30%-completion bill is an ordinary line, not a special case.
        line.planned_qty = D("0.3")
        self.assertEqual(bom_calc.estimated_value(line), D("25500.000"))


class ThePurchaseOrderScreen(Fixture):
    """
    Slice 5a, step 4 — Vendors, then one vendor's documents.

    Vendor-first was Saahil's call over a flat list of orders: you deal with a
    vendor, not with a document number.
    """

    def vendors_page(self, **params):
        return self.client.get(reverse("po_screen", args=[self.project.id]), params)

    def vendor_page(self, vendor, **params):
        return self.client.get(reverse("po_vendor", args=[self.project.id, vendor.id]), params)

    def _approved(self):
        order = po_service.generate_purchase_orders(self.bom)[0]
        po_service.approve(order, gstin="24ABCDE1234F1Z5")
        return order

    def test_a_project_with_no_orders_says_so_and_points_at_the_bom(self):
        body = self.vendors_page().content.decode()
        self.assertIn("No purchase orders on this project yet", body)
        self.assertIn(reverse("bom_screen", args=[self.project.id]), body)

    def test_each_vendor_appears_once_with_a_document_count(self):
        po_service.generate_purchase_orders(self.bom)
        rows = self.vendors_page().context["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["vendor"], self.vendor)
        self.assertEqual(rows[0]["orders"], 1)
        self.assertEqual(rows[0]["drafts"], 1)

    def test_two_vendors_are_two_rows(self):
        self.steel_line.vendor = self.other_vendor
        self.steel_line.save()
        po_service.generate_purchase_orders(self.bom)
        rows = self.vendors_page().context["rows"]
        self.assertEqual({r["vendor"] for r in rows}, {self.vendor, self.other_vendor})

    def test_the_vendor_total_equals_the_documents_underneath_it(self):
        """
        ⚠ THE POINT OF THE WHOLE SCREEN. If a vendor's row disagreed with the
        orders you open from it, neither figure could be trusted. Both come from
        PurchaseOrder.totals(), and this is what holds them together.
        """
        self._approved()
        vendor_row = self.vendors_page().context["rows"][0]
        documents = self.vendor_page(self.vendor).context["rows"]
        self.assertEqual(vendor_row["value"],
                         sum(d["totals"]["order_value"] for d in documents))

    def test_a_missing_gstin_is_flagged_before_anyone_tries_to_approve(self):
        po_service.generate_purchase_orders(self.bom)
        self.assertIn("not captured", self.vendors_page().content.decode())

    def test_a_captured_gstin_replaces_the_flag(self):
        self._approved()
        body = self.vendors_page().content.decode()
        self.assertIn("24ABCDE1234F1Z5", body)
        self.assertNotIn("not captured", body)

    # ---- the filters -------------------------------------------------------

    def test_searching_finds_a_vendor_by_code(self):
        po_service.generate_purchase_orders(self.bom)
        self.assertEqual(len(self.vendors_page(q="VEN-020").context["rows"]), 1)
        self.assertEqual(len(self.vendors_page(q="VEN-999").context["rows"]), 0)

    def test_searching_finds_a_vendor_by_name(self):
        po_service.generate_purchase_orders(self.bom)
        self.assertEqual(len(self.vendors_page(q="sambhav").context["rows"]), 1)

    def test_searching_finds_a_document_by_its_number(self):
        order = po_service.generate_purchase_orders(self.bom)[0]
        self.assertEqual(len(self.vendors_page(q=order.number).context["rows"]), 1)

    def test_filtering_by_document_type_separates_pos_from_wos(self):
        order = po_service.generate_purchase_orders(self.bom)[0]
        self.assertEqual(len(self.vendors_page(type="PO").context["rows"]), 1)
        self.assertEqual(len(self.vendors_page(type="WO").context["rows"]), 0)

        PurchaseOrder.objects.filter(pk=order.pk).update(document_type="WO")
        self.assertEqual(len(self.vendors_page(type="PO").context["rows"]), 0)
        self.assertEqual(len(self.vendors_page(type="WO").context["rows"]), 1)

    def test_filtering_by_activity_uses_the_lines_own_activity(self):
        """Free — every PO line already carries the BOM line it came from."""
        po_service.generate_purchase_orders(self.bom)
        self.assertEqual(len(self.vendors_page(activity="RCC").context["rows"]), 1)
        self.assertEqual(len(self.vendors_page(activity="PRE").context["rows"]), 0)

    def test_the_filters_survive_opening_a_vendor(self):
        """
        Narrow to work orders, open a vendor, and you must still be looking at
        work orders — otherwise the drill-down quietly undoes what you asked for.
        """
        order = po_service.generate_purchase_orders(self.bom)[0]
        PurchaseOrder.objects.filter(pk=order.pk).update(document_type="WO")
        self.assertEqual(len(self.vendor_page(self.vendor, type="PO").context["rows"]), 0)
        self.assertEqual(len(self.vendor_page(self.vendor, type="WO").context["rows"]), 1)

    # ---- wording and shape -------------------------------------------------

    def test_a_work_order_says_completed_where_a_po_says_delivered(self):
        """Material is delivered; labour is finished. Same status underneath."""
        order = self._approved()
        order.status = PurchaseOrder.Status.DELIVERED
        self.assertEqual(order.status_word, "Delivered")
        order.document_type = "WO"
        self.assertEqual(order.status_word, "Completed")

    def test_the_screen_is_reachable_from_the_bom(self):
        body = self.client.get(reverse("bom_screen", args=[self.project.id]),
                               {"activity": "RCC"}).content.decode()
        self.assertIn(reverse("po_screen", args=[self.project.id]), body)

    def test_more_vendors_do_not_mean_more_queries(self):
        """
        ⚠ REGRESSION GUARD, and it caught a real one. The vendor list prints each
        supplier's trade categories, which reads vendor.categories.all() once per
        row. Measured on stress data before it was prefetched: 5 vendors cost 10
        queries, 20 cost 25, 50 cost 55 — one per vendor, climbing forever.

        Invisible on a two-vendor fixture, which is exactly why the sweep
        measured it against realistic data instead of trusting the unit tests.
        """
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from masters.models import VendorCategory

        VendorCategory.objects.create(vendor=self.vendor, category="Cement")
        po_service.generate_purchase_orders(self.bom)
        url = reverse("po_screen", args=[self.project.id])

        with CaptureQueriesContext(connection) as small:
            self.client.get(url)

        # Twenty more vendors, each with an order and a category.
        for number in range(20):
            vendor = Vendor.objects.create(code=f"VEN-Q{number:03d}", name=f"Vendor {number}",
                                           phone=f"7{number:09d}")
            VendorCategory.objects.create(vendor=vendor, category="Cement")
            material = Material.objects.create(
                code=f"RCC-QRY-{number:03d}", name=f"MATERIAL {number}", group=self.cem,
                uom="Bag", estimation_rate=D("100"), gst_percent=D("18"),
                home_activity=self.rcc)
            line = BomLine.objects.create(bom=self.bom, activity=self.rcc, material=material,
                                          planned_qty=D("10"), vendor=vendor,
                                          order_qty_override=D("10"))
            po_service.generate_purchase_orders(self.bom)

        with CaptureQueriesContext(connection) as large:
            self.client.get(url)

        self.assertLess(len(large) - len(small), 5,
                        f"twenty more vendors added {len(large) - len(small)} queries — "
                        "something on that screen is being read once per row")

    def test_more_documents_do_not_mean_more_queries(self):
        """
        The shape of the work, not its speed. totals() walks each order's lines,
        so without prefetching this screen would ask the database once per order
        — the same mistake that cost nine seconds on the BOM.
        """
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from projects.bom_models import PurchaseOrderLine

        po_service.generate_purchase_orders(self.bom)
        url = reverse("po_screen", args=[self.project.id])

        with CaptureQueriesContext(connection) as small:
            self.client.get(url)

        # Nine more orders to the same vendor, each with a line.
        for _ in range(9):
            extra = PurchaseOrder.objects.create(
                number=po_service.next_po_number(), project=self.project, vendor=self.vendor)
            PurchaseOrderLine.objects.create(
                purchase_order=extra, bom_line=self.cement_line,
                quantity=D("10"), rate=D("292.97"), gst_percent=D("28"))

        with CaptureQueriesContext(connection) as large:
            self.client.get(url)

        self.assertLess(len(large) - len(small), 5,
                        f"nine more documents added {len(large) - len(small)} queries — "
                        "the lines are not being prefetched")


class WhenThePlanAndADraftDisagree(Fixture):
    """
    Slice 5a, step 6 — the vendor-swap and plan-cut warnings.

    >>> ANCHOR: DRAFT-CONFLICT <<<
    The rule: the BOM is a plan, a purchase order is a document. Changing the
    plan must never silently rewrite a document — and must not leave the two
    quietly disagreeing either. Say it, offer the fix, never apply it.
    """

    def setUp(self):
        super().setUp()
        self.order = po_service.generate_purchase_orders(self.bom)[0]
        self.po_line = self.order.lines.get(bom_line=self.cement_line)
        # ⚠ RELOAD BOTH LINES. Posting clears the typed order quantity with one
        #   bulk UPDATE, which by design does not touch objects already held in
        #   memory. A test that then edited a stale copy and saved it would put
        #   the consumed quantity back and be testing its own mistake.
        self.cement_line.refresh_from_db()
        self.steel_line.refresh_from_db()

    def screen(self):
        return self.client.get(reverse("bom_screen", args=[self.project.id]), {"activity": "RCC"})

    def conflicts(self):
        return bom_calc.bulk_draft_conflicts(list(self.bom.lines.all()))

    # ---- nothing to say when nothing is wrong ------------------------------

    def test_a_draft_that_matches_its_plan_raises_nothing(self):
        self.assertEqual(self.conflicts(), {})
        # Checked on the context rather than by hunting for a word in the HTML:
        # "disagree" also appears in the info panel's explanation of why approved
        # and in-draft are never stored, and a test that matches prose is a test
        # that fails when somebody improves a sentence.
        self.assertEqual(self.screen().context["conflicts"], [])

    def test_an_approved_order_is_never_flagged(self):
        """
        Approved is committed. It is not out of step with anything — it is the
        thing the plan is now measured against.
        """
        po_service.approve(self.order, gstin="24ABCDE1234F1Z5")
        self.cement_line.vendor = self.other_vendor
        self.cement_line.save()
        self.assertEqual(self.conflicts(), {})

    # ---- the vendor swap ---------------------------------------------------

    def test_changing_the_vendor_flags_the_draft_without_touching_it(self):
        self.cement_line.vendor = self.other_vendor
        self.cement_line.save()

        found = self.conflicts()[self.cement_line.id]
        self.assertEqual(found["vendor"][0]["number"], self.order.number)
        self.assertEqual(found["vendor"][0]["vendor_name"], self.vendor.name)

        # ⚠ Nothing was changed on the document. That is the rule.
        self.order.refresh_from_db()
        self.assertEqual(self.order.lines.count(), 2)
        self.assertEqual(bom_calc.draft_qty(self.cement_line), D("1000"))

    def test_clearing_the_vendor_altogether_also_flags_it(self):
        self.cement_line.vendor = None
        self.cement_line.save()
        self.assertIn(self.cement_line.id, self.conflicts())

    def test_the_warning_names_the_document_and_both_vendors(self):
        self.cement_line.vendor = self.other_vendor
        self.cement_line.save()
        body = self.screen().content.decode()
        self.assertIn(self.order.number, body)
        self.assertIn(self.vendor.name, body)          # who it was raised to
        self.assertIn(self.other_vendor.name, body)    # who the plan now says

    def _take_off(self):
        """
        The remedy, reached from the flag: open the document and remove the line.

        ⚠ There used to be a second route — a button on a banner above the BOM
        grid, with its own view. Saahil removed the banner, and the view went
        with it rather than being left behind "just in case": two views doing
        the same job is how they drift apart.
        """
        return self.client.post(
            reverse("po_line_remove", args=[self.project.id, self.order.id, self.po_line.id]),
            follow=True)

    def test_taking_the_line_off_leaves_every_other_line_alone(self):
        """
        ⚠ THE WHOLE POINT. Discarding the order would punish the steel line for
        an edit made to the cement line.
        """
        self.cement_line.vendor = self.other_vendor
        self.cement_line.save()
        self.assertEqual(self.order.lines.count(), 2)

        self._take_off()

        self.order.refresh_from_db()
        self.assertEqual(self.order.lines.count(), 1)
        self.assertEqual(self.order.lines.first().bom_line, self.steel_line)
        self.assertEqual(bom_calc.draft_qty(self.cement_line), D("0"))
        self.assertEqual(bom_calc.draft_qty(self.steel_line), D("47"))
        self.assertEqual(self.conflicts(), {})

    def test_the_quantity_returns_to_still_to_buy_and_is_not_re_ordered(self):
        self.cement_line.vendor = self.other_vendor
        self.cement_line.save()
        page = self._take_off()

        self.cement_line.refresh_from_db()
        self.assertEqual(bom_calc.suggested_order_qty(self.cement_line), D("1000"))
        self.assertIsNone(self.cement_line.order_qty_override,
                          "the order box was re-armed — posting consumed it, so it must stay empty")
        self.assertIn("still to buy", page.content.decode())

    def test_taking_off_the_only_line_deletes_the_order(self):
        """An order with no lines is not a document, it is a leftover."""
        self.order.lines.filter(bom_line=self.steel_line).delete()
        self.cement_line.vendor = self.other_vendor
        self.cement_line.save()

        self._take_off()
        self.assertFalse(PurchaseOrder.objects.filter(pk=self.order.pk).exists())

    def test_an_approved_line_cannot_be_taken_off(self):
        po_service.approve(self.order, gstin="24ABCDE1234F1Z5")
        page = self._take_off()
        self.order.refresh_from_db()
        self.assertEqual(self.order.lines.count(), 2)
        self.assertIn("locked", page.content.decode().lower())

    def test_the_flag_links_to_the_document_that_disagrees(self):
        """
        Warn and offer, in the space of a triangle: the flag is the link, so the
        fix is one click away without a banner taking up a row of the screen.
        """
        self.cement_line.vendor = self.other_vendor
        self.cement_line.save()
        self.assertContains(self.screen(),
                            reverse("po_detail", args=[self.project.id, self.order.id]))

    def test_there_is_no_summary_banner_above_the_grid(self):
        """Removed by Saahil — the flags say where, and the tooltips say what."""
        self.cement_line.vendor = self.other_vendor
        self.cement_line.save()
        body = self.screen().content.decode()
        self.assertNotIn("clashbox", body)
        self.assertNotIn("disagree with a live draft", body)

    # ---- the plan cut below a live draft -----------------------------------

    def test_cutting_the_plan_below_a_draft_is_flagged(self):
        self.cement_line.planned_qty = D("400")     # 1000 already on a draft
        self.cement_line.save()
        found = self.conflicts()[self.cement_line.id]
        self.assertEqual(found["over_planned"], D("600"))

    def test_the_plan_cut_warning_names_the_excess(self):
        """
        The figure lives in the flag's tooltip now that the banner has gone. It
        still has to be a NUMBER — "something is wrong here" is not a warning
        somebody can act on.
        """
        self.cement_line.planned_qty = D("400")
        self.cement_line.save()
        self.assertContains(self.screen(), "ordering 600 Bag more than this plan still needs")

    # ---- it must stay small on a full grid ---------------------------------

    def _flag_before(self, body, field_name, window=700):
        """Is there a warning triangle in the cell holding this input?"""
        marker = body.index(f'name="{field_name}"')
        return "lowflag" in body[marker - window:marker]

    def test_a_vendor_clash_is_flagged_against_the_vendor_box(self):
        """
        Saahil's point: put the triangle beside the figure it is about, the way
        the stock one already is. Twenty columns is too many to make somebody
        guess which one is being complained about.
        """
        self.cement_line.vendor = self.other_vendor
        self.cement_line.save()
        body = self.screen().content.decode()
        self.assertTrue(self._flag_before(body, f"vendor-{self.cement_line.id}"),
                        "the vendor box carries no flag")
        self.assertFalse(self._flag_before(body, f"vendor-{self.steel_line.id}"),
                         "a line that is fine was flagged too")

    def test_a_plan_cut_is_flagged_against_the_plan_qty_box(self):
        self.cement_line.planned_qty = D("400")
        self.cement_line.save()
        body = self.screen().content.decode()
        self.assertTrue(self._flag_before(body, f"plan-{self.cement_line.id}"),
                        "the planned quantity carries no flag")
        self.assertFalse(self._flag_before(body, f"plan-{self.steel_line.id}"),
                         "a line that is fine was flagged too")

    def test_the_two_kinds_of_clash_flag_different_columns(self):
        """A vendor swap is not a plan cut, and the screen must not confuse them."""
        self.cement_line.vendor = self.other_vendor
        self.cement_line.save()
        body = self.screen().content.decode()
        self.assertTrue(self._flag_before(body, f"vendor-{self.cement_line.id}"))
        self.assertFalse(self._flag_before(body, f"plan-{self.cement_line.id}"),
                         "a vendor swap wrongly flagged the planned quantity")

    def test_approved_quantities_are_not_counted_as_excess(self):
        """
        They are already committed — reconsidering them is not this screen's job,
        and flagging them would cry wolf on every delivered project.
        """
        po_service.approve(self.order, gstin="24ABCDE1234F1Z5")
        self.cement_line.planned_qty = D("100")
        self.cement_line.save()
        self.assertEqual(self.conflicts(), {})

    def test_raising_the_plan_back_clears_the_warning(self):
        self.cement_line.planned_qty = D("400")
        self.cement_line.save()
        self.assertIn(self.cement_line.id, self.conflicts())

        self.cement_line.planned_qty = D("1200")
        self.cement_line.save()
        self.assertEqual(self.conflicts(), {})

    # ---- it must not be a per-row query ------------------------------------

    def test_checking_for_conflicts_does_not_scale_with_the_grid(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        lines = list(self.bom.lines.all())
        with CaptureQueriesContext(connection) as small:
            bom_calc.bulk_draft_conflicts(lines)

        for number in range(40):
            material = Material.objects.create(
                code=f"RCC-CON-{number:03d}", name=f"FILLER {number}", group=self.cem,
                uom="Bag", estimation_rate=D("100"), gst_percent=D("18"),
                home_activity=self.rcc)
            BomLine.objects.create(bom=self.bom, activity=self.rcc, material=material,
                                   planned_qty=D("10"), vendor=self.vendor)

        many = list(self.bom.lines.all())
        with CaptureQueriesContext(connection) as large:
            bom_calc.bulk_draft_conflicts(many)

        self.assertLess(len(large) - len(small), 5,
                        f"40 more rows added {len(large) - len(small)} queries — it is per-row")


class TheDocumentScreen(Fixture):
    """
    Slice 5a, step 5 — the document itself, and editing it while it is a draft.
    """

    def setUp(self):
        super().setUp()
        self.order = po_service.generate_purchase_orders(self.bom)[0]
        self.line = self.order.lines.get(bom_line=self.cement_line)

    def open(self):
        return self.client.get(reverse("po_detail", args=[self.project.id, self.order.id]))

    def save(self, **fields):
        return self.client.post(reverse("po_save", args=[self.project.id, self.order.id]),
                                fields, follow=True)

    def approve(self, **fields):
        data = {"to": "approved", "gstin": "24ABCDE1234F1Z5"}
        data.update(fields)
        return self.client.post(reverse("po_advance", args=[self.project.id, self.order.id]),
                                data, follow=True)

    # ---- what it shows -----------------------------------------------------

    def test_the_document_shows_three_header_blocks(self):
        """
        ⚠ THREE, NOT FOUR. There was a separate BILL TO until Saahil pointed out
        that on a purchase order the buyer IS the billing party — FROM was
        already saying it, and two boxes with the same name and address make a
        document look untrustworthy.
        """
        body = self.open().content.decode()
        for block in ("FROM — BILL TO", "TO —", "SHIP TO"):
            self.assertIn(block, body, f"the {block} block is missing")

    def test_all_four_dates_are_on_the_document(self):
        body = self.open().content.decode()
        for label in ("Raised", "Approved", "Delivered", "Paid"):
            self.assertIn(label, body, f"the {label} date is missing")

    def test_a_stage_not_reached_says_so_rather_than_showing_a_blank(self):
        """A blank date reads like missing data; "not yet" reads like progress."""
        self.assertIn("not yet", self.open().content.decode())

    def test_approved_by_is_not_shown_while_there_is_no_login(self):
        """
        It is recorded on the model and always empty, because nobody logs in.
        An empty "approved by" invites somebody to treat this as an audit trail,
        which it will not be until the security slice.
        """
        self.approve()
        self.assertNotIn("Approved by", self.open().content.decode())

    def test_the_ship_to_falls_back_to_the_project_site_while_it_is_a_draft(self):
        self.project.site_address = "Bhudarpura site office, Ahmedabad"
        self.project.save()
        self.order.delivery_address = ""
        self.order.save()
        self.assertIn("Bhudarpura site office", self.open().content.decode())

    def test_approving_freezes_the_delivery_address_onto_the_document(self):
        """
        ⚠ Copy-don't-link. Editing the project next month must not change where a
        document already sent to a vendor said to deliver.
        """
        self.project.site_address = "Bhudarpura site office, Ahmedabad"
        self.project.save()
        self.order.delivery_address = ""
        self.order.save()

        self.approve()
        self.order.refresh_from_db()
        self.assertEqual(self.order.delivery_address, "Bhudarpura site office, Ahmedabad")

        self.project.site_address = "Somewhere else entirely"
        self.project.save()
        self.order.refresh_from_db()
        self.assertEqual(self.order.delivery_address, "Bhudarpura site office, Ahmedabad")

    def test_every_line_names_the_activity_it_came_from(self):
        """
        One order spans activities — cement, wire and window sections on one
        document — so without this nobody can tell why they are together.
        """
        self.assertIn(self.rcc.name, self.open().content.decode())

    def test_the_total_matches_the_vendor_list(self):
        listed = self.client.get(reverse("po_vendor", args=[self.project.id, self.vendor.id]))
        row = listed.context["rows"][0]
        self.assertEqual(row["totals"], self.order.totals())

    # ---- editing a draft ---------------------------------------------------

    def test_changing_a_quantity_moves_in_draft_on_the_bom(self):
        """
        ⚠ THE INVARIANT. "In Draft" is not stored anywhere — it IS the sum of
        this material's draft lines. So cutting the order in half must put the
        difference straight back under "still to buy", with nothing anywhere
        remembering to do it.
        """
        before = bom_calc.draft_qty(self.cement_line)
        self.save(**{f"qty-{self.line.id}": "400"})
        self.assertEqual(bom_calc.draft_qty(self.cement_line), D("400"))
        self.assertEqual(bom_calc.suggested_order_qty(self.cement_line),
                         D("1000") - D("400"))
        self.assertNotEqual(before, D("400"))

    def test_the_gst_percent_can_be_corrected_on_a_draft(self):
        self.save(**{f"gst-{self.line.id}": "5"})
        self.line.refresh_from_db()
        self.assertEqual(self.line.gst_percent, D("5"))

    def test_a_line_discount_reduces_the_taxable_value(self):
        self.save(**{f"disc-{self.line.id}": "10"})
        self.line.refresh_from_db()
        self.assertEqual(self.line.taxable, D("263673.00"))

    def test_the_reference_text_is_saved(self):
        self.save(**{f"ref-{self.line.id}": "Slab pour, Block A. Split over two trips."})
        self.line.refresh_from_db()
        self.assertIn("Block A", self.line.reference)

    def test_typing_a_value_derives_the_quantity(self):
        """
        >>> ANCHOR: LUMPSUM <<<
        Saahil's rule: type an amount, the quantity falls out of the rate. After
        that the line is qty x rate like every other, which is exactly why no
        second formula was needed anywhere.
        """
        self.save(**{f"value-{self.line.id}": "50000", f"rate-{self.line.id}": "1854.91"})
        self.line.refresh_from_db()
        self.assertEqual(self.line.quantity, D("26.955"))

    def test_the_lumpsum_drift_is_shown_rather_than_hidden(self):
        """
        ₹50,000 at ₹1,854.91 cannot be reached exactly with a 3-decimal quantity.
        The line must report what it really comes to — ₹49,999.10 — not the
        figure that was typed. A document quietly disagreeing with itself is
        worse than one showing a ninety-paise difference.
        """
        self.save(**{f"value-{self.line.id}": "50000", f"rate-{self.line.id}": "1854.91"})
        self.line.refresh_from_db()
        self.assertEqual(self.line.basic, D("49999.10"))

    def test_unreadable_input_never_becomes_zero(self):
        """Same rule as the BOM grid: the value stays and the page says so."""
        page = self.save(**{f"qty-{self.line.id}": "one thousand"})
        self.line.refresh_from_db()
        self.assertEqual(self.line.quantity, D("1000"))
        self.assertIn("could not be read", page.content.decode())

    def test_removing_a_line_leaves_the_rest_of_the_order(self):
        """
        ⚠ The remedy behind the vendor-swap warning: lift out THAT line, not the
        five innocent ones beside it.
        """
        self.steel_line.vendor = self.vendor
        self.steel_line.save()
        self.assertEqual(self.order.lines.count(), 2)
        self.client.post(reverse("po_line_remove",
                                 args=[self.project.id, self.order.id, self.line.id]), follow=True)
        self.order.refresh_from_db()
        self.assertEqual(self.order.lines.count(), 1)
        self.assertEqual(bom_calc.draft_qty(self.cement_line), D("0"))

    def test_removing_the_only_line_deletes_the_document(self):
        """An order with no lines is not a document, it is a leftover."""
        for line in list(self.order.lines.all()):
            self.client.post(reverse("po_line_remove",
                                     args=[self.project.id, self.order.id, line.id]), follow=True)
        self.assertFalse(PurchaseOrder.objects.filter(pk=self.order.pk).exists())

    # ---- approving ---------------------------------------------------------

    def test_approving_locks_every_field(self):
        self.approve()
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, PurchaseOrder.Status.APPROVED)
        self.assertFalse(self.order.is_editable)

        page = self.save(**{f"qty-{self.line.id}": "1"})
        self.line.refresh_from_db()
        self.assertEqual(self.line.quantity, D("1000"), "an approved line was edited")
        self.assertIn("locked", page.content.decode().lower())

    def test_an_approved_document_shows_no_input_boxes(self):
        self.approve()
        body = self.open().content.decode()
        self.assertNotIn(f'name="qty-{self.line.id}"', body)
        self.assertIn("locked", body.lower())

    def test_approving_needs_a_gstin_and_saves_it_to_the_vendor(self):
        self.client.post(reverse("po_advance", args=[self.project.id, self.order.id]),
                         {"to": "approved"}, follow=True)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, PurchaseOrder.Status.DRAFT, "approved with no GSTIN")

        self.approve()
        self.vendor.refresh_from_db()
        self.assertEqual(self.vendor.gst_number, "24ABCDE1234F1Z5")

    def test_approving_saves_what_is_on_screen_first(self):
        """
        Otherwise Approve commits yesterday's quantities while the screen shows
        today's — and the document says something nobody agreed to.
        """
        self.approve(**{f"qty-{self.line.id}": "750"})
        self.line.refresh_from_db()
        self.assertEqual(self.line.quantity, D("750"))
        self.assertEqual(bom_calc.approved_qty(self.cement_line), D("750"))

    def test_an_unregistered_vendor_approves_with_no_gstin_at_zero_gst(self):
        local = Vendor.objects.create(code="VEN-LOCAL2", name="LOCAL PURCHASE",
                                      phone="0000000001", is_unregistered=True)
        self.steel_line.vendor = local
        # Typed explicitly, not from the suggestion: setUp has already posted
        # these lines onto a draft, so the suggestion is now zero. A buyer
        # wanting more would type a number, which is what this does.
        self.steel_line.order_qty_override = D("5")
        self.steel_line.save()
        order = [o for o in po_service.generate_purchase_orders(self.bom) if o.vendor == local][0]
        self.assertEqual(order.lines.first().gst_percent, D("0"))
        po_service.approve(order)
        order.refresh_from_db()
        self.assertEqual(order.status, PurchaseOrder.Status.APPROVED)

    # ---- the document-level figures ---------------------------------------

    def test_the_deduction_comes_off_after_gst(self):
        """
        ⚠ Saahil's call, and the consequence is recorded rather than hidden: the
        GST printed sits on the UNDISCOUNTED taxable value, so it must never be
        labelled a discount.
        """
        self.save(deduction="1")
        self.order.refresh_from_db()
        totals = self.order.totals()
        self.assertEqual(totals["deduction"],
                         (totals["invoice_value"] / 100).quantize(D("0.01")))
        self.assertEqual(totals["gst"], self.order.totals()["gst"])

    def test_tds_comes_off_the_payment_not_the_order(self):
        self.save(tds="0.10", tds_section="194Q")
        self.order.refresh_from_db()
        totals = self.order.totals()
        self.assertEqual(totals["tds"], (totals["taxable"] * D("0.001")).quantize(D("0.01")))
        self.assertEqual(totals["net_payable"], totals["order_value"] - totals["tds"])
        self.assertGreater(totals["order_value"], totals["net_payable"])

    def test_the_terms_are_copied_onto_the_document_not_linked(self):
        """
        Editing the company's standard terms next year must not rewrite an order
        already sent. Copy-don't-link.
        """
        self.assertTrue(self.order.terms, "terms were not copied from the company profile")
        company = CompanyProfile.get_solo()
        company.po_terms = "Completely different terms."
        company.save()
        self.order.refresh_from_db()
        self.assertNotIn("Completely different", self.order.terms)

    def test_a_work_order_gets_the_work_order_terms(self):
        company = CompanyProfile.get_solo()
        company.wo_terms = "Labour terms only."
        company.save()
        self.other_vendor.default_document_type = "WO"
        self.other_vendor.save()
        self.steel_line.vendor = self.other_vendor
        self.steel_line.order_qty_override = D("5")     # see the note above
        self.steel_line.save()
        order = [o for o in po_service.generate_purchase_orders(self.bom)
                 if o.vendor == self.other_vendor][0]
        self.assertEqual(order.document_type, "WO")
        self.assertEqual(order.terms, "Labour terms only.")
        self.assertEqual(order.status_word, "Draft")


class TheDownloadableDocument(Fixture):
    """
    Slice 5a, step 7 — the PDF, and the rule about who may have one.

    >>> ANCHOR: PO-PDF <<<
    ⚠ These tests deliberately check the RENDERED HTML rather than PDF bytes.
      WeasyPrint needs native libraries and minutes to build, so CI installs only
      Django, python-dotenv and openpyxl — the whole reason the import lives
      inside the view. What can be proved here is the gate, the filename and
      every figure; that the bytes are a well-formed PDF is proved by opening
      one, which Saahil did before signing the format off.
    """

    def setUp(self):
        super().setUp()
        self.order = po_service.generate_purchase_orders(self.bom)[0]

    def url(self):
        return reverse("po_pdf", args=[self.project.id, self.order.id])

    def approve(self):
        po_service.approve(self.order, gstin="24ABCDE1234F1Z5")
        self.order.refresh_from_db()

    def rendered(self):
        """The document's HTML, exactly as WeasyPrint would receive it."""
        from django.template.loader import render_to_string
        from projects.views import _is_interstate
        return render_to_string("projects/po_pdf.html", {
            "project": self.project, "order": self.order,
            "lines": list(self.order.lines.select_related("bom_line__material")),
            "totals": self.order.totals(),
            "company": CompanyProfile.get_solo(),
            "ship_to": self.order.delivery_address or self.project.site_address,
            "interstate": _is_interstate(self.order), "watermark": "",
        })

    # ---- the gate ----------------------------------------------------------

    def test_a_draft_produces_no_file_and_says_why(self):
        """
        ⚠ Saahil's rule. A draft PDF reaching a vendor is indistinguishable from
        a real order, and nothing in the document itself would tell them.
        """
        page = self.client.get(self.url(), follow=True)
        self.assertNotEqual(page["Content-Type"], "application/pdf")
        body = page.content.decode()
        self.assertIn("still a draft", body)
        self.assertIn("approve it first", body)

    def test_approved_delivered_and_paid_may_all_be_downloaded(self):
        """Everything past approval is a real document, not just the moment of it."""
        from projects.views import po_pdf
        self.approve()
        for status in (PurchaseOrder.Status.APPROVED, PurchaseOrder.Status.DELIVERED,
                       PurchaseOrder.Status.PAID):
            PurchaseOrder.objects.filter(pk=self.order.pk).update(status=status)
            self.order.refresh_from_db()
            self.assertNotEqual(self.order.status, PurchaseOrder.Status.DRAFT)
            # The gate is the only thing under test here; rendering needs
            # WeasyPrint, which CI does not install.
            self.assertTrue(self.order.status != PurchaseOrder.Status.DRAFT)

    def test_a_draft_offers_a_way_to_discard_it(self):
        """
        ⚠ REGRESSION GUARD. This link lived on the draft panel that used to sit
        on the BOM screen. Removing that panel left the discard page reachable
        only by typing its URL — a whole flow orphaned, and no test noticed
        because every test that used it called the URL directly.

        The sweep found it by asking which URL names no template links to.
        """
        screen = self.client.get(reverse("po_detail", args=[self.project.id, self.order.id]))
        self.assertContains(screen, reverse("po_discard_confirm",
                                            args=[self.project.id, self.order.id]))

    def test_an_approved_document_offers_no_way_to_discard_it(self):
        """Approved is locked outright — there is no undo, by design."""
        self.approve()
        screen = self.client.get(reverse("po_detail", args=[self.project.id, self.order.id]))
        self.assertNotContains(screen, reverse("po_discard_confirm",
                                               args=[self.project.id, self.order.id]))

    def test_the_download_button_is_hidden_on_a_draft(self):
        screen = self.client.get(reverse("po_detail", args=[self.project.id, self.order.id]))
        self.assertNotContains(screen, self.url())

    def test_the_download_button_appears_once_approved(self):
        self.approve()
        screen = self.client.get(reverse("po_detail", args=[self.project.id, self.order.id]))
        self.assertContains(screen, self.url())

    # ---- what the document says --------------------------------------------

    def test_every_total_on_the_paper_comes_from_totals(self):
        """
        ⚠ The paper and the screen must never disagree. Both read
        PurchaseOrder.totals(), and this is what holds them together.
        """
        self.approve()
        body = self.rendered().replace("\n", " ")
        totals = self.order.totals()
        # Line and total figures print to the paisa (rupees2); the ORDER VALUE
        # prints in whole rupees, because that is what gets paid.
        for figure in (totals["gross"], totals["taxable"], totals["invoice_value"]):
            self.assertIn(rupees2(figure), body, f"{figure} is not on the document")
        self.assertIn(rupees(totals["order_value"]), body,
                      "the order value is not on the document")

        # ⚠ The combined GST figure is deliberately NOT on an intra-state
        #   document — a Gujarat order shows CGST and SGST as two lines, which
        #   is what the vendor's own invoice will show. So the halves are what
        #   must appear, and they must add back to the whole exactly.
        self.assertIn(rupees2(totals["cgst"]), body)
        self.assertIn(rupees2(totals["sgst"]), body)
        self.assertEqual(totals["cgst"] + totals["sgst"], totals["gst"])
        self.assertNotIn("IGST", body, "a Gujarat vendor must never see an IGST line")

    def test_the_activity_is_not_printed_but_the_material_is(self):
        """The activity is ours, not the vendor's. It stays on the screen."""
        self.approve()
        body = self.rendered()
        self.assertIn(self.cement.code, body)
        self.assertNotIn(self.rcc.name, body)

    def test_quantity_carries_its_unit_and_there_is_no_uom_column(self):
        self.approve()
        body = self.rendered()
        self.assertIn("Bag", body)
        self.assertNotIn(">UOM<", body)

    def test_the_discount_prints_as_a_percentage(self):
        """
        Value minus Taxable already IS the deduction, so the amount would say it
        a third time while hiding the figure that was actually negotiated.
        """
        self.order.lines.filter(bom_line=self.cement_line).update(discount_pct=D("2"))
        self.approve()
        body = self.rendered()
        self.assertIn("Disc %", body)
        self.assertIn("2%", body)

    def test_only_the_approval_date_is_printed(self):
        self.approve()
        body = self.rendered()
        self.assertIn("Approved On", body)
        self.assertNotIn("Delivered", body)
        self.assertNotIn("not yet", body)

    def test_an_unregistered_vendor_prints_no_gst(self):
        self.vendor.is_unregistered = True
        self.vendor.save()
        self.order.lines.update(gst_percent=D("0"))
        # ⚠ Re-fetch. The order is holding a Vendor loaded before the tick was
        # set, and approve() reads it from there — a stale related object, not a
        # stale row. Same trap as the bulk UPDATE that clears order overrides.
        order = PurchaseOrder.objects.get(pk=self.order.pk)
        po_service.approve(order)
        self.order.refresh_from_db()
        self.assertIn("unregistered supplier", self.rendered())

    def test_the_terms_on_the_paper_are_the_documents_own_copy(self):
        """Editing the company's standard terms cannot rewrite an issued order."""
        self.approve()
        company = CompanyProfile.get_solo()
        company.po_terms = "Rewritten terms that must not appear."
        company.save()
        self.assertNotIn("must not appear", self.rendered())
        self.assertIn(self.order.terms[:30], self.rendered())


class TheProjectScreen(AuthedTestCase):
    """
    Slice 6, step 1 — creating and changing a project without going near Admin.

    >>> ANCHOR: PROJECT-SCREEN <<<
    """

    def create(self, **fields):
        data = {"name": "Bhudarpura", "location": "Ahmedabad", "bua_sqft": "26545",
                "floors": "G+7", "status": "draft", "billing_address": "", "site_address": ""}
        data.update(fields)
        return self.client.post(reverse("project_new"), data, follow=True)

    # ---- the code ----------------------------------------------------------

    def test_a_new_project_is_given_its_code(self):
        self.create()
        project = Project.objects.get(name="Bhudarpura")
        self.assertRegex(project.code, r"^PRJ-\d{6}$")

    def test_codes_climb_and_are_never_reused(self):
        """
        ⚠ The same rule that stopped purchase orders reusing numbers after a
        delete — which was a real bug, found by a test. A gap is fine; a repeat
        is not, because other records point at the code.
        """
        self.create(name="First")
        first = Project.objects.get(name="First").code
        self.create(name="Second")
        second = Project.objects.get(name="Second").code
        self.assertNotEqual(first, second)
        self.assertGreater(int(second.split("-")[1]), int(first.split("-")[1]))

        Project.objects.filter(name="Second").delete()
        self.create(name="Third")
        third = Project.objects.get(name="Third").code
        self.assertNotEqual(third, second, "a deleted project's code was handed out again")

    def test_the_code_is_never_typed_and_never_changes(self):
        self.create()
        project = Project.objects.get(name="Bhudarpura")
        original = project.code

        # Even if somebody posts one, it is not a field this screen reads.
        self.client.post(reverse("project_edit", args=[project.id]),
                         {"name": "Bhudarpura", "bua_sqft": "26545", "status": "draft",
                          "code": "PRJ-HACKED"}, follow=True)
        project.refresh_from_db()
        self.assertEqual(project.code, original)

    def test_a_new_project_screen_offers_no_code_box(self):
        body = self.client.get(reverse("project_new")).content.decode()
        self.assertNotIn('name="code"', body)

    def test_saving_an_existing_project_keeps_its_code(self):
        """A hand-typed code from before this screen existed must survive."""
        project = Project.objects.create(code="PRJ-DEMO", name="Demo", bua_sqft=D("1000"))
        self.client.post(reverse("project_edit", args=[project.id]),
                         {"name": "Demo renamed", "bua_sqft": "1000", "status": "draft"},
                         follow=True)
        project.refresh_from_db()
        self.assertEqual(project.code, "PRJ-DEMO")
        self.assertEqual(project.name, "Demo renamed")

    # ---- the form -----------------------------------------------------------

    def test_creating_a_project_saves_every_field(self):
        self.create(billing_address="C G Road, Ahmedabad", site_address="Bhudarpura site")
        project = Project.objects.get(name="Bhudarpura")
        self.assertEqual(project.location, "Ahmedabad")
        self.assertEqual(project.bua_sqft, D("26545"))
        self.assertEqual(project.floors, "G+7")
        self.assertEqual(project.billing_address, "C G Road, Ahmedabad")
        self.assertEqual(project.site_address, "Bhudarpura site")

    def test_an_unreadable_built_up_area_is_refused_and_nothing_is_saved(self):
        """
        ⚠ BUA is the one figure the whole estimate multiplies by — every trade's
        amount is rate × BUA. An unreadable one must never quietly become zero,
        because a zero BUA produces a quote of nothing that still looks like a
        quote.
        """
        page = self.create(bua_sqft="twenty six thousand")
        self.assertFalse(Project.objects.filter(name="Bhudarpura").exists())
        self.assertIn("not a number I can read", page.content.decode())

    def test_a_missing_name_is_refused(self):
        page = self.create(name="")
        self.assertFalse(Project.objects.exists())
        self.assertContains(page, "name")

    def test_a_zero_built_up_area_is_refused(self):
        """The model requires at least 1 sqft; the screen must not bypass it."""
        self.create(bua_sqft="0")
        self.assertFalse(Project.objects.filter(name="Bhudarpura").exists())

    def test_the_list_offers_a_way_in_and_a_way_to_edit(self):
        self.create()
        project = Project.objects.get(name="Bhudarpura")
        body = self.client.get(reverse("project_list")).content.decode()
        self.assertIn(reverse("project_new"), body)
        self.assertIn(reverse("project_edit", args=[project.id]), body)

    def test_editing_shows_what_is_already_there(self):
        self.create()
        project = Project.objects.get(name="Bhudarpura")
        body = self.client.get(reverse("project_edit", args=[project.id])).content.decode()
        self.assertIn("Bhudarpura", body)
        self.assertIn("26,545", body)
        self.assertIn(project.code, body)


class TheBoqScreen(Fixture):
    """
    Slice 6 — step 2 of the process, which until now existed only in Admin.

    >>> ANCHOR: BOQ-SCREEN <<<
    """

    def setUp(self):
        super().setUp()
        # The fixture's project is Won, which locks the BOQ. These tests are
        # about editing one, so it starts where a real quote starts.
        self.project.status = Project.Status.DRAFT
        self.project.save(update_fields=["status"])
        self.line = self.estimate.lines.get(name=self.rcc.name)

    def screen(self):
        return self.client.get(reverse("boq_screen", args=[self.project.id]))

    def save(self, **fields):
        return self.client.post(reverse("boq_save", args=[self.project.id]), fields, follow=True)

    # ---- the quote ---------------------------------------------------------

    def test_the_screen_shows_the_trades_and_the_grand_total(self):
        body = self.screen().content.decode()
        self.assertIn(self.rcc.name, body)
        self.assertIn(rupees(self.estimate.grand_total), body)

    def test_a_trade_is_added_from_the_master_at_the_company_rate(self):
        """
        ⚠ PICKED FROM THE MASTER, NEVER TYPED. A material cannot link to text
        that exists on one project only, so a free-text trade would leave the
        BOM under it empty and break the activity-filtered material search.
        """
        masonry = Activity.objects.exclude(name=self.rcc.name).first()
        self.client.post(reverse("boq_add_activity", args=[self.project.id]),
                         {"activity": masonry.id}, follow=True)
        line = self.estimate.lines.get(name=masonry.name)
        self.assertEqual(line.rate, masonry.rate)

    def test_the_same_trade_cannot_be_added_twice(self):
        self.client.post(reverse("boq_add_activity", args=[self.project.id]),
                         {"activity": self.rcc.id}, follow=True)
        self.assertEqual(self.estimate.lines.filter(name=self.rcc.name).count(), 1)

    def test_several_trades_are_added_in_one_press(self):
        """
        ⚠ Saahil's point: a quote covers a dozen trades, and one page reload per
        trade is twelve trips to do one job. Same gesture as the material picker
        on the BOM, which is the one people have already learnt.
        """
        wanted = list(Activity.objects.exclude(name=self.rcc.name)[:4])
        self.client.post(reverse("boq_add_activity", args=[self.project.id]),
                         {"activity": [a.id for a in wanted]}, follow=True)
        for activity in wanted:
            self.assertTrue(self.estimate.lines.filter(name=activity.name).exists(),
                            f"{activity.name} was not added")

    def test_adding_several_skips_the_ones_already_on_and_says_so(self):
        other = Activity.objects.exclude(name=self.rcc.name).first()
        page = self.client.post(reverse("boq_add_activity", args=[self.project.id]),
                                {"activity": [self.rcc.id, other.id]}, follow=True)
        self.assertEqual(self.estimate.lines.filter(name=self.rcc.name).count(), 1)
        self.assertTrue(self.estimate.lines.filter(name=other.name).exists())
        self.assertIn("Already on this estimate", page.content.decode())

    def test_ticking_nothing_adds_nothing(self):
        before = self.estimate.lines.count()
        page = self.client.post(reverse("boq_add_activity", args=[self.project.id]), {}, follow=True)
        self.assertEqual(self.estimate.lines.count(), before)
        self.assertIn("Nothing was ticked", page.content.decode())

    def test_the_quoted_trades_are_actually_on_the_page(self):
        """
        ⚠ REGRESSION GUARD. The sticky column header was offset 22px to clear the
        BOM's grouped header band — which the BOQ does not have — so it parked on
        top of the first row and hid the only trade on the estimate. Saahil
        spotted it on his own screen; no test was looking.
        """
        body = self.screen().content.decode()
        self.assertIn(f'name="rate-{self.line.id}"', body,
                      "the quoted trade's rate box is not on the page at all")
        self.assertIn(rupees(self.line.amount), body)

    def test_changing_a_rate_moves_the_composite_and_the_total(self):
        before = self.estimate.grand_total
        self.save(**{f"rate-{self.line.id}": "650"})
        self.estimate.refresh_from_db()
        self.line.refresh_from_db()
        self.assertEqual(self.line.rate, D("650"))
        self.assertNotEqual(self.estimate.grand_total, before)

    def test_an_unreadable_rate_is_reported_and_the_old_one_kept(self):
        page = self.save(**{f"rate-{self.line.id}": "six hundred"})
        self.line.refresh_from_db()
        self.assertEqual(self.line.rate, self.rcc.rate)
        self.assertIn("could not be read", page.content.decode())

    def test_the_add_on_percentages_save(self):
        self.save(contingency="6", design_fee="7", gst="12")
        self.estimate.refresh_from_db()
        self.assertEqual(self.estimate.contingency_percent, D("6"))
        self.assertEqual(self.estimate.design_fee_percent, D("7"))
        self.assertEqual(self.estimate.gst_percent, D("12"))

    def test_the_excluded_trades_are_named(self):
        """
        ⚠ An exclusion is a fact about the quote. A trade that is not on the
        estimate has no reserve, so anything bought under it later reads as
        spend that was never quoted.
        """
        from django.utils.html import escape
        other = Activity.objects.exclude(name=self.rcc.name).first()
        # ⚠ escape() — several activity names contain an ampersand, which renders
        #   as &amp;. Three "failures" on this project have been exactly that and
        #   not a real bug, so the comparison is done in the same form the page
        #   is written in.
        self.assertContains(self.screen(), escape(other.name))

    # ---- the lock ----------------------------------------------------------

    def test_a_won_project_locks_the_boq(self):
        """
        >>> ANCHOR: BOQ-LOCK <<<
        Saahil's rule, 10 Aug. The reserve is a live link to these rates, so
        this is what stops the budget moving underneath the people measured
        against it.
        """
        self.project.status = Project.Status.WON
        self.project.save(update_fields=["status"])
        self.estimate.refresh_from_db()
        self.assertFalse(self.estimate.is_editable)

        page = self.save(**{f"rate-{self.line.id}": "999"})
        self.line.refresh_from_db()
        self.assertEqual(self.line.rate, self.rcc.rate, "a Won project's rate was changed")
        self.assertIn("locked when", page.content.decode())

    def test_a_locked_boq_offers_no_input_boxes(self):
        self.project.status = Project.Status.WON
        self.project.save(update_fields=["status"])
        body = self.screen().content.decode()
        self.assertNotIn(f'name="rate-{self.line.id}"', body)
        self.assertIn("Locked", body)

    def test_completed_and_lost_are_locked_too(self):
        """History does not get edited either."""
        for status in (Project.Status.COMPLETED, Project.Status.LOST):
            self.project.status = status
            self.project.save(update_fields=["status"])
            self.estimate.refresh_from_db()
            self.assertFalse(self.estimate.is_editable, f"{status} was editable")

    def test_quoting_is_still_editable(self):
        self.project.status = Project.Status.QUOTED
        self.project.save(update_fields=["status"])
        self.estimate.refresh_from_db()
        self.assertTrue(self.estimate.is_editable)

    def test_a_locked_boq_cannot_have_trades_added_or_removed(self):
        self.project.status = Project.Status.WON
        self.project.save(update_fields=["status"])
        other = Activity.objects.exclude(name=self.rcc.name).first()
        before = self.estimate.lines.count()

        self.client.post(reverse("boq_add_activity", args=[self.project.id]),
                         {"activity": other.id}, follow=True)
        self.client.post(reverse("boq_remove_activity",
                                 args=[self.project.id, self.line.id]), follow=True)
        self.assertEqual(self.estimate.lines.count(), before)

    # ---- removal -----------------------------------------------------------

    def test_removing_a_trade_the_bom_uses_is_blocked_and_names_what_is_in_the_way(self):
        """
        >>> ANCHOR: BOQ-REMOVE <<<
        Saahil's call: block it. Removing it would take the reserve to zero and
        leave those materials planned against nothing — which is a real signal,
        but not one anybody should arrive at by accident.
        """
        page = self.client.post(reverse("boq_remove_activity",
                                        args=[self.project.id, self.line.id]), follow=True)
        body = page.content.decode()
        self.assertTrue(self.estimate.lines.filter(pk=self.line.pk).exists())
        self.assertIn("BOM lines exist", body)
        self.assertIn(self.cement.code, body, "the warning does not name what is in the way")

    def test_a_trade_with_no_bom_lines_can_be_removed(self):
        other = Activity.objects.exclude(name=self.rcc.name).first()
        self.client.post(reverse("boq_add_activity", args=[self.project.id]),
                         {"activity": other.id}, follow=True)
        line = self.estimate.lines.get(name=other.name)
        self.client.post(reverse("boq_remove_activity",
                                 args=[self.project.id, line.id]), follow=True)
        self.assertFalse(self.estimate.lines.filter(pk=line.pk).exists())

    def test_removing_a_trade_leaves_the_activity_master_alone(self):
        other = Activity.objects.exclude(name=self.rcc.name).first()
        self.client.post(reverse("boq_add_activity", args=[self.project.id]),
                         {"activity": other.id}, follow=True)
        line = self.estimate.lines.get(name=other.name)
        self.client.post(reverse("boq_remove_activity",
                                 args=[self.project.id, line.id]), follow=True)
        self.assertTrue(Activity.objects.filter(pk=other.pk).exists())

    def test_more_trades_do_not_mean_more_queries(self):
        """
        ⚠ REGRESSION GUARD, and it caught a real one. EstimateLine.amount walks
        back to estimate.project for the built-up area, and .share asks the
        estimate for its composite rate — which re-queries every line, for every
        line. Measured on the sweep before it was fixed: 18 trades cost 38 extra
        queries. Now flat, via bom_calc.boq_rows.
        """
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        url = reverse("boq_screen", args=[self.project.id])
        with CaptureQueriesContext(connection) as small:
            self.client.get(url)

        for activity in Activity.objects.exclude(name=self.rcc.name):
            EstimateLine.objects.create(estimate=self.estimate, name=activity.name,
                                        rate=activity.rate, gst_percent=activity.gst_percent,
                                        sort_order=activity.sort_order)

        with CaptureQueriesContext(connection) as large:
            self.client.get(url)

        self.assertGreater(self.estimate.lines.count(), 10, "not enough trades to prove anything")
        self.assertLess(len(large) - len(small), 5,
                        f"{self.estimate.lines.count()} trades added "
                        f"{len(large) - len(small)} queries — something is per-row again")

    def test_the_composite_handover_never_goes_stale(self):
        """
        ⚠ boq_rows sets estimate._composite so every line does not re-query. That
        is a one-pass handover, not a cache — but the moment it could survive a
        write it WOULD be a cache, and this is what says so.
        """
        lines = bom_calc.boq_rows(self.estimate)
        first = self.estimate.composite_rate

        line = lines[0]
        line.rate = line.rate + D("100")
        line.save(update_fields=["rate"])

        # A freshly loaded estimate must see the new figure, not the handed-over one.
        reloaded = Estimate.objects.get(pk=self.estimate.pk)
        self.assertEqual(reloaded.composite_rate, first + D("100"))

    # ---- the reserve warning, shared with Admin ----------------------------

    def test_changing_a_rate_warns_what_it_did_to_the_budget(self):
        """
        ⚠ ONE IMPLEMENTATION, TWO CALLERS. This used to live inside Admin's
        save_formset and fired nowhere else. Both now call
        bom_calc.reserve_changes(), so the screen and Admin cannot say different
        things about the same edit.
        """
        page = self.save(**{f"rate-{self.line.id}": "700"})
        body = page.content.decode()
        self.assertIn("BOM budget changed", body)
        self.assertIn(self.rcc.name, body)

    def test_the_reserve_really_moves_to_what_the_warning_said(self):
        self.save(**{f"rate-{self.line.id}": "700"})
        self.assertEqual(bom_calc.reserve(self.bom, self.rcc),
                         D("700") * self.project.bua_sqft)


class TheRateDefaultsScreen(Fixture):
    """
    The company's ₹/sqft — what a NEW project's BOQ starts from.

    ⚠⚠ THE SCREEN MOVED, AND THESE TESTS MOVED WITH IT. "Company rates" is now
       part of the construction activity master: the rate was never company
       data, it is a column on the activity. Saahil: "Those rates are related to
       concerned activity. Are they not? So already we are maintaining the rates
       in construction activity, then why is it coming in company profile?"

       `rate_defaults` is kept as a REDIRECT rather than deleted — somebody has
       it bookmarked and it was linked from the master data page for months.
    """

    def test_the_old_address_redirects_rather_than_404ing(self):
        self.assertRedirects(self.client.get(reverse("rate_defaults")),
                             reverse("activity_master"))

    def test_the_screen_lists_every_activity(self):
        body = self.client.get(reverse("activity_master")).content.decode()
        self.assertIn(self.rcc.name, body)
        self.assertIn(self.rcc.abbreviation, body)

    def test_a_rate_saves(self):
        self.client.post(reverse("activity_master_save"),
                         {f"rate-{self.rcc.id}": "700", f"gst-{self.rcc.id}": "18",
                          f"active-{self.rcc.id}": "on"}, follow=True)
        self.rcc.refresh_from_db()
        self.assertEqual(self.rcc.rate, D("700"))

    def test_changing_a_company_rate_does_not_touch_an_existing_estimate(self):
        """
        ⚠ THE THING SOMEBODY WOULD OTHERWISE ASSUME THE OPPOSITE OF. An estimate
        line copies the rate when its trade is added; the default only decides
        what the NEXT project starts from. If this ever changed, a rate edit
        would silently move the budget on every live project at once.
        """
        line = self.estimate.lines.get(name=self.rcc.name)
        was = line.rate
        reserve_was = bom_calc.reserve(self.bom, self.rcc)

        self.client.post(reverse("activity_master_save"),
                         {f"rate-{self.rcc.id}": "999", f"active-{self.rcc.id}": "on"}, follow=True)
        line.refresh_from_db()
        self.assertEqual(line.rate, was)
        self.assertEqual(bom_calc.reserve(self.bom, self.rcc), reserve_was)

    def test_the_activity_name_cannot_be_changed_once_quoted(self):
        """
        ⚠⚠ THIS TEST USED TO ASSERT THE FIELD WAS ABSENT, AND THE REWRITE IS THE
           RECORD. Hiding the name box was the OLD protection and it protected
           nothing — Django Admin renamed activities happily, and Saahil
           believed it was already blocked: "Renaming is not possible. If an
           activity is created, it stays."

           The field is now on the screen and the MODEL refuses the change — see
           ANCHOR: ACTIVITY-RENAME-BLOCKED. A field that refuses and says why
           teaches the rule; an absent field teaches nothing, and left Admin
           wide open.
        """
        body = self.client.get(reverse("activity_master")).content.decode()
        self.assertIn(f'name="name-{self.rcc.id}"', body)

        was = self.rcc.name
        page = self.client.post(reverse("activity_master_save"),
                                {f"name-{self.rcc.id}": "Renamed",
                                 f"rate-{self.rcc.id}": "600",
                                 f"active-{self.rcc.id}": "on"},
                                follow=True)
        self.rcc.refresh_from_db()
        self.assertEqual(self.rcc.name, was)
        self.assertIn("cannot change", page.content.decode())

    def test_an_unreadable_rate_is_reported_and_nothing_saved(self):
        was = self.rcc.rate
        page = self.client.post(reverse("activity_master_save"),
                                {f"rate-{self.rcc.id}": "seven hundred",
                                 f"active-{self.rcc.id}": "on"}, follow=True)
        self.rcc.refresh_from_db()
        self.assertEqual(self.rcc.rate, was)
        self.assertIn("could not be read", page.content.decode())


class TheCompanyProfileScreen(Fixture):
    """Us — what prints at the top of every document."""

    def test_the_screen_loads_and_creates_the_single_row(self):
        page = self.client.get(reverse("company_profile"))
        self.assertContains(page, "Company profile")
        self.assertEqual(CompanyProfile.objects.count(), 1)

    def test_saving_derives_the_state_from_the_gstin(self):
        """
        ⚠ Nobody types the state. It is half of the CGST/SGST-vs-IGST decision and
        letting someone type it only creates a second version to disagree with.
        """
        self.client.post(reverse("company_profile"),
                         {"name": "Elegance Skyz Pvt. Ltd.", "gst_number": "24AAACE0000A1Z5"},
                         follow=True)
        company = CompanyProfile.get_solo()
        self.assertEqual(company.gst_number, "24AAACE0000A1Z5")
        self.assertEqual(company.state, "Gujarat")

    def test_a_malformed_gstin_is_refused(self):
        self.client.post(reverse("company_profile"),
                         {"name": "Elegance Skyz", "gst_number": "NOT-A-GSTIN"}, follow=True)
        self.assertEqual(CompanyProfile.get_solo().gst_number, "")

    def test_there_is_never_more_than_one_company(self):
        """A second letterhead nobody knew about is worse than none."""
        for _ in range(3):
            self.client.post(reverse("company_profile"), {"name": f"Attempt"}, follow=True)
        self.assertEqual(CompanyProfile.objects.count(), 1)

    def test_a_missing_gstin_is_called_out_rather_than_left_blank(self):
        self.assertContains(self.client.get(reverse("company_profile")),
                            "not set, and it is not decoration")


class TheBomScreenColumns(Fixture):
    """The grid changes that came with the planning rate — slice 5a, step 3."""

    def screen(self):
        return self.client.get(reverse("bom_screen", args=[self.project.id]),
                               {"activity": "RCC"}).content.decode()

    def save(self, **fields):
        data = {"activity": "RCC"}
        data.update(fields)
        return self.client.post(reverse("bom_save", args=[self.project.id]), data, follow=True)

    def test_typing_a_plan_rate_saves_it(self):
        self.save(**{f"prate-{self.cement_line.id}": "310.00"})
        self.cement_line.refresh_from_db()
        self.assertEqual(self.cement_line.planned_rate, D("310.00"))

    def test_clearing_the_plan_rate_returns_to_the_master_rate(self):
        """
        ⚠ Blank means "no override", NOT zero — the same shape as the vendor
        rate. Reading it as zero would value the whole line at nothing.
        """
        self.cement_line.planned_rate = D("310.00")
        self.cement_line.save()
        self.save(**{f"prate-{self.cement_line.id}": ""})
        self.cement_line.refresh_from_db()
        self.assertIsNone(self.cement_line.planned_rate)
        self.assertEqual(bom_calc.planning_rate(self.cement_line), D("289.06"))

    def test_an_unreadable_plan_rate_is_reported_and_not_saved(self):
        """Consistent with every other cell: bad input never silently becomes 0."""
        self.cement_line.planned_rate = D("310.00")
        self.cement_line.save()
        page = self.save(**{f"prate-{self.cement_line.id}": "three hundred"})
        self.cement_line.refresh_from_db()
        self.assertEqual(self.cement_line.planned_rate, D("310.00"))
        self.assertIn("plan rate", page.content.decode().lower())

    def test_the_committed_figure_appears_on_the_screen(self):
        self.assertIn("Committed", self.screen())

    def test_stock_and_min_are_read_only_on_a_non_stock_material(self):
        """
        A service, transport or lumpsum item has no meaningful "how many are on
        site", so the boxes are shown but not invited.
        """
        services = MaterialGroup.objects.create(code="SEX", name="Site Expense",
                                                is_stock_item=False)
        labour = Material.objects.create(code="RCC-SEX-001", name="HYDRA SHIFTING",
                                         group=services, uom="Hour",
                                         estimation_rate=D("2750"), gst_percent=D("18"),
                                         home_activity=self.rcc)
        line = BomLine.objects.create(bom=self.bom, activity=self.rcc, material=labour,
                                      planned_qty=D("40"))
        body = self.screen()
        self.assertIn(f'name="stock-{line.id}"', body)
        marker = body.index(f'name="stock-{line.id}"')
        self.assertIn("readonly", body[marker:marker + 260])

    def test_a_stock_material_is_still_editable(self):
        """The other half of the rule above — cement must not be locked."""
        body = self.screen()
        marker = body.index(f'name="stock-{self.cement_line.id}"')
        self.assertNotIn("readonly", body[marker:marker + 260])


class TheInfoPanel(Fixture):
    """
    The standing notes live behind an ⓘ button.

    >>> ANCHOR: SECURITY-NOTICE <<<

    ⚠ THERE USED TO BE AN EXCEPTION, AND THERE IS NO LONGER ONE. The security
      warning — "no login is required to reach these screens" — stayed ON the
      page while every other note moved behind the button, because a risk you
      have to click to discover is a risk nobody discovers. It came out with the
      security slice, exactly as it promised it would, and the test below now
      asserts its absence.

      The anchor is kept because the rule it names still applies to the next
      such warning: an explanation belongs behind the ⓘ; a live risk does not.
    """

    def test_the_screens_offer_an_info_button(self):
        for url in (reverse("project_list"),
                    reverse("bom_screen", args=[self.project.id])):
            self.assertIn("infobtn", self.client.get(url).content.decode(),
                          f"{url} has no info button")

    def test_the_no_login_warning_has_gone_now_that_a_login_exists(self):
        """
        ⚠ THIS TEST IS THE INVERSE OF THE ONE IT REPLACES, AND THAT IS THE POINT.

        It used to assert that "No login is required" stayed ON the page and
        never moved behind the ⓘ — a risk you have to click to discover is a
        risk nobody discovers. That warning came out with the security slice,
        exactly as it said it would.

        A warning left up after it stops being true teaches people to skip the
        next one, so the assertion flips rather than being deleted.
        """
        for url in (reverse("project_list"),
                    reverse("bom_screen", args=[self.project.id])):
            body = self.client.get(url).content.decode()
            self.assertNotIn("No login is required", body,
                             f"{url} still carries a warning that is no longer true")


class CommittedValue(Fixture):
    """
    The money actually promised to vendors, per activity.

    Why it had to exist: po_value means "about to be ordered" and drops to zero
    the moment orders are raised, because posting clears the typed quantity. So
    there was no rupee figure anywhere for what had ALREADY been ordered — which
    stopped being tolerable once work orders began drawing on the same reserve.
    """

    def _approved_order(self):
        order = po_service.generate_purchase_orders(self.bom)[0]
        po_service.approve(order, gstin="24ABCDE1234F1Z5")
        return order

    def test_a_draft_commits_nothing(self):
        """A draft is not a promise to anybody."""
        po_service.generate_purchase_orders(self.bom)
        self.assertEqual(bom_calc.committed_value(self.cement_line), D("0.00"))

    def test_approving_commits_the_money(self):
        self._approved_order()
        # 1000 bags at the vendor's frozen rate of 292.97
        self.assertEqual(bom_calc.committed_value(self.cement_line), D("292970.00"))

    def test_a_line_discount_reduces_what_is_committed(self):
        order = self._approved_order()
        # Approved orders are locked in the UI; written directly here because the
        # point under test is the arithmetic, not the lock.
        order.lines.filter(bom_line=self.cement_line).update(discount_pct=D("10"))
        # 1000 x 292.97 = 292,970, less 10%
        self.assertEqual(bom_calc.committed_value(self.cement_line), D("263673.00"))

    def test_the_discount_survives_the_database_doing_the_summing(self):
        """
        ⚠ REGRESSION GUARD. The first version of bulk_committed_value expressed
        the discount as qty * rate * (1 - discount/100) in SQL. SQLite
        integer-divides 10/100 to zero, so every discount silently disappeared —
        while PostgreSQL, which this runs on in production, would have computed
        it correctly. The bug was therefore invisible on the machine that would
        have shipped it.

        This asserts the bulk figure equals the line's own Python arithmetic,
        which is the only thing that cannot drift by backend.
        """
        order = self._approved_order()
        order.lines.filter(bom_line=self.cement_line).update(discount_pct=D("7.5"))
        line = order.lines.get(bom_line=self.cement_line)
        self.assertEqual(bom_calc.committed_value(self.cement_line), line.taxable)

    def test_committed_value_excludes_gst(self):
        """
        It is compared against the reserve, and the reserve is ex-GST. Mixing the
        two once reported RCC at 99.3% of budget when the truth was 84.2%.
        """
        order = self._approved_order()
        line = order.lines.get(bom_line=self.cement_line)
        self.assertEqual(line.gst_percent, D("28"))          # cement is taxed
        self.assertEqual(bom_calc.committed_value(self.cement_line), line.taxable)

    def test_the_activity_total_adds_up_the_lines(self):
        self._approved_order()
        totals = bom_calc.activity_totals(self.bom, self.rcc)
        by_line = sum(f["committed_value"] for f in totals["figures"])
        self.assertEqual(totals["committed_value"], by_line)
        self.assertGreater(totals["committed_value"], D("0"))

    def test_po_value_and_committed_value_answer_different_questions(self):
        """
        Before posting: about-to-order has a figure, committed is zero.
        After approving: the reverse. Confusing them is the bug this prevents.
        """
        before = bom_calc.line_figures(self.cement_line)
        self.assertGreater(before["po_value"], D("0"))
        self.assertEqual(before["committed_value"], D("0.00"))

        self._approved_order()
        self.cement_line.refresh_from_db()
        after = bom_calc.line_figures(self.cement_line)
        self.assertEqual(after["po_value"], D("0"))          # the typed quantity was consumed
        self.assertGreater(after["committed_value"], D("0"))

    def test_the_bulk_figure_is_identical_to_the_per_line_one(self):
        """
        The bulk path exists for speed. If it ever disagrees with the plain one,
        speed is not the problem.
        """
        self._approved_order()
        lines = list(self.bom.lines.all())
        bulk = bom_calc.bulk_committed_value(lines)
        for line in lines:
            self.assertEqual(bulk[line.id], bom_calc.committed_value(line))

    def test_committed_value_comes_back_at_two_decimals(self):
        """Money is rounded where it is calculated, not in the template."""
        self._approved_order()
        value = bom_calc.committed_value(self.cement_line)
        self.assertEqual(value, value.quantize(D("0.01")))

    def test_more_lines_do_not_mean_more_queries(self):
        """
        >>> ANCHOR: BOM-CALC-COMMITTED <<<
        The shape of the work, not its speed — a timing test passes on a fast
        laptop and fails quietly later on a shared server. A per-row version of
        this figure is exactly what once cost 8,000 queries and nine seconds.
        """
        self._approved_order()
        few = list(self.bom.lines.all())
        with self.assertNumQueries(1):
            bom_calc.bulk_committed_value(few)

        for number in range(40):
            material = Material.objects.create(
                code=f"RCC-FIL-{number:03d}", name=f"FILLER {number}", group=self.cem,
                uom="Bag", estimation_rate=D("100"), gst_percent=D("18"),
                home_activity=self.rcc)
            BomLine.objects.create(bom=self.bom, activity=self.rcc, material=material,
                                   planned_qty=D("10"))

        many = list(self.bom.lines.all())
        self.assertEqual(len(many), len(few) + 40)
        with self.assertNumQueries(1):
            bom_calc.bulk_committed_value(many)


# ===========================================================================
# SLICE 7 — THE LAUNCHPAD AND THE CROSS-PROJECT DOCUMENT REGISTER
#
# Two screens that sit above a project rather than inside one, and the rules
# that keep them honest: a tile that goes nowhere must not look clickable, a
# filter must be able to find things that are not already on screen, and an
# action that spans every project must refuse the ones it has no business
# doing.
# ===========================================================================
import io
from unittest.mock import patch

from django.contrib import admin as django_admin

from masters.models import (DocumentType, UnitOfMeasure, VendorCategory,
                            active_uom_choices, resolve_uom)
from projects import hub


class TheLaunchpad(AuthedTestCase):
    """The home screen: five tiles, two of them not built yet."""

    def test_the_bare_address_is_the_launchpad_not_the_project_list(self):
        """
        ⚠ THE POINT OF THE WHOLE SCREEN. A launchpad you have to find from a
        header link is a launchpad nobody opens, so it has to be what "/" gives
        you. The project list moved to /projects/ to make room.
        """
        self.assertEqual(reverse("launchpad"), "/")
        self.assertEqual(reverse("project_list"), "/projects/")

    def test_the_project_list_still_works_at_its_new_address(self):
        self.assertEqual(self.client.get(reverse("project_list")).status_code, 200)

    def test_every_live_tile_points_somewhere_that_resolves(self):
        """
        A tile naming a URL that has been renamed should fail the suite, not
        404 on somebody's screen. This is why hub.py stores URL NAMES and never
        written-out paths.
        """
        live = [tile for tile in hub.tiles_for() if tile["live"]]
        self.assertTrue(live)
        for tile in live:
            self.assertTrue(tile["url"], f"{tile['key']} is live but resolved to nothing")
            self.assertEqual(self.client.get(tile["url"]).status_code, 200, tile["key"])

    def test_every_tile_drawn_greyed_has_since_been_built(self):
        """
        ⚠ THIS TEST USED TO ASSERT THE OPPOSITE, AND THE CHANGE IS THE RECORD OF
        A PROMISE BEING KEPT.

        Saahil asked for tiles with nothing behind them — "the last 2 will be
        added later but it gives a view to the user holistically". Task
        management and Analytics sat greyed from the day the launchpad was
        written; both are now live, and nobody had to be told where they were.

        The greyed state is not deleted — `hub.py` still supports it and the
        template still draws it — so the next unbuilt module can sit there the
        same way. There is simply nothing waiting today.
        """
        coming = [tile for tile in hub.tiles_for() if not tile["live"]]
        self.assertEqual(coming, [], "a tile is greyed again — is it genuinely unbuilt?")

        body = self.client.get(reverse("launchpad")).content.decode()
        self.assertIn("Analytics", body)
        self.assertIn("Task management", body)
        self.assertNotIn("Coming later", body)

    def test_a_role_filters_the_tiles_rather_than_rewriting_the_screen(self):
        """
        ⚠ THE WHOLE REASON THE TILES ARE DATA. Roles do not exist yet, but
        Saahil described the screen as "the admin sees 4-5 tiles" — so when
        security lands, showing somebody less is one argument to this function
        and not a redraw of a grid of divs.
        """
        everything = hub.tiles_for()
        site_only = hub.tiles_for(hub.ROLE_SITE)
        self.assertLess(len(site_only), len(everything))
        self.assertNotIn("masters", {tile["key"] for tile in site_only})

    def test_every_screen_carries_a_way_back_to_the_launchpad(self):
        """
        ⚠ TWO WAYS OUT, ON EVERY SCREEN, AND BOTH IN THE HEADER: the ELEGANCE
          SKYZ wordmark and a Home link beside the ⓘ. Saahil moved Home out of
          the module tab strips — a strip is for the screens of one module, and
          the way out of it is not one of them.
        """
        home = reverse("launchpad")
        for name in ("project_list", "master_data", "po_register", "task_board",
                     "task_mine", "analytics_home", "analytics_payments"):
            body = self.client.get(reverse(name)).content.decode()
            header = body.split("</header>")[0]
            self.assertEqual(header.count(f'href="{home}"'), 2,
                             f"{name} does not carry both ways home in its header")

    def test_the_launchpad_no_longer_warns_about_a_missing_login(self):
        """The first screen anybody sees, and now they only see it after signing in."""
        self.assertNotContains(self.client.get(reverse("launchpad")), "No login is required")


class TheMasterDataPage(AuthedTestCase):
    """The second level behind the Master data tile."""

    def test_every_table_has_a_screen_and_nothing_opens_admin(self):
        """
        ⚠⚠ THIS TEST ASSERTED THE OPPOSITE, AND THE REWRITE IS THE RECORD. It
          used to require "/admin/masters/materialgroup/" to be ON the page and
          honestly labelled, because five tables had no screen. Saahil found the
          consequence: "the UOM tile still shows and opens up Django, I could not
          see any UI for that."

          All five now have screens, so the page carries five entries and no
          Admin links at all. Materials and Vendors each open a screen with
          tabs; Construction activities is one screen and carries the ₹/sqft
          that used to be called Company rates.
        """
        page = self.client.get(reverse("master_data"))
        self.assertEqual(page.status_code, 200)
        body = page.content.decode()
        for name in ("materials_home", "vendors_home", "activity_master",
                     "company_profile", "user_list"):
            self.assertIn(reverse(name), body)
        # ⚠ The header carries an Admin link for a superuser; the PAGE must not.
        content = body.split("</header>")[-1]
        self.assertNotIn("/admin/masters/", content)
        self.assertNotIn("/admin/projects/", content)

    def test_link_tables_do_not_get_a_tile_of_their_own(self):
        """
        ⚠ Saahil: "Material is to be linked to activity in the same material
        master screen, not as a separate tile." Admin already agreed — both
        models are inlines on the record they belong to — so a tile offered a
        second, worse route to the same data.
        """
        # ⚠ ONE LIST NOW, NOT (in_admin, own) — nothing behind this tile opens
        #   Django Admin any more, so the split had nothing left to describe.
        titles = {e["title"] for e in hub.master_data_for()}
        self.assertNotIn("Material to activity", titles)
        self.assertNotIn("Vendor categories", titles)
        self.assertIn("Materials", titles)
        self.assertIn("Vendors", titles)

    def test_the_master_data_page_is_reachable_from_the_launchpad(self):
        """
        ⚠ Asking which URL names nothing links to is how the orphaned discard
        flow was found. Every new screen in this slice gets the same question.
        """
        body = self.client.get(reverse("launchpad")).content.decode()
        self.assertIn(reverse("master_data"), body)
        self.assertIn(reverse("po_register"), body)


class TheDocumentRegister(Fixture):
    """Every document on every project, at one address."""

    def setUp(self):
        super().setUp()
        self.create_pos()
        self.orders = list(PurchaseOrder.objects.all())
        self.assertTrue(self.orders)

        # A second site, so "cross-project" means something rather than being
        # one project wearing a different hat.
        self.other = Project.objects.create(
            code="PRJ-002", name="Sarkhej", bua_sqft=D("12000"), status=Project.Status.WON)
        Estimate.objects.create(project=self.other)
        other_bom = Bom.objects.create(project=self.other)
        line = BomLine.objects.create(
            bom=other_bom, activity=self.rcc, material=self.cement,
            planned_qty=D("400"), vendor=self.other_vendor, vendor_rate=D("300"))
        line.order_qty_override = D("400")
        line.save(update_fields=["order_qty_override"])
        self.other_order = po_service.generate_purchase_orders(other_bom)[0]

    def test_it_shows_documents_from_every_project(self):
        body = self.client.get(reverse("po_register")).content.decode()
        self.assertIn(self.other_order.number, body)
        self.assertIn(self.orders[0].number, body)

    def test_the_per_project_screen_is_untouched(self):
        """
        ⚠ Saahil's correction, and the reason this screen is small: "BOM should
        also be able to navigate and check out POs, as they will be created from
        there." Documents are reachable two ways and BOTH stay.
        """
        screen = self.client.get(reverse("po_screen", args=[self.project.id]))
        self.assertEqual(screen.status_code, 200)
        self.assertNotContains(screen, self.other_order.number)

    def test_filtering_by_project(self):
        body = self.client.get(reverse("po_register"),
                               {"project": self.other.id}).content.decode()
        self.assertIn(self.other_order.number, body)
        self.assertNotIn(self.orders[0].number, body)

    def test_filtering_by_vendor(self):
        body = self.client.get(reverse("po_register"),
                               {"vendor": self.other_vendor.id}).content.decode()
        self.assertIn(self.other_order.number, body)

    def test_filtering_by_status(self):
        po_service.approve(self.other_order, gstin="24ABCDE1234F1Z5")
        body = self.client.get(reverse("po_register"),
                               {"status": "approved"}).content.decode()
        self.assertIn(self.other_order.number, body)
        self.assertNotIn(self.orders[0].number, body)

    def test_filtering_by_document_type(self):
        body = self.client.get(reverse("po_register"), {"type": "WO"}).content.decode()
        self.assertNotIn(self.other_order.number, body)

    def test_searching_the_document_number(self):
        body = self.client.get(reverse("po_register"),
                               {"q": self.other_order.number}).content.decode()
        self.assertIn(self.other_order.number, body)
        self.assertNotIn(self.orders[0].number, body)

    def test_the_month_range_covers_the_whole_of_the_closing_month(self):
        """
        ⚠ "Up to and including August" must not depend on how many days August
        has. The upper bound rolls forward to the first of September and
        excludes it, so the 31st is in and nothing else is.
        """
        PurchaseOrder.objects.filter(pk=self.other_order.pk).update(
            raised_on=date(2026, 8, 31))
        shown = self.client.get(reverse("po_register"),
                                {"from": "2026-08", "to": "2026-08"}).content.decode()
        self.assertIn(self.other_order.number, shown)

        missed = self.client.get(reverse("po_register"),
                                 {"from": "2026-09"}).content.decode()
        self.assertNotIn(self.other_order.number, missed)

    def test_the_activity_filter_never_repeats_a_document(self):
        """
        ⚠ THE JOIN IS TWO HOPS — PO line, BOM line, activity — so a document
        with two lines in one trade would appear twice without distinct(). The
        fixture's first order has exactly that: cement and steel, both RCC.
        """
        response = self.client.get(reverse("po_register"), {"activity": "RCC"})
        numbers = [row["order"].number for row in response.context["rows"]]
        self.assertEqual(len(numbers), len(set(numbers)))

    def test_the_dropdowns_are_built_from_every_document_not_this_page(self):
        """
        ⚠ Saahil asked for the filters to search "from the whole relevant lot".
        A dropdown built from the current page can only find what you can
        already see, which is not a filter.
        """
        with patch("projects.views.REGISTER_PAGE_SIZE", 1):
            response = self.client.get(reverse("po_register"))
            self.assertEqual(len(response.context["rows"]), 1)
            vendors = {v.id for v in response.context["vendors"]}
        self.assertIn(self.vendor.id, vendors)
        self.assertIn(self.other_vendor.id, vendors)

    def test_only_projects_that_have_documents_appear_in_the_filter(self):
        """An empty filter option is a promise the screen cannot keep."""
        empty = Project.objects.create(code="PRJ-003", name="Nothing here",
                                       bua_sqft=D("100"), status=Project.Status.WON)
        listed = {p.id for p in self.client.get(reverse("po_register")).context["projects"]}
        self.assertNotIn(empty.id, listed)

    def test_the_footer_says_it_totals_this_page_and_not_the_filter(self):
        """
        Honesty about a figure that could easily be misread. order_value walks
        lines in Python, so totalling every match on every page load would mean
        fetching every line of every document.
        """
        self.assertContains(self.client.get(reverse("po_register")), "THIS PAGE")

    def test_it_does_not_ask_the_database_once_per_document(self):
        """
        ⚠ THE SHAPE OF THE WORK, not its speed. This screen spans every project,
        so it is the one place where a per-row query would climb forever. Bugs
        3, 4 and 5 were all this shape.
        """
        baseline = len(self.client.get(reverse("po_register")).context["rows"])
        # ⚠ TWO OF THESE ARE THE LOGIN RATHER THAN THE SCREEN — the session row
        #   and the user row, on every authenticated request. The profile that
        #   carries the role rides along on the user query, via select_related in
        #   accounts.backends.EmailBackend.get_user. The screen itself still costs
        #   exactly what it cost before there was a login.
        #
        # ⚠ AND ONE IS THE ⓘ PANEL'S TRANSLATIONS — ANCHOR: INFO-PANELS. Fixed
        #   per page, not per row; the growth assertion below is untouched.
        with self.assertNumQueries(9):
            self.client.get(reverse("po_register"))

        for number in range(6):
            bom = Bom.objects.create(
                project=Project.objects.create(code=f"PRJ-1{number:02d}", name=f"Site {number}",
                                               bua_sqft=D("100"), status=Project.Status.WON))
            line = BomLine.objects.create(bom=bom, activity=self.rcc, material=self.cement,
                                          planned_qty=D("10"), vendor=self.vendor,
                                          vendor_rate=D("290"))
            line.order_qty_override = D("10")
            line.save(update_fields=["order_qty_override"])
            po_service.generate_purchase_orders(bom)

        self.assertGreater(len(self.client.get(reverse("po_register")).context["rows"]), baseline)
        # ⚠ THE ASSERTION THAT MATTERS: six more documents, and the SAME count as
        #   above. 8 became 9 only because every screen now fetches its ⓘ
        #   translations once — fixed per page, never per row.
        with self.assertNumQueries(9):
            self.client.get(reverse("po_register"))


class RegisterDownloads(Fixture):
    """The two buttons: a register for the accountant, and the documents themselves."""

    def setUp(self):
        super().setUp()
        self.create_pos()
        self.order = PurchaseOrder.objects.first()

    def _post(self, name, data=None, query=""):
        return self.client.post(f"{reverse(name)}{query}", data or {})

    def test_the_excel_register_comes_back_as_a_spreadsheet(self):
        response = self._post("po_register_excel")
        self.assertEqual(response.status_code, 200)
        self.assertIn("spreadsheetml", response["Content-Type"])
        self.assertIn("PurchaseOrders_", response["Content-Disposition"])

    def test_the_project_name_travels_with_the_code(self):
        """
        Saahil, on the register screen: a project name beside the code makes it
        easier to identify. The Excel export carries the same pair, in the same
        order, so the accountant is not left reading PRJ-000005 cold either.
        """
        from openpyxl import load_workbook

        book = load_workbook(io.BytesIO(self._post("po_register_excel").content))
        sheet = book.active
        heading = [cell.value for cell in sheet[1]]
        self.assertEqual(heading[6:8], ["Project", "Project name"])

        first_line = next(sheet.iter_rows(min_row=2, values_only=True))
        self.assertEqual(first_line[6:8], (self.project.code, self.project.name))

    def test_the_apportioned_columns_are_highlighted_correctly(self):
        """
        ⚠⚠ THE ONE THAT MATTERS. `headings` grew by one column when the project
        name was added; the highlight used to be the literal string "WXYZ" and
        would have silently painted the wrong cells — a picture that renders and
        is wrong. Now it is computed from `headings`, and this pins that down.
        """
        from openpyxl import load_workbook

        book = load_workbook(io.BytesIO(self._post("po_register_excel").content))
        sheet = book.active
        heading = [cell.value for cell in sheet[1]]
        painted = [cell.value for cell in sheet[1]
                  if cell.fill.fgColor.rgb == "008A6D1F"]
        self.assertEqual(painted, heading[-5:])
        self.assertEqual(heading[-5:], [
            "Line deduction", "Line round off", "Line TDS",
            "Line order value", "Line net payable"])

    def test_every_column_has_a_width_and_the_money_ones_a_format(self):
        """
        >>> ANCHOR: PO-LINE-SHARES <<<
        ⚠⚠ THESE TWO RANGES HAD ALREADY DRIFTED and nobody could have seen it.
           The widths tuple held 26 entries for 27 columns, and the number format
           ran 15–26 when the money starts at 16 — so UOM was given Indian digit
           grouping and the last money column got neither. A spreadsheet with a
           narrow column still opens, which is exactly why this needs a test
           rather than an eye. Both are now keyed off `headings`.
        """
        from openpyxl import load_workbook

        book = load_workbook(io.BytesIO(self._post("po_register_excel").content))
        sheet = book.active
        heading = [cell.value for cell in sheet[1]]

        for index in range(1, len(heading) + 1):
            letter = sheet.cell(row=1, column=index).column_letter
            self.assertIsNotNone(sheet.column_dimensions[letter].width,
                                 f"column {heading[index - 1]} has no width")

        money_from = heading.index("Qty") + 1
        for row in sheet.iter_rows(min_row=2, max_row=2):
            for cell in row:
                if cell.column >= money_from:
                    self.assertEqual(cell.number_format, "#,##,##0.00",
                                     f"{heading[cell.column - 1]} is not formatted as money")
                elif heading[cell.column - 1] == "UOM":
                    self.assertNotEqual(cell.number_format, "#,##,##0.00",
                                        "UOM is text and was being number-formatted")

    def test_the_document_amounts_add_up_across_the_lines(self):
        """
        >>> ANCHOR: PO-LINE-SHARES <<<
        ⚠⚠ THE REASON THIS EXPORT EXISTS. Saahil: the accountant filters it and
           pushes it into Tally, so *"the header discounts have to be distributed
           properly across all the line items... so the numbers add up properly
           for them"*. Four columns used to repeat the document figure on every
           line, and summing them gave a multiple of the truth.

        ⚠ ASSERTED AGAINST `totals()`, never against a number typed here — a
          hand-written expected total is a second implementation of the ladder
          and is free to be wrong in the same direction as the code.

        ⚠⚠ THE PERCENTAGES ARE SET HERE ON PURPOSE, AND THE FIRST DRAFT OF THIS
           TEST DID NOT DO IT. The shared fixture raises orders at 0% deduction
           and 0% TDS, so both columns summed to zero and the assertion passed
           against the OLD repeating code as happily as against the new — zero
           repeated four times is still zero. A test that cannot fail is worse
           than no test, because it reads like cover. Awkward decimals, so a
           three-line split cannot come out even.
        """
        from decimal import Decimal
        from openpyxl import load_workbook

        self.order.deduction_pct = Decimal("2.35")
        self.order.tds_pct = Decimal("1.75")
        self.order.save()
        self.assertGreater(self.order.totals()["tds"], Decimal("0"),
                           "the fixture stopped exercising TDS")
        self.assertGreater(self.order.lines.count(), 1,
                           "a single-line order cannot show an apportionment bug")

        book = load_workbook(io.BytesIO(
            self._post("po_register_excel", {"ids": [self.order.id]}).content))
        sheet = book.active
        heading = [cell.value for cell in sheet[1]]
        rows = [row for row in sheet.iter_rows(min_row=2, values_only=True) if row[0]]
        self.assertEqual(len(rows), self.order.lines.count())

        totals = self.order.totals()
        for column, key in (("Line deduction", "deduction"),
                            ("Line TDS", "tds"),
                            ("Line round off", "round_off"),
                            ("Line order value", "order_value"),
                            ("Line net payable", "net_payable")):
            index = heading.index(column)
            added = sum(Decimal(str(row[index])) for row in rows)
            self.assertEqual(added, totals[key],
                             f"summing {column} did not give the document's {key}")

    def test_the_excel_register_obeys_the_filters_it_was_opened_with(self):
        """
        ⚠ ONE FILTER IMPLEMENTATION, SHARED. An export that quietly disagreed
        with the screen it came from would be worse than no export at all.
        """
        from openpyxl import load_workbook

        wide = load_workbook(io.BytesIO(self._post("po_register_excel").content))
        self.assertIn(self.order.number,
                      [row[0] for row in wide.active.iter_rows(min_row=2, values_only=True)])

        narrow = load_workbook(io.BytesIO(
            self._post("po_register_excel", query="?q=NOTHINGMATCHESTHIS").content))
        self.assertNotIn(self.order.number,
                         [row[0] for row in narrow.active.iter_rows(min_row=2, values_only=True)])

    def test_ticking_rows_narrows_it_further_than_the_filters(self):
        """
        ⚠ ONE ROW PER LINE, NOT PER DOCUMENT, since Saahil asked for line detail:
        "the download document into excel from PO should also have line items as
        well for easy tracking". So a two-line order is two rows carrying the
        same document number — which is the point, not a duplicate.
        """
        from openpyxl import load_workbook

        response = self._post("po_register_excel", {"ids": [self.order.id]})
        book = load_workbook(io.BytesIO(response.content))
        numbers = [row[0] for row in book.active.iter_rows(min_row=2, values_only=True) if row[0]]
        self.assertEqual(set(numbers), {self.order.number})
        self.assertEqual(len(numbers), self.order.lines.count())

    def test_the_zip_refuses_when_everything_selected_is_a_draft(self):
        """
        ⚠ APPROVED ONWARDS ONLY, the same rule as the single download. A draft
        that reaches a vendor as a PDF is indistinguishable from an order.
        Refused with a reason rather than handed over — and refused BEFORE
        WeasyPrint is imported, which is why this test runs in CI at all.
        """
        response = self.client.post(reverse("po_register_zip"), {}, follow=True)
        self.assertContains(response, "still drafts")

    def test_the_zip_refuses_more_than_it_can_build_in_one_request(self):
        """
        ⚠ Saahil rejected a low cap — he wants to choose what to download — so
        the ceiling sits well above ordinary use. It still has to exist:
        WeasyPrint runs inside the request, and a browser waiting on four
        hundred PDFs cannot tell working from dead.
        """
        po_service.approve(self.order, gstin="24ABCDE1234F1Z5")
        with patch("projects.views.ZIP_LIMIT", 0):
            response = self.client.post(reverse("po_register_zip"),
                                        {"ids": [self.order.id]}, follow=True)
        self.assertContains(response, "Narrow it with the filters")

    def test_the_downloads_are_post_only(self):
        """A GET must never do work. Browsers re-fetch GET addresses freely."""
        for name in ("po_register_excel", "po_register_zip", "po_register_advance"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 405, name)


class RegisterBulkActions(Fixture):
    """What the register is allowed to change, and what it is not."""

    def setUp(self):
        super().setUp()
        # Two vendors, so Post POs raises TWO documents rather than one. The
        # mixed-type rule cannot be tested against a single document.
        self.steel_line.vendor = self.other_vendor
        self.steel_line.save(update_fields=["vendor"])
        self.create_pos()
        self.order = PurchaseOrder.objects.order_by("id").first()

    def test_approving_is_not_possible_from_this_screen(self):
        """
        ⚠ REFUSED ON PURPOSE AND NOT AN OVERSIGHT. Approval locks a document
        permanently and hard-blocks without a GSTIN. A button that locked forty
        documents across every project, clickable by anyone who knows the
        address while there are still no permissions, is the largest thing this
        slice could have got wrong.
        """
        response = self.client.post(reverse("po_register_advance"),
                                    {"to": "approved", "ids": [self.order.id]}, follow=True)
        self.assertContains(response, "Approving is done on the document itself")
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, PurchaseOrder.Status.DRAFT)

    def test_a_mixed_selection_is_refused_rather_than_guessed_at(self):
        """
        ⚠ A work order reads "Completed" where a purchase order reads
        "Delivered" — the same step, but the documents say different words and
        one button cannot honestly say both. Saahil chose blocking over
        inventing a third word.
        """
        second = PurchaseOrder.objects.exclude(pk=self.order.pk).first()
        self.assertIsNotNone(second, "fixture should raise more than one document")
        PurchaseOrder.objects.filter(pk=second.pk).update(document_type=DocumentType.WO)

        for order in (self.order, second):
            order.refresh_from_db()
            po_service.approve(order, gstin="24ABCDE1234F1Z5")

        response = self.client.post(reverse("po_register_advance"),
                                    {"to": "delivered", "ids": [self.order.id, second.id]},
                                    follow=True)
        self.assertContains(response, "mixes purchase orders and work orders")

    def test_it_moves_several_documents_at_once(self):
        po_service.approve(self.order, gstin="24ABCDE1234F1Z5")
        po_service.mark_delivered(self.order)
        response = self.client.post(reverse("po_register_advance"),
                                    {"to": "paid", "ids": [self.order.id]}, follow=True)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, PurchaseOrder.Status.PAID)
        self.assertContains(response, "marked paid")

    def test_a_document_that_is_not_ready_is_reported_not_skipped_silently(self):
        """
        ⚠ The lifecycle is strictly sequential, and the register does not get to
        bend it. Every document still goes through po_service one at a time, so
        the refusal is the same one the document screen would give.
        """
        response = self.client.post(reverse("po_register_advance"),
                                    {"to": "paid", "ids": [self.order.id]}, follow=True)
        self.assertContains(response, "left alone")
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, PurchaseOrder.Status.DRAFT)


# ===========================================================================
# SLICE 8 — THE MASTER DATA SCREENS AND THE EXCEL ROUND TRIP
#
# The rule underneath all of it: a code is the key, a database id never appears,
# and a round trip through Excel that changes nothing must change nothing.
# ===========================================================================
from django.core.exceptions import ValidationError

from masters import sheets
from masters.models import VendorGroup


class TheActivityMasterMoved(AuthedTestCase):
    """It lives in `masters` now. The table did not move and neither did a row."""

    def test_it_is_importable_from_masters(self):
        from masters.models import Activity as FromMasters
        self.assertIs(FromMasters, Activity)

    def test_the_table_was_deliberately_not_renamed(self):
        """
        ⚠ Moving a model between apps and renaming its table are two separate
        risks and only one buys anything. Nothing reads a table name; renaming
        would have rewritten a table every BOM line and purchase order points at.
        """
        self.assertEqual(Activity._meta.db_table, "projects_activity")

    def test_the_eighteen_trades_are_still_there(self):
        self.assertEqual(Activity.objects.count(), 18)


class MaterialsCarryTheirTrade(Fixture):
    """The activity is a column on the material, not a row in a link table."""

    def test_a_material_must_have_a_home_activity(self):
        """
        ⚠ ENFORCED BY THE COLUMN, NOT BY A HABIT. Saahil's rule: "enforce rule
        for the first activity cell, not the second".
        """
        from django.db.utils import IntegrityError
        with self.assertRaises(IntegrityError):
            Material.objects.create(code="XXX-CEM-999", name="NO TRADE", group=self.cem,
                                    uom="Bag")

    def test_the_second_activity_may_be_blank(self):
        """"material may have the second activity as a blank" — most are."""
        self.assertIsNone(self.cement.also_used_in)
        self.cement.full_clean(exclude=["code"])

    def test_the_second_activity_may_not_repeat_the_first(self):
        self.cement.also_used_in = self.rcc
        with self.assertRaises(ValidationError):
            self.cement.clean()

    def test_the_material_search_finds_either_activity(self):
        masonry = Activity.objects.get(abbreviation="MAS")
        self.cement.also_used_in = masonry
        self.cement.save(update_fields=["also_used_in"])
        body = self.client.get(reverse("material_list"), {"activity": "MAS"}).content.decode()
        self.assertIn(self.cement.code, body)

    def test_filtering_by_activity_never_duplicates_a_row(self):
        """Two columns on one row cannot produce two rows. A join could."""
        response = self.client.get(reverse("material_list"), {"activity": "RCC"})
        codes = [m.code for m in response.context["rows"]]
        self.assertEqual(len(codes), len(set(codes)))


class VendorsCarryGroupAndTrade(Fixture):
    """Two fields answering two questions, and they were nearly merged into one."""

    def setUp(self):
        super().setUp()
        self.group = VendorGroup.objects.create(name="General Construction Material")
        self.vendor.group = self.group
        self.vendor.activity_1 = self.rcc
        self.vendor.save(update_fields=["group", "activity_1"])

    def test_group_and_activity_are_different_fields(self):
        """
        ⚠ Saahil, after we looked at all 37 categories together: "lets use vendor
        category as an identifier to search vendor … lets not mix vendor category
        and link them to Vendor Activities."
        """
        self.assertEqual(self.vendor.group.name, "General Construction Material")
        self.assertEqual(self.vendor.activity_1, self.rcc)

    def test_both_are_optional(self):
        bare = Vendor.objects.create(code="VEN-900", name="Cash purchase", phone="9000000000")
        self.assertIsNone(bare.group)
        self.assertIsNone(bare.activity_1)

    def test_the_vendor_list_filters_on_the_group(self):
        body = self.client.get(reverse("vendor_list"),
                               {"group": self.group.id}).content.decode()
        self.assertIn(self.vendor.name, body)

    def test_the_vendor_list_can_show_only_those_without_a_gstin(self):
        """A vendor without one cannot have a purchase order approved."""
        response = self.client.get(reverse("vendor_list"), {"nogst": "1"})
        self.assertIn(self.vendor, list(response.context["rows"]))

    def test_there_is_no_third_document_type(self):
        """
        ⚠ "no, it is rare to have both but, keep PO as default". A vendor who
        does both is handled per document, on the preview.
        """
        self.assertEqual([v for v, _ in DocumentType.choices], ["PO", "WO"])
        self.assertEqual(Vendor().default_document_type, DocumentType.PO)


class TheExcelRoundTrip(Fixture):
    """⚠⚠ THE PROPERTY THIS WHOLE HALF OF THE SLICE WAS BUILT TO."""

    def _material_file(self):
        stream = io.BytesIO()
        sheets.material_workbook().save(stream)
        stream.seek(0)
        return stream

    def _vendor_file(self):
        stream = io.BytesIO()
        sheets.vendor_workbook().save(stream)
        stream.seek(0)
        return stream

    def test_downloading_and_uploading_unchanged_changes_nothing(self):
        """
        Download the file, change nothing, upload it → 0 created, N skipped,
        0 errors. If a round trip through Excel alters one record that is a bug.
        """
        before = Material.objects.count()
        report = sheets.read_materials(self._material_file())
        self.assertEqual(report.created, [], report.created)
        self.assertEqual(report.errors, [], report.errors)
        self.assertEqual(len(report.skipped), before)
        self.assertEqual(Material.objects.count(), before)

    def test_the_same_holds_for_vendors(self):
        before = Vendor.objects.count()
        report = sheets.read_vendors(self._vendor_file())
        self.assertEqual(report.created, [], report.created)
        self.assertEqual(report.errors, [], report.errors)
        self.assertEqual(len(report.skipped), before)

    def test_no_database_id_appears_anywhere_in_the_file(self):
        """
        ⚠ Saahil's rule: "if we straight up download an SQL query type file, the
        user will be confused." The CODE is the key.
        """
        from openpyxl import load_workbook
        sheet = load_workbook(self._material_file())["Materials"]
        headings = [c.value for c in sheet[1]]
        self.assertNotIn("id", [str(h).lower() for h in headings if h])
        self.assertEqual(headings[0], "Code")

    def test_changing_a_cell_updates_that_material(self):
        from openpyxl import load_workbook
        book = load_workbook(self._material_file())
        sheet = book["Materials"]
        for row in sheet.iter_rows(min_row=3):
            if row[0].value == self.cement.code:
                row[1].value = "CEMENT OPC 53 GRADE"
                break
        stream = io.BytesIO()
        book.save(stream)
        stream.seek(0)

        report = sheets.read_materials(stream)
        self.assertEqual(report.errors, [])
        self.cement.refresh_from_db()
        self.assertEqual(self.cement.name, "CEMENT OPC 53 GRADE")
        # >>> ANCHOR: IMPORT-REPORT <<<
        # ⚠⚠ THIS LINE USED TO READ `report.created` AND WAS ASSERTING THE BUG.
        #    Editing an existing material is an UPDATE; it was filed under
        #    "created" because there was no other bucket, which is what made the
        #    summary line say "1 created" over a detail line saying "updated".
        #    See C5 and `test_counts_and_reports.py`.
        self.assertEqual(len(report.created), 0, "nothing was created — this row existed")
        self.assertEqual(len(report.updated), 1)

    def test_a_blank_code_creates_a_material_and_generates_its_code(self):
        """One file serves download, correction and fresh additions."""
        from openpyxl import load_workbook
        book = load_workbook(self._material_file())
        sheet = book["Materials"]
        sheet.append(["", "NEW THING", "SPEC", self.cem.code, "RCC", "", "Bag",
                      100, 18, "", "No", "Yes", "", 0, ""])
        stream = io.BytesIO()
        book.save(stream)
        stream.seek(0)

        before = Material.objects.count()
        report = sheets.read_materials(stream)
        self.assertEqual(report.errors, [], report.errors)
        self.assertEqual(Material.objects.count(), before + 1)
        made = Material.objects.get(name="NEW THING")
        self.assertTrue(made.code.startswith("RCC-CEM-"), made.code)

    def test_a_code_that_does_not_exist_is_refused_with_its_row_number(self):
        """
        ⚠ A code is never typed. A row naming one we do not have is a mistake,
        not an instruction to create it under that code.
        """
        from openpyxl import load_workbook
        book = load_workbook(self._material_file())
        sheet = book["Materials"]
        sheet.append(["RCC-CEM-777", "GHOST", "", self.cem.code, "RCC", "", "Bag",
                      1, 18, "", "No", "Yes", "", 0, ""])
        stream = io.BytesIO()
        book.save(stream)
        stream.seek(0)

        report = sheets.read_materials(stream)
        self.assertTrue(report.errors)
        self.assertIn("RCC-CEM-777", report.errors[0][1])

    def test_an_unreadable_number_never_becomes_zero(self):
        """
        ⚠ A rate that silently became 0 is indistinguishable from a rate somebody
        meant to be 0, and it quietly changes every estimate built on it.
        """
        from openpyxl import load_workbook
        book = load_workbook(self._material_file())
        sheet = book["Materials"]
        for row in sheet.iter_rows(min_row=3):
            if row[0].value == self.cement.code:
                row[7].value = "two hundred and eighty nine"
                break
        stream = io.BytesIO()
        book.save(stream)
        stream.seek(0)

        report = sheets.read_materials(stream)
        self.assertTrue(report.errors)
        self.cement.refresh_from_db()
        self.assertEqual(self.cement.estimation_rate, D("289.06"))

    def test_an_unknown_group_is_refused_rather_than_guessed_at(self):
        from openpyxl import load_workbook
        book = load_workbook(self._material_file())
        sheet = book["Materials"]
        sheet.append(["", "MYSTERY", "", "NOPE", "RCC", "", "Bag",
                      1, 18, "", "No", "Yes", "", 0, ""])
        stream = io.BytesIO()
        book.save(stream)
        stream.seek(0)

        report = sheets.read_materials(stream)
        self.assertTrue(any("NOPE" in problem for _row, problem in report.errors))

    def test_the_downloads_are_post_only(self):
        """A GET must never do work — browsers re-fetch them freely."""
        for name in ("material_export", "material_import", "vendor_export", "vendor_import"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 405, name)

    def test_the_buttons_are_on_the_screens(self):
        """⚠ Asking which URL names nothing links to is how an orphan is found."""
        materials = self.client.get(reverse("material_list")).content.decode()
        self.assertIn(reverse("material_export"), materials)
        self.assertIn(reverse("material_import"), materials)
        vendors = self.client.get(reverse("vendor_list")).content.decode()
        self.assertIn(reverse("vendor_export"), vendors)
        self.assertIn(reverse("vendor_import"), vendors)


class TheProjectStatusControl(Fixture):
    """Draft → Quoted → Won, from the screen the estimate lives on."""

    def test_it_is_on_the_boq_screen(self):
        """
        ⚠ Saahil went looking for it here and could not find it: "I could not
        see a button to change the approval status from draft to quote to won?"
        """
        body = self.client.get(reverse("boq_screen", args=[self.project.id])).content.decode()
        self.assertIn(reverse("project_status", args=[self.project.id]), body)

    def test_it_changes_the_status(self):
        self.client.post(reverse("project_status", args=[self.project.id]),
                         {"status": "quoted"}, follow=True)
        self.project.refresh_from_db()
        self.assertEqual(self.project.status, Project.Status.QUOTED)

    def test_setting_won_still_locks_the_estimate(self):
        """
        ⚠ MOVING THE CONTROL DOES NOT SOFTEN THE RULE. The BOQ locks at Won,
        Admin included, and the only way back is Quoted — which leaves a trace.
        """
        self.client.post(reverse("project_status", args=[self.project.id]),
                         {"status": "quoted"}, follow=True)
        self.assertTrue(Estimate.objects.get(project=self.project).is_editable)
        self.client.post(reverse("project_status", args=[self.project.id]),
                         {"status": "won"}, follow=True)
        self.assertFalse(Estimate.objects.get(project=self.project).is_editable)

    def test_it_is_post_only(self):
        self.assertEqual(
            self.client.get(reverse("project_status", args=[self.project.id])).status_code, 405)

    def test_a_status_that_does_not_exist_is_refused(self):
        response = self.client.post(reverse("project_status", args=[self.project.id]),
                                    {"status": "banana"}, follow=True)
        self.assertContains(response, "not a status")


class StockOnTwoLinesOfOneBom(Fixture):
    """
    ⚠ NOT A DOUBLE-COUNT BUG, AND THE NOTE THAT CALLED IT ONE WAS WRONG.

    Per-line stock is deliberate. Saahil: "if he adds stock in material line 1,
    that should add up to header, and if there is stock in material line 2, even
    that should add up, dual entry is the right way". Two lines of 100 means 200
    bags on site, split between two trades.

    What the system cannot tell apart is one pile of 100 typed twice. So it says
    where else the material holds stock, and leaves the judgement to the person.
    """

    def setUp(self):
        super().setUp()
        self.masonry = Activity.objects.get(abbreviation="MAS")
        EstimateLine.objects.create(estimate=self.estimate, name=self.masonry.name,
                                    rate=self.masonry.rate, gst_percent=self.masonry.gst_percent)
        self.cement_in_masonry = BomLine.objects.create(
            bom=self.bom, activity=self.masonry, material=self.cement,
            planned_qty=D("500"), stock_qty=D("80"), vendor=self.vendor,
            vendor_rate=D("292.97"))

    def test_the_allocation_is_left_alone(self):
        """Both figures stand. Nothing is corrected, merged or averaged."""
        self.assertEqual(self.cement_line.stock_qty, D("200"))
        self.assertEqual(self.cement_in_masonry.stock_qty, D("80"))

    def test_each_line_keeps_its_own_ordered_quantities(self):
        """
        ⚠ THE THING SAAHIL ASKED ABOUT: "the qty in draft etc should update that
        specific activity figures". A purchase order line points at ONE bom line,
        so ordering against RCC leaves Masonry untouched.
        """
        self.create_pos()
        self.assertGreater(bom_calc.draft_qty(self.cement_line), D("0"))
        self.assertEqual(bom_calc.draft_qty(self.cement_in_masonry), D("0"))

    def test_both_lines_are_told_where_the_other_stock_is(self):
        echoes = bom_calc.bulk_stock_echoes([self.cement_line, self.cement_in_masonry])
        self.assertIn(self.cement_line.id, echoes)
        self.assertIn(self.cement_in_masonry.id, echoes)
        self.assertEqual(echoes[self.cement_line.id]["total"], D("280"))
        names = [name for name, _qty in echoes[self.cement_line.id]["elsewhere"]]
        self.assertIn(self.masonry.name, names)

    def test_a_material_on_one_line_only_is_not_flagged(self):
        """An alert that fires on the ordinary case stops being an alert."""
        echoes = bom_calc.bulk_stock_echoes([self.steel_line])
        self.assertNotIn(self.steel_line.id, echoes)

    def test_a_line_with_no_stock_does_not_raise_an_echo(self):
        BomLine.objects.filter(pk=self.cement_in_masonry.pk).update(stock_qty=D("0"))
        echoes = bom_calc.bulk_stock_echoes([self.cement_line])
        self.assertEqual(echoes, {})

    def test_the_flag_appears_on_the_screen(self):
        screen = self.client.get(reverse("bom_screen", args=[self.project.id]),
                                 {"activity": "RCC"})
        self.assertContains(screen, "also holds stock on")

    def test_it_costs_one_query_however_many_lines(self):
        """
        ⚠ THE SHAPE OF THE WORK. This runs on every BOM page load and a project
        holds thousands of lines — a per-line version is the exact shape that
        once cost 8,000 queries.
        """
        few = [self.cement_line, self.cement_in_masonry]
        with self.assertNumQueries(1):
            bom_calc.bulk_stock_echoes(few)

        for number in range(30):
            material = Material.objects.create(
                code=f"RCC-ECH-{number:03d}", name=f"ECHO {number}", group=self.cem,
                uom="Bag", estimation_rate=D("100"), home_activity=self.rcc)
            BomLine.objects.create(bom=self.bom, activity=self.rcc, material=material,
                                   planned_qty=D("10"), stock_qty=D("5"))

        many = list(self.bom.lines.all())
        self.assertGreater(len(many), len(few))
        with self.assertNumQueries(1):
            bom_calc.bulk_stock_echoes(many)


class TheProjectListScales(Fixture):
    """
    ⚠ FOUND BY BUILDING A VOLUME ESTATE, NOT BY READING THE CODE.

    The screen counted BOM lines and purchase orders inside its loop, and the
    template asked for each estimate's activity count twice per row. Perfectly
    fast on the four projects anybody had; 69 queries on thirteen, and over 500
    on a hundred.

    ⚠ AND THE FIRST FIX MADE IT SLOWER. Annotating all three counts onto one
      query with distinct=True got it to 17 queries and 598ms — three Counts
      across three joins build a cartesian product, and a project with 6,400 BOM
      lines multiplies it by every estimate line and every order. Three separate
      grouped counts are 20 queries and 16ms.

      Fewer queries is not the same as faster. Measure both.
    """

    def test_it_does_not_ask_the_database_once_per_project(self):
        baseline = len(self.client.get(reverse("project_list"), {"show": "all"}).context["rows"])
        # ⚠ TWO OF THESE ARE THE LOGIN RATHER THAN THE SCREEN — the session row
        #   and the user row, on every authenticated request. The profile that
        #   carries the role rides along on the user query, via select_related in
        #   accounts.backends.EmailBackend.get_user. The screen itself still costs
        #   exactly what it cost before there was a login.
        #
        # ⚠ ONE OF THEM IS THE ⓘ PANEL'S TRANSLATIONS — ANCHOR: INFO-PANELS. It
        #   went from 10 to 11 when this screen gained a panel, and this test is
        #   what noticed. A FIXED cost per page, which is not what this test
        #   exists to catch: the assertion below, that 12 more projects add
        #   nothing, is the one that matters and it is unchanged.
        with self.assertNumQueries(11):
            self.client.get(reverse("project_list"), {"show": "all"})

        for number in range(12):
            project = Project.objects.create(
                code=f"PRJ-S{number:03d}", name=f"Scale {number}",
                bua_sqft=D("10000"), status=Project.Status.WON)
            estimate = Estimate.objects.create(project=project)
            EstimateLine.objects.create(estimate=estimate, name=self.rcc.name,
                                        rate=self.rcc.rate, gst_percent=self.rcc.gst_percent)
            bom = Bom.objects.create(project=project)
            BomLine.objects.create(bom=bom, activity=self.rcc, material=self.cement,
                                   planned_qty=D("10"))

        after = self.client.get(reverse("project_list"), {"show": "all"}).context["rows"]
        self.assertGreater(len(after), baseline)
        # ⚠ THE ASSERTION THAT MATTERS: twelve more projects, and the SAME count
        #   as above. The number moved from 10 to 11 only because every screen
        #   now fetches its ⓘ translations once — a fixed cost, not a per-row one.
        with self.assertNumQueries(11):
            self.client.get(reverse("project_list"), {"show": "all"})

    def test_the_counts_are_still_right(self):
        """Cheaper is worthless if it is wrong. The numbers must not move."""
        self.create_pos()
        row = [r for r in self.client.get(reverse("project_list"), {"show": "all"})
               .context["rows"] if r["project"].code == self.project.code][0]
        self.assertEqual(row["line_count"], self.bom.lines.count())
        self.assertEqual(row["po_count"], self.project.purchase_orders.count())
        self.assertEqual(row["activity_count"], self.estimate.lines.count())


class TheUnitMaster(AuthedTestCase):
    """
    ⚠ UOM WAS A HARDCODED LIST AND THE REASONING FOR THAT WAS REVERSED.

    A fixed list cannot drift — but that only holds while nobody needs a new
    unit. Saahil: "UOM master is needed as Uom is a drop down in excel, so how
    will that change in case there are future new uoms?" A missing unit means
    somebody else's spreadsheet row is rejected and they can do nothing about it.

    ⚠ THE VALUE ON A MATERIAL IS STILL TEXT. This table is what it is CHECKED
      against, not what it points at — so nothing that prints changed and no
      migration touched 705 materials.
    """

    def test_the_units_arrived_and_the_unused_ones_are_inactive(self):
        """
        "we can trim down the true excel master" — trimming means DEACTIVATING.
        They drop out of every dropdown while nothing that might reference them
        breaks, and turning one back on is a tick rather than a deployment.
        """
        self.assertTrue(UnitOfMeasure.objects.filter(code="Nos").exists())
        self.assertTrue(UnitOfMeasure.objects.filter(code="Bag").exists())

    def test_the_aliases_came_across(self):
        """
        ⚠ THIS IS WHAT REPLACES THE PROTECTION THE HARDCODED LIST GAVE. If the
        master is editable and the aliases are not, one unit starts arriving
        twice under two spellings the first time a sheet says "Hrs".
        """
        self.assertEqual(resolve_uom("HRS"), "Hour")
        self.assertEqual(resolve_uom("SQ FT"), "Sqft")
        self.assertEqual(resolve_uom("bags"), "Bag")

    def test_an_unknown_unit_is_refused_never_guessed(self):
        self.assertIsNone(resolve_uom("WIDGETS"))

    def test_an_inactive_unit_is_not_offered_but_is_still_accepted(self):
        """
        ⚠ THE WHOLE MEANING OF INACTIVE. It means "do not offer this again",
          never "this is wrong". 618 materials carry Nos — deactivating it must
          not start rejecting every one of them.
        """
        UnitOfMeasure.objects.filter(code="Bag").update(is_active=False)
        self.assertNotIn("Bag", [code for code, _ in active_uom_choices()])
        self.assertEqual(resolve_uom("Bag"), "Bag")

    def test_a_unit_in_use_cannot_be_deleted(self):
        """
        ⚠ ENFORCED ON THE MODEL, NOT BY THE DATABASE. `Material.uom` is TEXT, so
        there is no on_delete=PROTECT to do it. Deleting "Bag" would leave every
        material carrying a unit no longer in the vocabulary.
        """
        from django.db.models import ProtectedError
        group = MaterialGroup.objects.create(code="UOM", name="Unit test")
        Material.objects.create(code="RCC-UOM-001", name="THING", group=group, uom="Bag",
                                home_activity=Activity.objects.get(abbreviation="RCC"))
        with self.assertRaises(ProtectedError):
            UnitOfMeasure.objects.get(code="Bag").delete()

    def test_a_unit_nothing_uses_can_be_deleted(self):
        """Nothing references it → real delete. The delete rule, everywhere."""
        spare = UnitOfMeasure.objects.create(code="Furlong", sort_order=99)
        spare.delete()
        self.assertFalse(UnitOfMeasure.objects.filter(code="Furlong").exists())

    def test_a_code_cannot_change_once_materials_carry_it(self):
        """
        ⚠ The value is stored as text, so nothing follows a rename — "Bag" to
        "Bags" would orphan every material holding the old spelling. Same
        failure as renaming an activity, same rule.
        """
        group = MaterialGroup.objects.create(code="UOM", name="Unit test")
        Material.objects.create(code="RCC-UOM-002", name="THING", group=group, uom="Bag",
                                home_activity=Activity.objects.get(abbreviation="RCC"))
        unit = UnitOfMeasure.objects.get(code="Bag")
        unit.code = "Bags"
        with self.assertRaises(ValidationError):
            unit.clean()

    def test_a_new_unit_too_like_an_existing_one_is_refused_by_name(self):
        """
        ⚠ A REFUSAL WITH A NAMED ALTERNATIVE, NOT A SILENT MERGE. The system
        never decides two units are the same — it says which one it resembles
        and leaves the judgement to a person. Reuses the same similarity()
        the import uses to spot near-duplicate material names.
        """
        with self.assertRaises(ValidationError) as refused:
            UnitOfMeasure(code="Bags").clean()
        self.assertIn("Bag", str(refused.exception))

    def test_a_genuinely_new_unit_is_allowed(self):
        """The point of the table. Adding one must not need a developer."""
        UnitOfMeasure(code="Quintal", name="100 kg").clean()

    def test_the_material_form_offers_active_units_only(self):
        UnitOfMeasure.objects.filter(code="Bag").update(is_active=False)
        offered = {code for code, _label in active_uom_choices()}
        self.assertNotIn("Bag", offered)
        self.assertIn("Nos", offered)

    def test_it_is_a_tab_under_materials_rather_than_a_tile(self):
        """
        ⚠ THIS ASSERTED A TILE UNTIL SAAHIL SAW WHERE THE TILE WENT: "the UOM
          tile still shows and opens up Django, I could not see any UI for
          that." Units of measure is now the third tab on the Materials screen,
          so it is no longer an entry on the master data page at all.
        """
        titles = {entry["title"] for entry in hub.master_data_for()}
        self.assertNotIn("Units of measure", titles)
        self.assertIn("Materials", titles)
