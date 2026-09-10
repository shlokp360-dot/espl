"""
What the money on these pages has to keep meaning.

⚠ THE WORDS ARE THE FEATURE. Most of the tests below check a LABEL's meaning
  rather than a formula: that "spend" is only ever money paid, that a commitment
  counts on the approval date, that a draft counts nowhere. A page that adds the
  three stages together would still pass an arithmetic test and would be wrong
  in the way that costs money.
"""
import re
from datetime import date, timedelta
from decimal import Decimal as D

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from accounts.testing import AuthedTestCase
from analytics import budget, charts, money, periods
from masters.models import Activity, Material, MaterialGroup, Vendor
from projects.bom_models import Bom, BomLine, PurchaseOrder, PurchaseOrderLine
from projects.models import Estimate, EstimateLine, Project


class TheFiscalYearIsAprilToMarch(TestCase):
    """⚠ Not a preference. Every figure here is eventually read beside the CA's."""

    def test_april_starts_the_year_and_march_belongs_to_the_one_before(self):
        self.assertEqual(periods.fiscal_start(date(2026, 4, 1)), date(2026, 4, 1))
        self.assertEqual(periods.fiscal_start(date(2026, 8, 14)), date(2026, 4, 1))
        self.assertEqual(periods.fiscal_start(date(2027, 3, 31)), date(2026, 4, 1))
        self.assertEqual(periods.fiscal_label(date(2026, 4, 1)), "FY 2026-27")

    def test_ptd_runs_from_the_first_of_april_to_today(self):
        start, end, label, kind = periods.bounds(date(2026, 8, 14))
        self.assertEqual((start, end, kind), (date(2026, 4, 1), date(2026, 8, 14), "PTD"))
        self.assertIn("2026-27", label)

    def test_a_chosen_month_is_that_month_and_never_past_today(self):
        start, end, _label, kind = periods.bounds(date(2026, 8, 14), "2026-07")
        self.assertEqual((start, end, kind), (date(2026, 7, 1), date(2026, 7, 31), "CPD"))

        # The current month stops at today rather than promising a fortnight
        # that has not happened.
        start, end, _label, _kind = periods.bounds(date(2026, 8, 14), "2026-08")
        self.assertEqual((start, end), (date(2026, 8, 1), date(2026, 8, 14)))

    def test_a_month_outside_this_year_or_in_the_future_falls_back_to_ptd(self):
        for asked in ("2026-03", "2026-12", "rubbish", ""):
            _start, _end, _label, kind = periods.bounds(date(2026, 8, 14), asked)
            self.assertEqual(kind, "PTD", f"{asked!r} should not have been accepted")

    def test_only_months_that_have_begun_are_offered(self):
        keys = [key for key, _label in periods.months_so_far(date(2026, 8, 14))]
        self.assertEqual(keys, ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08"])


class MoneyCase(AuthedTestCase):
    """One project, one vendor, and documents at every stage."""

    def setUp(self):
        super().setUp()
        self.today = timezone.localdate()
        self.rcc = Activity.objects.get(abbreviation="RCC")
        self.project = Project.objects.create(
            name="Bhudarpura", bua_sqft=D("10000"), status=Project.Status.WON)
        estimate = Estimate.objects.create(project=self.project)
        EstimateLine.objects.create(estimate=estimate, name=self.rcc.name,
                                    rate=D("100"), gst_percent=D("18"))
        self.reserve = D("1000000")          # 100 x 10,000 sqft

        group = MaterialGroup.objects.create(code="CEM", name="Cement")
        self.material = Material.objects.create(
            code="RCC-CEM-001", name="CEMENT", group=group, uom="Bag",
            estimation_rate=D("400"), gst_percent=D("18"), home_activity=self.rcc)
        self.vendor = Vendor.objects.create(code="VEN-001", name="Sambhav Hardware",
                                            phone="9409124489", payment_terms="30 days")
        self.bom = Bom.objects.create(project=self.project)
        self.line = BomLine.objects.create(bom=self.bom, activity=self.rcc,
                                           material=self.material, planned_qty=D("100"),
                                           vendor=self.vendor, vendor_rate=D("400"))

    def order(self, status, qty=D("10"), rate=D("400"), approved=None, delivered=None, paid=None):
        """
        A document at a stage, with the dates that stage counts on.

        ⚠ THE NUMBER IS SET BY HAND HERE. `PurchaseOrder.objects.create()` does
          not assign one — that happens in `po_service`, which is the only route
          a real document takes. Two built directly both get "" and collide on
          the unique constraint, which is the constraint doing its job.
        """
        self.raised = getattr(self, "raised", 0) + 1
        order = PurchaseOrder.objects.create(
            number=f"PO-TEST-{self.raised:04d}",
            project=self.project, vendor=self.vendor, status=status,
            approved_at=approved, delivered_at=delivered, paid_at=paid)
        PurchaseOrderLine.objects.create(purchase_order=order, bom_line=self.line,
                                         quantity=qty, rate=rate, gst_percent=D("18"))
        return order

    def at(self, day):
        """A timezone-aware moment on a given date."""
        return timezone.make_aware(timezone.datetime.combine(day, timezone.datetime.min.time()))


class SpendMeansMoneyPaid(MoneyCase):
    """
    ⚠⚠ THE MOST IMPORTANT RULE IN THE MODULE, AND SAAHIL'S OWN CORRECTION.
      Committed, received and paid are three different questions. A page that
      calls the wrong one "spend" is worse than no page.
    """

    def test_an_approved_document_is_committed_and_is_not_spend(self):
        self.order(PurchaseOrder.Status.APPROVED, approved=self.at(self.today))
        start, end, _l, _k = periods.bounds(self.today)

        committed = money.add_up(money.documents("committed", start, end))
        paid = money.add_up(money.documents("paid", start, end))

        self.assertGreater(committed["taxable"], 0)
        self.assertEqual(paid["net_payable"], money.ZERO,
                         "an approved document was counted as money paid")

    def test_a_paid_document_is_still_committed(self):
        # ⚠ Otherwise a month's commitments would SHRINK as invoices were
        #   settled, which is the opposite of what commitment means.
        self.order(PurchaseOrder.Status.PAID, approved=self.at(self.today),
                   delivered=self.at(self.today), paid=self.at(self.today))
        start, end, _l, _k = periods.bounds(self.today)
        self.assertEqual(len(money.documents("committed", start, end)), 1)
        self.assertEqual(len(money.documents("paid", start, end)), 1)

    def test_a_draft_is_counted_nowhere(self):
        self.order(PurchaseOrder.Status.DRAFT)
        start, end, _l, _k = periods.bounds(self.today)
        for stage in ("committed", "received", "paid"):
            self.assertEqual(money.documents(stage, start, end), [],
                             f"a draft appeared in {stage}")

    def test_each_stage_counts_on_its_own_date(self):
        """The same document belongs to April's commitments and July's payments."""
        april, july = date(2026, 4, 10), date(2026, 7, 20)
        self.order(PurchaseOrder.Status.PAID, approved=self.at(april),
                   delivered=self.at(july), paid=self.at(july))

        in_april = periods.bounds(date(2026, 8, 14), "2026-04")
        in_july = periods.bounds(date(2026, 8, 14), "2026-07")

        self.assertEqual(len(money.documents("committed", in_april[0], in_april[1])), 1)
        self.assertEqual(money.documents("paid", in_april[0], in_april[1]), [])
        self.assertEqual(len(money.documents("paid", in_july[0], in_july[1])), 1)

    def test_the_ladder_matches_the_document_it_came_from(self):
        # ⚠ Document money comes from totals(), never re-derived. A page that
        #   disagrees with the PDF is worse than no page.
        order = self.order(PurchaseOrder.Status.PAID, approved=self.at(self.today),
                           delivered=self.at(self.today), paid=self.at(self.today))
        start, end, _l, _k = periods.bounds(self.today)
        summed = money.add_up(money.documents("paid", start, end))
        totals = order.totals()
        for key in money.LADDER:
            self.assertEqual(summed[key], totals[key], key)


class WhatIsOwed(MoneyCase):

    def test_outstanding_is_delivered_and_not_paid_at_any_date(self):
        # ⚠ An invoice from March unpaid in August is still owed in August.
        self.order(PurchaseOrder.Status.DELIVERED, delivered=self.at(date(2026, 3, 2)))
        self.assertEqual(len(money.outstanding()), 1)

    def test_a_paid_document_is_not_outstanding(self):
        self.order(PurchaseOrder.Status.PAID, approved=self.at(self.today),
                   delivered=self.at(self.today), paid=self.at(self.today))
        self.assertEqual(money.outstanding(), [])

    def test_terms_are_read_out_of_free_text(self):
        self.assertEqual(money.credit_days(self.vendor), (30, False))
        self.vendor.payment_terms = "45"
        self.assertEqual(money.credit_days(self.vendor), (45, False))

    def test_unreadable_terms_now_take_the_house_default(self):
        """
        ⚠ THIS TEST USED TO ASSERT THE OPPOSITE, AND THE CHANGE IS THE RECORD OF
          A DECISION BEING REVERSED.

        It read: "a vendor with no readable terms gets NO invented due date",
        because an assumed date can put a real invoice in the wrong bucket.
        Saahil's call on 14 Aug — "sure, have a default of 30 days" — and he is
        right for this business: 173 of 174 vendors have nothing in that field,
        so the old rule aged almost nothing and the page was useless.

        The old objection is answered rather than dropped: the assumption is
        FLAGGED on every row and COUNTED in every bucket. See
        ThirtyDaysIsTheHouseDefault.
        """
        self.vendor.payment_terms = "Advance against delivery"
        self.vendor.save()
        order = self.order(PurchaseOrder.Status.DELIVERED, delivered=self.at(self.today))
        self.assertEqual(money.credit_days(self.vendor), (30, True))
        self.assertIsNotNone(money.due_date(order))
        self.assertTrue(money.terms_assumed(order))

    def test_a_due_date_is_delivery_plus_the_terms(self):
        order = self.order(PurchaseOrder.Status.DELIVERED, delivered=self.at(date(2026, 7, 1)))
        self.assertEqual(money.due_date(order), date(2026, 7, 31))


class TheSettlementReconciles(MoneyCase):
    """
    ⚠ THE PAGE'S WHOLE CLAIM: settled + payable now + not yet payable is every
      rupee approved onward. Saahil asked for it in a sentence about books —
      "how much is to be paid and how much has been paid" — and a books figure
      whose parts do not add up is the first one an accountant stops trusting.
    """

    def setUp(self):
        super().setUp()
        moment = self.at(self.today)
        self.paid = self.order(PurchaseOrder.Status.PAID, qty=D("10"),
                               approved=moment, delivered=moment, paid=moment)
        self.owed = self.order(PurchaseOrder.Status.DELIVERED, qty=D("20"),
                               approved=moment, delivered=moment)
        self.coming = self.order(PurchaseOrder.Status.APPROVED, qty=D("30"), approved=moment)
        self.order(PurchaseOrder.Status.DRAFT, qty=D("99"))

    def test_the_three_buckets_add_back_to_the_obligation(self):
        split = money.settlement()
        parts = (split["settled"]["net_payable"]
                 + split["payable_now"]["net_payable"]
                 + split["not_yet_payable"]["net_payable"])
        self.assertEqual(parts, split["obligation"])

    def test_each_document_lands_in_exactly_one_bucket(self):
        split = money.settlement()
        self.assertEqual([o.pk for o in split["orders"]["settled"]], [self.paid.pk])
        self.assertEqual([o.pk for o in split["orders"]["payable_now"]], [self.owed.pk])
        self.assertEqual([o.pk for o in split["orders"]["not_yet_payable"]], [self.coming.pk])

    def test_a_draft_is_in_no_bucket_and_not_in_the_obligation(self):
        split = money.settlement()
        self.assertEqual(sum(len(rows) for rows in split["orders"].values()), 3)

    def test_what_vendors_invoice_exceeds_what_leaves_the_bank_by_the_tds(self):
        """⚠ TDS IS NAMED, NOT LOST. Otherwise: "why does this not match the ledger"."""
        for order in (self.paid, self.owed, self.coming):
            order.tds_pct = D("2")
            order.save()
        split = money.settlement()
        self.assertGreater(split["invoiced"], split["obligation"])
        self.assertEqual(split["tds"], split["invoiced"] - split["obligation"])

    def test_settlement_ignores_the_month_because_a_debt_does_not(self):
        # ⚠ An invoice from March unpaid in August is still unpaid in August.
        old = self.order(PurchaseOrder.Status.DELIVERED,
                         approved=self.at(date(2026, 3, 2)),
                         delivered=self.at(date(2026, 3, 5)))
        self.assertIn(old.pk, [o.pk for o in money.settlement()["orders"]["payable_now"]])

    def test_a_document_on_default_terms_is_aged_like_any_other_and_marked(self):
        # ⚠ There is no "terms unknown" bucket any more — see
        #   WhatIsOwed.test_unreadable_terms_now_take_the_house_default.
        self.vendor.payment_terms = "Advance"
        self.vendor.save()
        buckets = {row["key"]: row for row in money.ageing(money.outstanding(), self.today)}
        aged = [row for row in buckets.values() if row["orders"]]
        self.assertEqual(sum(len(row["orders"]) for row in aged), 1)
        self.assertEqual(sum(row["assumed"] for row in aged), 1)

    def test_ageing_counts_from_the_due_date_not_the_delivery_date(self):
        # 30-day terms, delivered 40 days ago → 10 days over, not 40.
        order = self.order(PurchaseOrder.Status.DELIVERED,
                           delivered=self.at(self.today - timedelta(days=40)))
        buckets = {row["key"]: row for row in money.ageing([order], self.today)}
        self.assertEqual(len(buckets["d30"]["orders"]), 1)

    def test_the_activity_split_adds_up_to_the_taxable_value(self):
        """
        ⚠ EX-GST AND NOTHING ELSE. A deduction and TDS belong to a document, not
          to a trade, so this is the only figure that can honestly be split.
        """
        rows = money.by_activity([self.paid])
        self.assertEqual(sum(row["value"] for row in rows), self.paid.totals()["taxable"])
        self.assertEqual([row["label"] for row in rows], [self.rcc.name])

    def test_the_screen_opens_and_says_what_is_owed(self):
        response = self.client.get(reverse("analytics_payments"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["split"]["payable_now"]["count"], 1)
        body = response.content.decode()
        for leak in ("{#", "#}", "{%", "%}"):
            self.assertNotIn(leak, body)

    def test_only_an_admin_can_open_it(self):
        person = self.make_user("pm.person", role=Role.PROJECT_MANAGER)
        self.client.force_login(person)
        self.assertEqual(self.client.get(reverse("analytics_payments")).status_code, 403)

    def test_indian_digit_grouping_on_chart_labels(self):
        # ⚠ 12,34,567 and not 1,234,567. It appears in plain SVG strings, where
        #   the template filter cannot reach.
        from analytics.views import intcomma_in
        self.assertEqual(intcomma_in(D("1234567")), "12,34,567")
        self.assertEqual(intcomma_in(D("999")), "999")
        self.assertEqual(intcomma_in(D("45000")), "45,000")


class TheWaterfallIsArithmeticFirst(TestCase):
    """
    ⚠ A WATERFALL THAT IS ONE STEP OUT LOOKS LIKE A PLAUSIBLE CHART. Nobody
      checks a picture against the ladder it came from, so the geometry is
      asserted as numbers and the SVG only turns those numbers into rectangles.
    """

    def steps(self):
        return charts.waterfall_steps([
            {"label": "Gross", "amount": 1000, "kind": "start"},
            {"label": "Discount", "amount": 100, "kind": "less"},
            {"label": "Taxable", "amount": 900, "kind": "total"},
            {"label": "GST", "amount": 162, "kind": "add"},
            {"label": "Invoice", "amount": 1062, "kind": "total"},
        ])[0]

    def test_a_step_down_hangs_from_the_running_balance(self):
        discount = self.steps()[1]
        self.assertEqual((discount["low"], discount["high"]), (900, 1000))
        self.assertEqual(discount["running"], 900)

    def test_a_step_up_sits_on_top_of_it(self):
        gst = self.steps()[3]
        self.assertEqual((gst["low"], gst["high"]), (900, 1062))
        self.assertEqual(gst["running"], 1062)

    def test_a_subtotal_is_drawn_from_zero_and_restates_the_balance(self):
        taxable = self.steps()[2]
        self.assertEqual((taxable["low"], taxable["high"]), (0, 900))
        self.assertEqual(taxable["running"], 900)

    def test_a_subtotal_is_never_added_to_the_running_balance(self):
        """⚠ THE CLASSIC WAY TO GET A WATERFALL WRONG — every subtotal doubles."""
        self.assertEqual(self.steps()[-1]["running"], 1062)

    def test_the_scale_is_the_tallest_bar(self):
        _steps, top = charts.waterfall_steps([
            {"label": "Gross", "amount": 500, "kind": "start"},
            {"label": "Less", "amount": 100, "kind": "less"}])
        self.assertEqual(top, 500)


class ABarMeansWhatTheNumberBesideItMeans(TestCase):
    """
    ⚠⚠ SAAHIL FOUND THIS ON SCREEN, AND IT IS THE WORST KIND OF FAULT: the chart
      rendered perfectly and said the opposite of its own labels. The bars were
      committed RUPEES ranked against the biggest trade; the figure printed
      beside each was that trade's PERCENTAGE of budget. The longest bar read
      1% and a short one read 39%.
    """

    def test_the_widest_bar_belongs_to_the_biggest_number(self):
        html = charts.hbars([
            {"label": "RCC", "value": 1, "display": "1%", "colour": "#000"},
            {"label": "Waterproofing", "value": 39, "display": "39%", "colour": "#000"},
        ], maximum=100)
        widths = [float(width) for width in re.findall(r"width:([\d.]+)%", html)]
        self.assertLess(widths[0], widths[1],
                        "the bar order does not follow the values")

    def test_a_fixed_maximum_stops_the_biggest_row_filling_the_track(self):
        """
        ⚠ Without it, three trades at 1%, 3% and 12% draw as short, medium and
          FULL — and 12% looks like the budget is gone.
        """
        html = charts.hbars([{"label": "A", "value": 12, "display": "12%", "colour": "#000"}],
                            maximum=100)
        self.assertIn("width:12.0000%", html)

    def test_without_a_maximum_it_still_ranks_against_the_biggest(self):
        html = charts.hbars([
            {"label": "A", "value": 50, "display": "Rs 50", "colour": "#000"},
            {"label": "B", "value": 100, "display": "Rs 100", "colour": "#000"},
        ])
        widths = [float(width) for width in re.findall(r"width:([\d.]+)%", html)]
        self.assertEqual(widths, [50.0, 100.0])


class TheLadderOnScreen(MoneyCase):

    def setUp(self):
        super().setUp()
        moment = self.at(self.today)
        self.doc = self.order(PurchaseOrder.Status.PAID, qty=D("100"),
                              approved=moment, delivered=moment, paid=moment)
        self.doc.deduction_pct = D("1")
        self.doc.tds_pct = D("2")
        self.doc.save()

    def test_every_rung_matches_the_document_it_came_from(self):
        # ⚠ A page that disagrees with the PDF is worse than no page.
        response = self.client.get(reverse("analytics_g2n") + "?stage=paid")
        ladder, totals = response.context["ladder"], self.doc.totals()
        for key in money.LADDER:
            self.assertEqual(ladder[key], totals[key], key)

    def test_the_ladder_actually_reconciles_step_by_step(self):
        totals = self.doc.totals()
        self.assertEqual(totals["taxable"], totals["gross"] - totals["discount"])
        self.assertEqual(totals["invoice_value"], totals["taxable"] + totals["gst"])
        self.assertEqual(totals["order_value"],
                         totals["invoice_value"] - totals["deduction"] + totals["round_off"])
        self.assertEqual(totals["net_payable"], totals["order_value"] - totals["tds"])

    def test_a_negative_round_off_steps_the_right_way(self):
        """Round off is the one rung that can go either way."""
        rows = self.client.get(reverse("analytics_g2n") + "?stage=paid").context["rows"]
        round_off = next(row for row in rows if row["key"] == "round_off")
        if round_off["raw"] < 0:
            self.assertEqual(round_off["kind"], "less")
            self.assertGreater(round_off["amount"], 0)

    def test_the_stage_changes_which_documents_are_counted(self):
        self.order(PurchaseOrder.Status.APPROVED, qty=D("5"), approved=self.at(self.today))
        paid = self.client.get(reverse("analytics_g2n") + "?stage=paid").context["count"]
        committed = self.client.get(reverse("analytics_g2n") + "?stage=committed").context["count"]
        self.assertEqual((paid, committed), (1, 2))


class TheDocumentsPageIsWhereDrillsLand(MoneyCase):

    def test_a_stage_drill_lands_on_exactly_those_documents(self):
        moment = self.at(self.today)
        paid = self.order(PurchaseOrder.Status.PAID, approved=moment, delivered=moment, paid=moment)
        self.order(PurchaseOrder.Status.APPROVED, approved=moment)

        rows = self.client.get(reverse("analytics_documents") + "?stage=paid").context["rows"]
        self.assertEqual([row["order"].pk for row in rows], [paid.pk])

    def test_the_footer_adds_up_the_rows_on_screen(self):
        # ⚠ If it does not match the figure that sent you here, the figure is
        #   wrong — which is the whole point of having a footer.
        moment = self.at(self.today)
        for _ in range(3):
            self.order(PurchaseOrder.Status.PAID, approved=moment, delivered=moment, paid=moment)
        response = self.client.get(reverse("analytics_documents") + "?stage=paid")
        rows, ladder = response.context["rows"], response.context["ladder"]
        self.assertEqual(ladder["net_payable"],
                         sum(row["totals"]["net_payable"] for row in rows))

    def test_owed_is_its_own_drill(self):
        self.order(PurchaseOrder.Status.DELIVERED, delivered=self.at(self.today))
        rows = self.client.get(reverse("analytics_documents") + "?status=owed").context["rows"]
        self.assertEqual(len(rows), 1)

    def test_a_draft_never_appears_under_a_stage_drill(self):
        self.order(PurchaseOrder.Status.DRAFT)
        for stage in ("committed", "received", "paid"):
            rows = self.client.get(
                f"{reverse('analytics_documents')}?stage={stage}").context["rows"]
            self.assertEqual(rows, [], stage)


class ThirtyDaysIsTheHouseDefault(MoneyCase):
    """
    ⚠ SAAHIL'S DECISION, AND IT OVERTURNED AN EARLIER ONE. 173 of 174 vendors
      have nothing typed in `payment_terms`, and a page that ages almost nothing
      is a page nobody opens. The assumption is applied AND counted.
    """

    def test_written_terms_win(self):
        self.assertEqual(money.credit_days(self.vendor), (30, False))
        self.vendor.payment_terms = "45 days"
        self.assertEqual(money.credit_days(self.vendor), (45, False))

    def test_blank_or_unreadable_terms_take_the_default_and_say_so(self):
        for terms in ("", "Advance against delivery", None):
            self.vendor.payment_terms = terms
            days, assumed = money.credit_days(self.vendor)
            self.assertEqual(days, money.DEFAULT_CREDIT_DAYS)
            self.assertTrue(assumed, f"{terms!r} was not flagged as assumed")

    def test_every_delivered_document_now_has_a_due_date(self):
        self.vendor.payment_terms = "Advance"
        self.vendor.save()
        order = self.order(PurchaseOrder.Status.DELIVERED, delivered=self.at(date(2026, 7, 1)))
        self.assertEqual(money.due_date(order), date(2026, 7, 31))
        self.assertTrue(money.terms_assumed(order))

    def test_the_ageing_buckets_count_how_many_were_assumed(self):
        self.vendor.payment_terms = ""
        self.vendor.save()
        order = self.order(PurchaseOrder.Status.DELIVERED,
                           delivered=self.at(self.today - timedelta(days=40)))
        buckets = {row["key"]: row for row in money.ageing([order], self.today)}
        self.assertEqual(buckets["d30"]["assumed"], 1)

    def test_days_to_pay_is_measured_from_approval(self):
        # ⚠ It measures US. From delivery it would blend our behaviour with the
        #   vendor's, and the point is to know which of the two is slow.
        self.order(PurchaseOrder.Status.PAID,
                   approved=self.at(date(2026, 6, 1)),
                   delivered=self.at(date(2026, 6, 5)),
                   paid=self.at(date(2026, 6, 21)))
        average, count = money.days_to_pay(money.documents(
            "paid", date(2026, 6, 1), date(2026, 6, 30)))
        self.assertEqual((average, count), (20, 1))


class BudgetAgainstPlanAgainstActual(MoneyCase):
    """
    ⚠ THREE COLUMNS BECAUSE THERE ARE TWO GAPS. Budget minus plan is an
      estimating gap; plan minus committed is a buying gap. They are not the
      same person's problem, and one "variance" column would hide which
      happened.
    """

    def test_the_three_columns_come_from_three_different_places(self):
        self.order(PurchaseOrder.Status.APPROVED, qty=D("50"), approved=self.at(self.today))
        row = budget.by_trade(self.project)[0]

        self.assertEqual(row["label"], self.rcc.name)
        self.assertEqual(row["budget"], self.reserve)                 # BOQ rate × area
        self.assertEqual(row["plan"], D("40000.00"))                  # 100 bags × Rs 400
        self.assertEqual(row["committed"], D("20000.00"))             # 50 bags × Rs 400
        self.assertEqual(row["left"], self.reserve - D("20000.00"))

    def test_a_trade_quoted_but_not_planned_still_appears(self):
        """Otherwise the total would not add up, which is worse than an odd row."""
        other = Activity.objects.exclude(pk=self.rcc.pk).first()
        EstimateLine.objects.create(estimate=self.project.estimate, name=other.name,
                                    rate=D("50"), gst_percent=D("18"))
        rows = {row["label"]: row for row in budget.by_trade(self.project)}
        self.assertIn(other.name, rows)
        self.assertEqual(rows[other.name]["plan"], money.ZERO)
        self.assertEqual(rows[other.name]["lines"], 0)

    def test_overspending_is_a_flag_and_the_figure_stays_true(self):
        # ⚠ A red number, never a red banner — the standing rule for this system.
        self.project.estimate.lines.update(rate=D("1"))               # budget = Rs 10,000
        self.order(PurchaseOrder.Status.APPROVED, qty=D("50"), approved=self.at(self.today))
        row = budget.by_trade(self.project)[0]
        self.assertTrue(row["over"])
        self.assertLess(row["left"], 0)
        self.assertEqual(row["used_pct"], 200)

    def test_rows_are_projects_until_a_project_is_chosen(self):
        """
        ⚠ THIS ASSERTED "trade" UNTIL SAAHIL RENAMED THE WORD ON SCREEN. The
          rewrite is the record: `grain` is BOTH the comparison the template
          switches on AND the phrase printed in the toolbar, so changing the
          visible word without changing this one left the heading reading
          "Project" on a page grouped by construction activity — perfectly
          rendered, and the opposite of itself. One string, deliberately.
        """
        response = self.client.get(reverse("analytics_budget"))
        self.assertEqual(response.context["grain"], "project")
        response = self.client.get(f"{reverse('analytics_budget')}?project={self.project.pk}")
        self.assertEqual(response.context["grain"], "construction activity")

    def test_the_heading_matches_the_grain_it_is_grouped_by(self):
        """The bug this pair exists to catch — the label and the grouping agreeing."""
        response = self.client.get(f"{reverse('analytics_budget')}?project={self.project.pk}")
        self.assertContains(response, "<th>Construction activity</th>", html=False)

    def test_the_footer_is_the_rows_added_and_never_re_queried(self):
        self.order(PurchaseOrder.Status.APPROVED, qty=D("50"), approved=self.at(self.today))
        rows = budget.by_trade(self.project)
        footer = budget.total(rows)
        self.assertEqual(footer["budget"], sum(row["budget"] for row in rows))
        self.assertEqual(footer["committed"], sum(row["committed"] for row in rows))

    def test_adding_trades_does_not_add_queries(self):
        """⚠ The cost is per PROJECT, not per trade — figures_for asks in bulk."""
        with CaptureQueriesContext(connection) as small:
            self.client.get(f"{reverse('analytics_budget')}?project={self.project.pk}")

        group = MaterialGroup.objects.get(code="CEM")
        for activity in Activity.objects.exclude(pk=self.rcc.pk)[:4]:
            material = Material.objects.create(
                code=f"{activity.abbreviation}-CEM-900", name=f"{activity.abbreviation} THING",
                group=group, uom="Bag", estimation_rate=D("100"), gst_percent=D("18"),
                home_activity=activity)
            BomLine.objects.create(bom=self.bom, activity=activity, material=material,
                                   planned_qty=D("10"), vendor=self.vendor, vendor_rate=D("100"))
        with CaptureQueriesContext(connection) as large:
            self.client.get(f"{reverse('analytics_budget')}?project={self.project.pk}")

        self.assertEqual(len(large), len(small),
                         "the budget page costs a query per trade")


class TheBuyingAndWorkPages(MoneyCase):

    def test_buying_opens_on_one_project_and_ranks_materials_by_committed(self):
        self.order(PurchaseOrder.Status.APPROVED, qty=D("50"), approved=self.at(self.today))
        response = self.client.get(f"{reverse('analytics_bom')}?project={self.project.pk}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["code"] for row in response.context["materials"]],
                         ["RCC-CEM-001"])

    def test_work_counts_progress_and_both_kinds_of_lost_day(self):
        from tasks.models import Subtask, TaskHeader
        header = TaskHeader.objects.create(project=self.project, activity=self.rcc,
                                           name="Earthing", start=date(2026, 4, 1), days=10)
        Subtask.objects.create(header=header, title="Done late", start=date(2026, 4, 1), days=2,
                               status=Subtask.Status.DONE, finished_on=date(2026, 4, 5))
        Subtask.objects.create(header=header, title="Replanned", start=date(2026, 4, 10), days=2,
                               original_start=date(2026, 4, 1), original_days=2)
        Subtask.objects.create(header=header, title="Open", start=date(2026, 4, 20), days=2)

        response = self.client.get(f"{reverse('analytics_tasks')}?project={self.project.pk}")
        row = response.context["rows"][0]
        self.assertEqual(row["label"], self.rcc.name)
        self.assertEqual(row["done"], 1)
        self.assertEqual(row["total"], 3)
        self.assertEqual(row["progress"], 33)
        self.assertEqual(row["late"], 3)          # finished 5 Apr, due 2 Apr
        self.assertEqual(row["shifted"], 9)       # moved from 2 Apr to 11 Apr
        self.assertEqual(response.context["days_lost"], 12)

    def test_work_draws_the_same_chart_as_the_site_screen(self):
        # ⚠ Two drawings of one schedule would eventually disagree.
        from tasks.models import TaskHeader
        TaskHeader.objects.create(project=self.project, activity=self.rcc, name="Earthing",
                                  start=date(2026, 4, 1), days=10)
        response = self.client.get(f"{reverse('analytics_tasks')}?project={self.project.pk}")
        self.assertEqual(response.context["chart_data"]["span"]["start"], date(2026, 4, 1))

    def test_no_money_appears_on_the_work_page(self):
        """
        ⚠ SAAHIL'S INSTRUCTION: "task is different and bom is different… no need
          to combine them in a screen for the head over here." A subtask names no
          material and no order, so a rupee figure against a delay is invented.
        """
        self.order(PurchaseOrder.Status.PAID, approved=self.at(self.today),
                   delivered=self.at(self.today), paid=self.at(self.today))
        response = self.client.get(f"{reverse('analytics_tasks')}?project={self.project.pk}")

        # ⚠ CHECKED IN THE CONTEXT, NOT IN THE HTML. The tab strip links to the
        #   Budget page, so the WORD appears on the screen; what must not appear
        #   is a money FIGURE, and the context is where that would have to come
        #   from.
        forbidden = {"paid", "committed", "owed", "split", "total", "materials"}
        self.assertEqual(forbidden & set(response.context.keys()), set(),
                         "money reached the work page")

    def test_every_analytics_page_opens_and_leaks_nothing(self):
        self.order(PurchaseOrder.Status.PAID, approved=self.at(self.today),
                   delivered=self.at(self.today), paid=self.at(self.today))
        for name in ("analytics_home", "analytics_budget", "analytics_bom",
                     "analytics_payments", "analytics_tasks"):
            body = self.client.get(reverse(name)).content.decode()
            for leak in ("{#", "#}", "{%", "%}"):
                self.assertNotIn(leak, body, f"{name} printed raw template syntax")

    def test_every_page_is_the_admins_alone(self):
        person = self.make_user("pm.person", role=Role.PROJECT_MANAGER)
        self.client.force_login(person)
        for name in ("analytics_home", "analytics_budget", "analytics_bom",
                     "analytics_payments", "analytics_tasks"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)

    def test_the_filters_survive_moving_between_tabs(self):
        # ⚠ The tab strip carries the query string; otherwise the module is five
        #   unrelated screens.
        response = self.client.get(
            f"{reverse('analytics_home')}?project={self.project.pk}&month=2026-04")
        body = response.content.decode()
        self.assertIn(f"project={self.project.pk}", body)
        self.assertIn("month=2026-04", body)


class TheOverviewScreen(MoneyCase):

    def test_only_an_admin_can_open_it(self):
        for role in (Role.PROJECT_MANAGER, Role.PURCHASE, Role.ACCOUNTANT,
                     Role.SITE, Role.COMPLIANCE):
            person = self.make_user(f"{role}.person", role=role)
            self.client.force_login(person)
            self.assertEqual(self.client.get(reverse("analytics_home")).status_code, 403,
                             f"{role} opened analytics")

    def test_it_opens_with_no_documents_at_all(self):
        # A fresh installation is a real state, not an error.
        self.assertEqual(self.client.get(reverse("analytics_home")).status_code, 200)

    def test_reserve_consumed_compares_ex_gst_with_ex_gst(self):
        """
        ⚠ MIXING THE TWO ONCE REPORTED AN ACTIVITY AT 99.3% OF BUDGET WHEN THE
          TRUTH WAS 84.2%. The reserve is a pre-GST number because the BOQ adds
          GST once at the very end.
        """
        # 250 bags x Rs 400 = Rs 100,000 ex-GST against a Rs 1,000,000 reserve.
        self.order(PurchaseOrder.Status.APPROVED, qty=D("250"),
                   approved=self.at(self.today))
        response = self.client.get(reverse("analytics_home"))
        self.assertEqual(response.context["reserve"], self.reserve)
        self.assertEqual(response.context["reserve_pct"], 10)

    def test_the_page_does_not_query_once_per_document(self):
        """
        ⚠ `totals()` FIRES A QUERY PER DOCUMENT WITHOUT `prefetch_related`.
          420 documents today, 4,200 at ten times the size. A fixed budget would
          go stale; what matters is that the count does not GROW.
        """
        for _ in range(2):
            self.order(PurchaseOrder.Status.PAID, approved=self.at(self.today),
                       delivered=self.at(self.today), paid=self.at(self.today))
        with CaptureQueriesContext(connection) as small:
            self.client.get(reverse("analytics_home"))

        for _ in range(10):
            self.order(PurchaseOrder.Status.PAID, approved=self.at(self.today),
                       delivered=self.at(self.today), paid=self.at(self.today))
        with CaptureQueriesContext(connection) as large:
            self.client.get(reverse("analytics_home"))

        self.assertEqual(len(large), len(small),
                         "analytics costs a query per document — prefetch has been lost")

    def test_the_launchpad_tile_is_live_for_the_admin_only(self):
        tiles = {tile["key"] for tile in self.client.get(reverse("launchpad")).context["tiles"]}
        self.assertIn("analytics", tiles)

        engineer = self.make_user("site.person", role=Role.SITE)
        self.client.force_login(engineer)
        seen = {tile["key"] for tile in self.client.get(reverse("launchpad")).context["tiles"]}
        self.assertNotIn("analytics", seen)

    def test_the_screen_does_not_leak_template_syntax(self):
        self.order(PurchaseOrder.Status.PAID, approved=self.at(self.today),
                   delivered=self.at(self.today), paid=self.at(self.today))
        body = self.client.get(reverse("analytics_home")).content.decode()
        for leak in ("{#", "#}", "{%", "%}"):
            self.assertNotIn(leak, body, f"analytics printed raw template syntax: {leak}")
