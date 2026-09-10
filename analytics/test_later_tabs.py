"""
The four later analytics tabs: cost to complete, rates, vendors, sales velocity.

⚠ EACH SCREEN REUSES A CALCULATOR THAT ALREADY EXISTS, and the tests below
  assert the reuse: a forecast is the Budget tab's three figures added, a rate
  is the line's own `taxable` over its quantity, price-vs-plan uses
  `bom_calc.planning_rate`, and a sales rupee is `sales.calc`'s.

⚠ EVERY LIST IS BULK-FETCHED. The query-shape tests compare 3 rows with 23
  and allow fewer than ten extra queries — the shape that once cost 8,000
  queries on the BOM screen is the one being kept out.
"""
from datetime import date, timedelta
from decimal import Decimal as D

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from accounts.models import Role
from analytics import budget, charts, rates, vendors, velocity
from analytics.tests import MoneyCase
from masters.models import Activity, Material, MaterialGroup, Vendor
from projects.bom_calc import planning_rate
from projects.bom_models import BomLine, PurchaseOrder, PurchaseOrderLine
from projects.models import Project
from sales import services
from sales.models import Booking, Enquiry, Unit, UnitKind

FOUR = ("analytics_cost_to_complete", "analytics_rates", "analytics_vendors", "analytics_sales")


def _extra(small, large):
    return len(large) - len(small)


class CostToComplete(MoneyCase):

    def test_forecast_is_committed_plus_what_is_still_planned(self):
        # plan 100 x 400 = 40,000; committed 10 x 400 = 4,000; budget 10,00,000
        self.order(PurchaseOrder.Status.APPROVED, approved=self.at(self.today))
        rows = budget.with_forecast(budget.by_trade(self.project))
        row = next(r for r in rows if r["label"] == self.rcc.name)
        self.assertEqual(row["committed"], D("4000.00"))
        self.assertEqual(row["remaining_plan"], D("36000.00"))
        self.assertEqual(row["forecast"], D("40000.00"))
        self.assertEqual(row["variance"], self.reserve - D("40000.00"))

    def test_remaining_plan_is_floored_at_zero(self):
        """Bought above plan: the forecast is what was committed, no negative remainder."""
        self.order(PurchaseOrder.Status.APPROVED, qty=D("250"), approved=self.at(self.today))
        row = budget.with_forecast(budget.by_trade(self.project))[0]
        self.assertEqual(row["committed"], D("100000.00"))
        self.assertEqual(row["remaining_plan"], D("0.00"))
        self.assertEqual(row["forecast"], D("100000.00"))

    def test_the_footer_is_the_rows_added(self):
        self.order(PurchaseOrder.Status.APPROVED, qty=D("250"), approved=self.at(self.today))
        rows = budget.with_forecast(budget.by_trade(self.project))
        total = budget.forecast_total(rows)
        self.assertEqual(total["forecast"], sum((r["forecast"] for r in rows), D("0")))
        self.assertEqual(total["variance"], total["budget"] - total["forecast"])

    def test_the_screen_opens_by_project_then_by_activity(self):
        response = self.client.get(reverse("analytics_cost_to_complete"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["grain"], "project")
        response = self.client.get(
            f"{reverse('analytics_cost_to_complete')}?project={self.project.pk}")
        self.assertEqual(response.context["grain"], "construction activity")
        self.assertIn("forecast = committed + what is still planned",
                      response.content.decode())

    def test_the_paired_bars_share_one_scale(self):
        html = charts.hbars_paired([
            {"label": "A", "values": [100, 50], "displays": ["100", "50"]},
            {"label": "B", "values": [25, 200], "displays": ["25", "200"]},
        ], [{"label": "Budget", "colour": "#000"}, {"label": "Forecast", "colour": "#111"}])
        self.assertIn("width:50.0000%", html)
        self.assertIn("width:100.0000%", html)
        self.assertIn("width:12.5000%", html)

    def test_more_activities_do_not_add_queries(self):
        with CaptureQueriesContext(connection) as small:
            self.client.get(f"{reverse('analytics_cost_to_complete')}?project={self.project.pk}")
        group = MaterialGroup.objects.get(code="CEM")
        for index, activity in enumerate(Activity.objects.exclude(pk=self.rcc.pk)[:20]):
            material = Material.objects.create(
                code=f"ZQ-{index:03d}", name=f"ZQ THING {index}", group=group, uom="Bag",
                estimation_rate=D("100"), gst_percent=D("18"), home_activity=activity)
            BomLine.objects.create(bom=self.bom, activity=activity, material=material,
                                   planned_qty=D("10"), vendor=self.vendor, vendor_rate=D("100"))
        with CaptureQueriesContext(connection) as large:
            self.client.get(f"{reverse('analytics_cost_to_complete')}?project={self.project.pk}")
        self.assertLess(_extra(small, large), 10)


class RateTrends(MoneyCase):

    def test_the_rate_is_the_frozen_line_rate_after_discount(self):
        first = self.order(PurchaseOrder.Status.APPROVED, rate=D("400"),
                           approved=self.at(self.today - timedelta(days=30)))
        second = self.order(PurchaseOrder.Status.APPROVED, rate=D("500"),
                            approved=self.at(self.today))
        line = second.lines.get()
        line.discount_pct = D("10")
        line.save()
        rows = rates.trend(rates.lines())
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["first"], D("400.00"))
        self.assertEqual(row["latest"], D("450.00"))            # 500 less 10%
        self.assertEqual(row["latest"], (line.taxable / line.quantity).quantize(D("0.01")))
        self.assertEqual(row["low"], D("400.00"))
        self.assertEqual(row["average"], D("425.00"))
        self.assertEqual(row["change_pct"], D("12.5"))
        self.assertEqual([p["number"] for p in row["points"]], [first.number, second.number])

    def test_a_draft_is_not_a_price(self):
        self.order(PurchaseOrder.Status.DRAFT, rate=D("900"))
        self.assertEqual(rates.trend(rates.lines()), [])

    def test_the_top_fifteen_by_committed_value(self):
        group = MaterialGroup.objects.get(code="CEM")
        for index in range(17):
            material = Material.objects.create(
                code=f"ZQ-R{index:03d}", name=f"ZQ MAT {index}", group=group, uom="Bag",
                estimation_rate=D("100"), gst_percent=D("18"), home_activity=self.rcc)
            line = BomLine.objects.create(bom=self.bom, activity=self.rcc, material=material,
                                          planned_qty=D("10"), vendor=self.vendor, vendor_rate=D("100"))
            order = PurchaseOrder.objects.create(
                number=f"PO-ZQR-{index:04d}", project=self.project, vendor=self.vendor,
                status=PurchaseOrder.Status.APPROVED, approved_at=self.at(self.today))
            PurchaseOrderLine.objects.create(purchase_order=order, bom_line=line,
                                             quantity=D(index + 1), rate=D("100"), gst_percent=D("18"))
        rows = rates.trend(rates.lines())
        self.assertEqual(len(rows), 15)
        self.assertEqual(rows[0]["code"], "ZQ-R016")
        self.assertNotIn("ZQ-R000", [r["code"] for r in rows])

    def test_the_group_filter_narrows_before_ranking(self):
        other = MaterialGroup.objects.create(code="ZQG", name="ZQ Group")
        material = Material.objects.create(
            code="ZQ-G001", name="ZQ OTHER", group=other, uom="Bag",
            estimation_rate=D("100"), gst_percent=D("18"), home_activity=self.rcc)
        line = BomLine.objects.create(bom=self.bom, activity=self.rcc, material=material,
                                      planned_qty=D("10"), vendor=self.vendor, vendor_rate=D("100"))
        self.order(PurchaseOrder.Status.APPROVED, approved=self.at(self.today))
        order = PurchaseOrder.objects.create(
            number="PO-ZQG-0001", project=self.project, vendor=self.vendor,
            status=PurchaseOrder.Status.APPROVED, approved_at=self.at(self.today))
        PurchaseOrderLine.objects.create(purchase_order=order, bom_line=line,
                                         quantity=D("1"), rate=D("100"), gst_percent=D("18"))
        every = rates.lines()
        self.assertEqual([name for _pk, name in rates.groups_in(every)], ["Cement", "ZQ Group"])
        self.assertEqual([r["code"] for r in rates.trend(every, other.pk)], ["ZQ-G001"])
        response = self.client.get(f"{reverse('analytics_rates')}?group={other.pk}")
        self.assertEqual([r["code"] for r in response.context["rows"]], ["ZQ-G001"])

    def test_a_sparkline_is_drawn_from_two_points_and_not_one(self):
        self.assertEqual(charts.sparkline([D("400")]), "")
        self.assertIn("<polyline", charts.sparkline([D("400"), D("450")]))

    def test_more_orders_do_not_add_queries(self):
        for _ in range(3):
            self.order(PurchaseOrder.Status.APPROVED, approved=self.at(self.today))
        with CaptureQueriesContext(connection) as small:
            self.client.get(reverse("analytics_rates"))
        for _ in range(20):
            self.order(PurchaseOrder.Status.APPROVED, approved=self.at(self.today))
        with CaptureQueriesContext(connection) as large:
            self.client.get(reverse("analytics_rates"))
        self.assertLess(_extra(small, large), 10)


class VendorPerformance(MoneyCase):

    def test_price_against_plan_uses_the_planning_rate(self):
        # planned at 400 (the material's estimation rate); bought at 440.
        self.order(PurchaseOrder.Status.APPROVED, rate=D("440"), approved=self.at(self.today))
        row = vendors.scorecard(PurchaseOrder.objects.exclude(status="draft"))[0]
        self.assertEqual(row["plan"], D("10") * planning_rate(self.line))
        self.assertEqual(row["actual"], D("4400.00"))
        self.assertEqual(row["price_pct"], D("10.0"))
        self.assertEqual(row["committed"], D("4400.00"))

    def test_paid_and_days_to_pay_come_from_the_paid_documents(self):
        self.order(PurchaseOrder.Status.PAID, approved=self.at(self.today - timedelta(days=20)),
                   delivered=self.at(self.today - timedelta(days=10)), paid=self.at(self.today))
        self.order(PurchaseOrder.Status.APPROVED, approved=self.at(self.today))
        row = vendors.scorecard(PurchaseOrder.objects.exclude(status="draft"))[0]
        self.assertEqual(row["documents"], 2)
        self.assertEqual(row["days_to_pay"], 20)
        self.assertEqual(row["paid_count"], 1)
        self.assertGreater(row["paid"], D("0"))

    def test_lateness_counts_from_required_by_and_a_missing_date_is_counted(self):
        late = self.order(PurchaseOrder.Status.DELIVERED, approved=self.at(self.today - timedelta(days=9)),
                          delivered=self.at(self.today))
        late.required_by = self.today - timedelta(days=3)
        late.save()
        self.order(PurchaseOrder.Status.DELIVERED, approved=self.at(self.today - timedelta(days=9)),
                   delivered=self.at(self.today))                     # no required_by
        row = vendors.scorecard(PurchaseOrder.objects.exclude(status="draft"))[0]
        self.assertEqual(row["late_days"], 3)
        self.assertEqual(row["late_count"], 1)
        self.assertEqual(row["no_due_date"], 1)
        response = self.client.get(reverse("analytics_vendors"))
        self.assertEqual(response.context["no_due_date"], 1)
        self.assertIn("No due dates set", response.content.decode())

    def test_sorting_is_by_a_whitelisted_key_through_the_address(self):
        other = Vendor.objects.create(code="ZQV-002", name="ZQ Second", phone="9409124488")
        self.order(PurchaseOrder.Status.APPROVED, qty=D("50"), approved=self.at(self.today))
        order = PurchaseOrder.objects.create(
            number="PO-ZQV-0001", project=self.project, vendor=other,
            status=PurchaseOrder.Status.APPROVED, approved_at=self.at(self.today))
        PurchaseOrderLine.objects.create(purchase_order=order, bom_line=self.line,
                                         quantity=D("1"), rate=D("400"), gst_percent=D("18"))
        names = lambda query: [r["name"] for r in self.client.get(
            f"{reverse('analytics_vendors')}{query}").context["rows"]]
        self.assertEqual(names(""), ["Sambhav Hardware", "ZQ Second"])          # committed desc
        self.assertEqual(names("?sort=committed&dir=asc"), ["ZQ Second", "Sambhav Hardware"])
        self.assertEqual(names("?sort=vendor"), ["Sambhav Hardware", "ZQ Second"])
        self.assertEqual(names("?sort=rubbish&dir=sideways"), ["Sambhav Hardware", "ZQ Second"])

    def test_a_vendor_with_no_figure_sorts_last_either_way(self):
        rows = [{"name": "a", "late_days": None}, {"name": "b", "late_days": 2},
                {"name": "c", "late_days": 5}]
        self.assertEqual([r["name"] for r in vendors.sort(rows, "late_days", "desc")], ["c", "b", "a"])
        self.assertEqual([r["name"] for r in vendors.sort(rows, "late_days", "asc")], ["b", "c", "a"])

    def test_more_vendors_do_not_add_queries(self):
        def vendor_orders(count, start):
            for index in range(start, start + count):
                vendor = Vendor.objects.create(code=f"ZQV-{index:03d}", name=f"ZQ Vendor {index}",
                                               phone=f"94091{index:05d}")
                order = PurchaseOrder.objects.create(
                    number=f"PO-ZQV-{index:04d}", project=self.project, vendor=vendor,
                    status=PurchaseOrder.Status.PAID, approved_at=self.at(self.today),
                    delivered_at=self.at(self.today), paid_at=self.at(self.today))
                PurchaseOrderLine.objects.create(purchase_order=order, bom_line=self.line,
                                                 quantity=D("1"), rate=D("400"), gst_percent=D("18"))
        vendor_orders(3, 100)
        with CaptureQueriesContext(connection) as small:
            self.client.get(reverse("analytics_vendors"))
        vendor_orders(20, 200)
        with CaptureQueriesContext(connection) as large:
            self.client.get(reverse("analytics_vendors"))
        self.assertLess(_extra(small, large), 10)


class SalesVelocity(MoneyCase):

    def setUp(self):
        super().setUp()
        self.units = [
            Unit.objects.create(project=self.project, number=f"ZQ-{n}", block="ZQ", floor=1,
                                kind=UnitKind.TWO_BHK, carpet_sqft=D("900"),
                                saleable_sqft=D("1150"), base_price=D("4800000"))
            for n in range(1, 5)]

    def book(self, unit, days_ago, phone, enquiry=None):
        return services.book_unit(unit, phone=phone, name=f"ZQ {phone}", agreement_value=D("5000000"),
                                  booked_on=self.today - timedelta(days=days_ago),
                                  enquiry=enquiry, by=self.user)

    def test_bookings_are_counted_by_month_and_cancelled_ones_are_not(self):
        self.book(self.units[0], 0, "9800000001")
        cancelled = self.book(self.units[1], 0, "9800000002")
        cancelled.status = Booking.Status.CANCELLED
        cancelled.save()
        response = self.client.get(reverse("analytics_sales"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["bookings"], 1)
        self.assertEqual(response.context["units"]["booked"], 1)
        self.assertEqual(response.context["units"]["available"], 3)

    def test_days_to_book_only_where_the_enquiry_is_linked(self):
        enquiry = Enquiry.objects.create(project=self.project, name="ZQ Asker", phone="9800000003")
        Enquiry.objects.filter(pk=enquiry.pk).update(
            created_at=self.at(self.today - timedelta(days=12)))
        enquiry.refresh_from_db()
        self.book(self.units[0], 2, "9800000003", enquiry=enquiry)
        self.book(self.units[1], 0, "9800000004")
        bookings = list(Booking.objects.select_related("enquiry"))
        self.assertEqual(velocity.days_to_book(bookings), (10, 1))

    def test_demands_and_collections_are_sales_calc_figures(self):
        from sales import calc
        booking = self.book(self.units[0], 5, "9800000005")
        milestone = booking.milestones.get(sequence=1)
        demand = services.raise_demand(booking, milestone, due_on=self.today,
                                       raised_on=self.today, by=self.user)
        receipt = services.record_receipt(booking, amount=D("100000"), demand=demand,
                                          tds_amount=D("1000"), received_on=self.today, by=self.user)
        response = self.client.get(reverse("analytics_sales"))
        self.assertEqual(response.context["demanded"], calc.demand_total(demand))
        self.assertEqual(response.context["collected"], calc.receipt_credit(receipt))
        self.assertEqual(response.context["collected"], D("101000.00"))

    def test_the_project_filter_narrows_every_figure(self):
        other = Project.objects.create(name="ZQ Other", bua_sqft=D("5000"), status=Project.Status.WON)
        Unit.objects.create(project=other, number="ZQ-O1", block="O", floor=1, kind=UnitKind.TWO_BHK,
                            carpet_sqft=D("900"), saleable_sqft=D("1150"), base_price=D("4800000"))
        self.book(self.units[0], 1, "9800000006")
        response = self.client.get(f"{reverse('analytics_sales')}?project={other.pk}")
        self.assertEqual(response.context["bookings"], 0)
        self.assertEqual([r["project"] for r in response.context["unit_rows"]], [other])

    def test_sales_view_opens_it_and_the_rest_of_the_module_stays_closed(self):
        for role in (Role.PROJECT_MANAGER, Role.ACCOUNTANT):
            self.client.force_login(self.make_user(f"{role}.person", role=role))
            body = self.client.get(reverse("analytics_sales"))
            self.assertEqual(body.status_code, 200, role)
            html = body.content.decode()
            self.assertIn("Sales velocity", html)
            self.assertNotIn(f'href="{reverse("analytics_home")}?', html)
            self.assertNotIn(reverse("analytics_rates"), html)
            self.assertEqual(self.client.get(reverse("analytics_home")).status_code, 403)
        self.client.force_login(self.make_user("site.person", role=Role.SITE))
        self.assertEqual(self.client.get(reverse("analytics_sales")).status_code, 403)

    def test_more_bookings_do_not_add_queries(self):
        for index in range(3):
            unit = Unit.objects.create(project=self.project, number=f"ZQ-S{index}", block="S", floor=1,
                                       kind=UnitKind.TWO_BHK, carpet_sqft=D("900"),
                                       saleable_sqft=D("1150"), base_price=D("4800000"))
            booking = self.book(unit, 1, f"98100{index:05d}")
            services.raise_demand(booking, booking.milestones.get(sequence=1), due_on=self.today,
                                  raised_on=self.today, by=self.user)
            services.record_receipt(booking, amount=D("1000"), received_on=self.today, by=self.user)
        with CaptureQueriesContext(connection) as small:
            self.client.get(reverse("analytics_sales"))
        for index in range(20):
            unit = Unit.objects.create(project=self.project, number=f"ZQ-T{index}", block="T", floor=1,
                                       kind=UnitKind.TWO_BHK, carpet_sqft=D("900"),
                                       saleable_sqft=D("1150"), base_price=D("4800000"))
            booking = self.book(unit, 1, f"98200{index:05d}")
            services.raise_demand(booking, booking.milestones.get(sequence=1), due_on=self.today,
                                  raised_on=self.today, by=self.user)
            services.record_receipt(booking, amount=D("1000"), received_on=self.today, by=self.user)
        with CaptureQueriesContext(connection) as large:
            self.client.get(reverse("analytics_sales"))
        self.assertLess(_extra(small, large), 10)


class TheFourTabs(MoneyCase):

    def test_every_tab_opens_and_leaks_nothing(self):
        self.order(PurchaseOrder.Status.PAID, approved=self.at(self.today),
                   delivered=self.at(self.today), paid=self.at(self.today))
        for name in FOUR:
            body = self.client.get(reverse(name))
            self.assertEqual(body.status_code, 200, name)
            for leak in ("{#", "#}", "{%", "%}"):
                self.assertNotIn(leak, body.content.decode(), f"{name} printed raw template syntax")

    def test_every_tab_is_in_the_strip_for_the_admin(self):
        html = self.client.get(reverse("analytics_home")).content.decode()
        for name in FOUR:
            self.assertIn(reverse(name), html)

    def test_no_grey_helper_text_and_no_small_type_on_the_analytics_screens(self):
        """The restyle's rule: explanations live in the ⓘ panel, not under a chart."""
        import glob
        for path in glob.glob("templates/analytics/*.html"):
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
            for banned in ('class="legend"', 'class="hint"', "font-size:11", "font-size:12px",
                           "font-size:10"):
                self.assertNotIn(banned, text, f"{path} carries {banned}")


class TheOverviewLayout(MoneyCase):

    def test_the_donut_key_truncates_names_and_keeps_the_figure_whole(self):
        self.order(PurchaseOrder.Status.PAID, approved=self.at(self.today),
                   delivered=self.at(self.today), paid=self.at(self.today))
        html = self.client.get(reverse("analytics_home")).content.decode()
        self.assertIn('class="chart2"', html)
        self.assertIn(f'<span class="k" title="{self.rcc.name}">', html)
        self.assertNotIn("Still to come", html)
        self.assertNotIn("counted nowhere", html)

    def test_the_month_chart_fills_its_card(self):
        html = charts.bars([{"label": "Apr", "values": [1, 2]}],
                           [{"label": "A", "colour": "#000"}, {"label": "B", "colour": "#111"}])
        self.assertIn("width:100%;height:auto", html)
        self.assertNotIn('height="200"', html)
        self.assertIn(">A<", html)          # the key is inside the drawing
