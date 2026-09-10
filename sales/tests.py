"""
Sales: the money ladders, the one-live-booking rule, the derived statuses,
who may press what, and the screens rendering with data.

Fixtures use ZQ-prefixed values so they cannot collide with other apps'.
"""
import sys
import types
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal as D
from unittest.mock import MagicMock

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse

from accounts.models import Role
from accounts.testing import AuthedTestCase
from masters.models import Activity
from projects.models import Project
from sales import calc, services
from sales.models import (
    Booking, BookingEvent, Customer, CustomerReceipt, Demand, Enquiry, PaymentMilestone,
    SiteVisit, Unit, UnitKind,
)
from sales.services import SalesError
from tasks.models import Subtask, TaskHeader


@contextmanager
def stubbed_weasyprint():
    """A fake module in sys.modules — the same trick as projects/test_boq_pdf.py."""
    fake = types.ModuleType("weasyprint")
    fake.HTML = MagicMock()
    fake.HTML.return_value.write_pdf.return_value = b"%PDF-1.7 fake"
    had = sys.modules.get("weasyprint")
    sys.modules["weasyprint"] = fake
    try:
        yield fake
    finally:
        if had is None:
            sys.modules.pop("weasyprint", None)
        else:
            sys.modules["weasyprint"] = had


class Fixture(AuthedTestCase):
    """One Won project, four units, one customer. Bookings are made per test."""

    def setUp(self):
        super().setUp()
        self.project = Project.objects.create(
            code="PRJ-ZQS1", name="ZQ Sales Towers", bua_sqft=D("20000"),
            status=Project.Status.WON)
        self.units = [
            Unit.objects.create(project=self.project, number=f"ZQ-{floor}0{pos}", block="ZQ",
                                floor=floor, kind=UnitKind.TWO_BHK, carpet_sqft=D("900"),
                                saleable_sqft=D("1150"), base_price=D("4800000"))
            for floor in (1, 2) for pos in (1, 2)
        ]
        self.unit = self.units[0]
        self.customer = Customer.objects.create(name="ZQ Ramesh Patel", phone="9800000001")
        self.rcc = Activity.objects.get(abbreviation="RCC")
        self.today = date(2026, 9, 10)

    def book(self, unit=None, value=D("5000000"), gst=D("5"), phone="9800000001",
             name="ZQ Ramesh Patel", **kw):
        return services.book_unit(unit or self.unit, phone=phone, name=name,
                                  agreement_value=value, gst_percent=gst,
                                  booked_on=self.today - timedelta(days=60), by=self.user, **kw)

    def header(self, name="ZQ 3rd slab", done=True):
        header = TaskHeader.objects.create(project=self.project, activity=self.rcc, name=name,
                                           start=date(2026, 8, 1), days=10, created_by=self.user)
        Subtask.objects.create(header=header, title="pour", start=date(2026, 8, 1), days=3,
                               status=Subtask.Status.DONE if done else Subtask.Status.OPEN)
        return header


# =========================================================== the arithmetic
class MoneyLadders(Fixture):

    def test_milestone_amounts_of_the_default_schedule_add_back_to_the_agreement_value(self):
        booking = self.book(value=D("5000000"))
        amounts = [calc.milestone_amount(booking.agreement_value, m.percent)
                   for m in booking.milestones.all()]
        self.assertEqual(sum(amounts), D("5000000.00"))
        self.assertEqual(calc.schedule_total_percent(booking.milestones.all()), D("100.00"))

    def test_default_schedule_sums_to_100(self):
        self.assertEqual(calc.schedule_total_percent(calc.DEFAULT_SCHEDULE), D("100.00"))
        self.assertEqual(len(calc.DEFAULT_SCHEDULE), 8)

    def test_booking_gst_and_total(self):
        booking = self.book(value=D("5000000"), gst=D("5"))
        self.assertEqual(calc.booking_gst(booking), D("250000.00"))
        self.assertEqual(calc.booking_total(booking), D("5250000.00"))

    def test_affordable_housing_at_one_percent(self):
        booking = self.book(value=D("3000000"), gst=D("1"))
        self.assertEqual(calc.booking_total(booking), D("3030000.00"))

    def test_demand_gst_and_total_are_frozen_from_the_booking(self):
        booking = self.book(value=D("5000000"), gst=D("5"))
        milestone = booking.milestones.get(sequence=1)
        demand = services.raise_demand(booking, milestone, due_on=self.today, raised_on=self.today,
                                       by=self.user)
        self.assertEqual(demand.amount, D("500000.00"))
        self.assertEqual(demand.gst_percent, D("5"))
        self.assertEqual(calc.demand_gst(demand), D("25000.00"))
        self.assertEqual(calc.demand_total(demand), D("525000.00"))
        # Change the booking's GST afterwards: the letter does not move.
        booking.gst_percent = D("12")
        booking.save()
        demand.refresh_from_db()
        self.assertEqual(calc.demand_total(demand), D("525000.00"))

    def test_rounding_is_half_up_to_the_paisa(self):
        self.assertEqual(calc.milestone_amount(D("1000"), D("33.333")), D("333.33"))
        self.assertEqual(calc.milestone_amount(D("1"), D("12.5")), D("0.13"))   # 0.125 rounds up
        self.assertEqual(calc.gst_on(D("0.05"), D("5")), D("0.00"))              # 0.0025 rounds down
        self.assertEqual(calc.gst_on(D("0.10"), D("5")), D("0.01"))              # 0.005 rounds up

    def test_collected_outstanding_and_due(self):
        booking = self.book(value=D("5000000"))
        m1, m2 = booking.milestones.get(sequence=1), booking.milestones.get(sequence=2)
        d1 = services.raise_demand(booking, m1, due_on=self.today - timedelta(days=40),
                                   raised_on=self.today - timedelta(days=55), by=self.user)
        services.raise_demand(booking, m2, due_on=self.today + timedelta(days=10),
                              raised_on=self.today, by=self.user)
        services.record_receipt(booking, amount=D("300000"), demand=d1,
                                received_on=self.today - timedelta(days=30), by=self.user)
        self.assertEqual(calc.collected(booking), D("300000.00"))
        self.assertEqual(calc.demanded(booking), D("1050000.00"))
        self.assertEqual(calc.outstanding(booking), D("4950000.00"))
        self.assertEqual(calc.due_balance(booking), D("750000.00"))
        # Only d1 is past due: 525,000 − 300,000.
        self.assertEqual(calc.overdue(booking, self.today), D("225000.00"))

    def test_tds_is_credited_to_the_customer(self):
        booking = self.book(value=D("6000000"))
        receipt = services.record_receipt(booking, amount=D("99000"), tds_amount=D("1000"),
                                          received_on=self.today, by=self.user)
        self.assertEqual(calc.receipt_credit(receipt), D("100000.00"))
        self.assertEqual(calc.collected(booking), D("100000.00"))

    def test_suggested_tds_only_above_fifty_lakh(self):
        small = self.book(value=D("4500000"))
        self.assertEqual(calc.suggested_tds(small), D("0"))
        big = self.book(unit=self.units[1], value=D("6000000"), phone="9800000002", name="ZQ B")
        self.assertEqual(calc.suggested_tds(big), D("60000.00"))
        self.assertEqual(calc.suggested_tds(big, D("500000")), D("5000.00"))

    def test_refund_on_cancel_is_collected_less_deduction_capped_at_collected(self):
        booking = self.book(value=D("5000000"))
        services.record_receipt(booking, amount=D("200000"), received_on=self.today, by=self.user)
        deduction, refund = calc.refund_on_cancel(booking, D("2"))
        self.assertEqual((deduction, refund), (D("100000.00"), D("100000.00")))
        deduction, refund = calc.refund_on_cancel(booking, D("10"))   # 500,000 > collected
        self.assertEqual((deduction, refund), (D("200000.00"), D("0.00")))

    def test_bulk_figures_agree_with_the_single_functions(self):
        a = self.book(value=D("5000000"))
        b = self.book(unit=self.units[1], value=D("4000000"), phone="9800000002", name="ZQ B")
        m = a.milestones.get(sequence=1)
        services.raise_demand(a, m, due_on=self.today - timedelta(days=5),
                              raised_on=self.today - timedelta(days=20), by=self.user)
        services.record_receipt(a, amount=D("100000"), received_on=self.today, by=self.user)
        figures = calc.bulk_booking_figures([a, b], self.today)
        self.assertEqual(figures[a.id]["collected"], calc.collected(a))
        self.assertEqual(figures[a.id]["outstanding"], calc.outstanding(a))
        self.assertEqual(figures[a.id]["overdue"], calc.overdue(a, self.today))
        self.assertEqual(figures[a.id]["total"], calc.booking_total(a))
        self.assertEqual(figures[b.id]["collected"], D("0"))
        self.assertEqual(figures[b.id]["outstanding"], D("4200000.00"))


class DemandStatusIsDerived(Fixture):

    def setUp(self):
        super().setUp()
        self.booking = self.book(value=D("5000000"))
        m1, m2 = self.booking.milestones.get(sequence=1), self.booking.milestones.get(sequence=2)
        self.d1 = services.raise_demand(self.booking, m1, due_on=self.today - timedelta(days=30),
                                        raised_on=self.today - timedelta(days=45), by=self.user)
        self.d2 = services.raise_demand(self.booking, m2, due_on=self.today - timedelta(days=1),
                                        raised_on=self.today - timedelta(days=16), by=self.user)

    def figures(self):
        return calc.bulk_demand_figures([self.d1, self.d2])

    def test_open_then_part_paid_then_paid(self):
        self.assertEqual(self.figures()[self.d1.id]["status"], "open")
        services.record_receipt(self.booking, amount=D("25000"), demand=self.d1,
                                received_on=self.today, by=self.user)
        self.assertEqual(self.figures()[self.d1.id]["status"], "part_paid")
        self.assertEqual(self.figures()[self.d1.id]["balance"], D("500000.00"))
        services.record_receipt(self.booking, amount=D("500000"), demand=self.d1,
                                received_on=self.today, by=self.user)
        self.assertEqual(self.figures()[self.d1.id]["status"], "paid")
        self.assertEqual(self.figures()[self.d1.id]["balance"], D("0.00"))

    def test_an_on_account_receipt_pays_the_oldest_demand_first(self):
        services.record_receipt(self.booking, amount=D("600000"), received_on=self.today, by=self.user)
        figures = self.figures()
        self.assertEqual(figures[self.d1.id]["status"], "paid")
        self.assertEqual(figures[self.d2.id]["status"], "part_paid")
        self.assertEqual(figures[self.d2.id]["paid"], D("75000.00"))

    def test_an_advance_beyond_every_demand_shows_on_the_ledger(self):
        services.record_receipt(self.booking, amount=D("2000000"), received_on=self.today, by=self.user)
        rows = calc.ledger(self.booking, [self.d1, self.d2], list(self.booking.receipts.all()))
        self.assertEqual(rows[-1]["balance"], D("-950000.00"))
        self.assertTrue(rows[-1]["advance"])
        self.assertEqual(rows[-1]["balance_shown"], D("950000.00"))

    def test_the_ledger_runs_in_date_order_with_a_running_balance(self):
        services.record_receipt(self.booking, amount=D("100000"), demand=self.d1,
                                received_on=self.today - timedelta(days=20), by=self.user)
        rows = calc.ledger(self.booking, [self.d1, self.d2], list(self.booking.receipts.all()))
        self.assertEqual([r["kind"] for r in rows], ["demand", "receipt", "demand"])
        self.assertEqual([r["balance"] for r in rows],
                         [D("525000.00"), D("425000.00"), D("950000.00")])

    def test_ageing_buckets(self):
        t = self.today
        self.assertEqual(calc.ageing_bucket(t + timedelta(days=1), t), "not_due")
        self.assertEqual(calc.ageing_bucket(t, t), "0_30")
        self.assertEqual(calc.ageing_bucket(t - timedelta(days=30), t), "0_30")
        self.assertEqual(calc.ageing_bucket(t - timedelta(days=31), t), "31_60")
        self.assertEqual(calc.ageing_bucket(t - timedelta(days=90), t), "61_90")
        self.assertEqual(calc.ageing_bucket(t - timedelta(days=91), t), "90_plus")


class UnitStatusIsDerived(Fixture):

    def test_available_booked_registered_cancelled(self):
        self.assertEqual(self.unit.status, "available")
        booking = self.book()
        self.assertEqual(self.unit.status, "booked")
        services.mark_registered(booking, by=self.user)
        self.assertEqual(self.unit.status, "registered")
        other = self.units[1]
        b2 = self.book(unit=other, phone="9800000002", name="ZQ Two")
        services.cancel_booking(b2, reason="changed mind", by=self.user)
        self.assertEqual(other.status, "cancelled")
        self.assertTrue(calc.is_bookable(other.status))
        self.assertFalse(calc.is_bookable("booked"))

    def test_bulk_status_matches_the_property(self):
        self.book()
        bulk = calc.bulk_unit_status(self.units)
        self.assertEqual(bulk[self.unit.id], "booked")
        self.assertEqual(bulk[self.units[1].id], "available")


# ============================================================== the rules
class OneLiveBookingPerUnit(Fixture):

    def test_the_service_refuses_a_second_live_booking(self):
        self.book()
        with self.assertRaises(SalesError) as caught:
            self.book(phone="9800000002", name="ZQ Other")
        self.assertIn("already has a live booking", str(caught.exception))
        self.assertEqual(Booking.objects.filter(unit=self.unit).count(), 1)

    def test_clean_refuses_too(self):
        first = self.book()
        second = Booking(unit=self.unit, customer=self.customer, booked_on=self.today,
                         agreement_value=D("1"))
        with self.assertRaises(ValidationError):
            second.clean()
        # A cancelled second one is fine.
        second.status = Booking.Status.CANCELLED
        second.clean()
        self.assertEqual(first.unit_id, self.unit.id)

    def test_the_database_holds_the_rule_under_a_race(self):
        self.book()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Booking.objects.create(unit=self.unit, customer=self.customer,
                                       booked_on=self.today, agreement_value=D("1"))

    def test_a_cancelled_booking_frees_the_unit(self):
        first = self.book()
        services.cancel_booking(first, reason="loan refused", by=self.user)
        second = self.book(phone="9800000002", name="ZQ Next")
        self.assertNotEqual(first.number, second.number)
        self.assertEqual(self.unit.status, "booked")


class ScheduleRules(Fixture):

    def test_a_schedule_that_does_not_total_100_is_refused_with_the_total(self):
        rows = [{"name": "a", "percent": "50"}, {"name": "b", "percent": "45"}]
        with self.assertRaises(SalesError) as caught:
            self.book(schedule=rows)
        self.assertIn("95", str(caught.exception))
        self.assertEqual(Booking.objects.count(), 0)
        self.assertEqual(Customer.objects.filter(phone="9800000001").count(), 1)

    def test_an_empty_schedule_is_refused(self):
        with self.assertRaises(SalesError):
            self.book(schedule=[])

    def test_rewriting_keeps_a_demanded_milestone(self):
        booking = self.book()
        m1 = booking.milestones.get(sequence=1)
        services.raise_demand(booking, m1, due_on=self.today, raised_on=self.today, by=self.user)
        rows = [{"name": "renamed", "percent": "10"}, {"name": "rest", "percent": "90"}]
        services.write_schedule(booking, rows, by=self.user)
        m1.refresh_from_db()
        self.assertEqual(m1.name, "On booking")            # the letter is out
        self.assertEqual(booking.milestones.count(), 2)
        with self.assertRaises(SalesError):
            services.write_schedule(booking, [{"name": "only", "percent": "100"}], by=self.user)


class Numbers(Fixture):

    def test_documents_are_numbered_from_series(self):
        booking = self.book()
        self.assertRegex(booking.number, r"^BK-\d{6}$")
        demand = services.raise_demand(booking, booking.milestones.get(sequence=1),
                                       due_on=self.today, raised_on=self.today, by=self.user)
        self.assertRegex(demand.number, r"^DL-\d{6}$")
        receipt = services.record_receipt(booking, amount=D("1"), received_on=self.today, by=self.user)
        self.assertRegex(receipt.number, r"^RC-\d{6}$")

    def test_customer_phone_is_unique_and_digits_only(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Customer.objects.create(name="ZQ Dup", phone="9800000001")
        bad = Customer(name="ZQ Bad", phone="98-0000")
        with self.assertRaises(ValidationError):
            bad.full_clean()

    def test_pan_is_uppercased_and_validated(self):
        customer = Customer.objects.create(name="ZQ Pan", phone="9800000009", pan="abcde1234f")
        self.assertEqual(customer.pan, "ABCDE1234F")
        with self.assertRaises(ValidationError):
            Customer(name="ZQ Pan2", phone="9800000010", pan="ABC123").full_clean()


# ============================================================ the services
class BookingService(Fixture):

    def test_book_unit_creates_the_customer_schedule_event_and_marks_the_enquiry(self):
        enquiry = Enquiry.objects.create(project=self.project, name="ZQ New", phone="9800000077")
        booking = self.book(phone="9800000077", name="ZQ New Person", enquiry=enquiry)
        self.assertEqual(booking.customer.name, "ZQ New Person")
        self.assertEqual(booking.milestones.count(), 8)
        self.assertEqual(booking.events.filter(kind=BookingEvent.Kind.BOOKED).count(), 1)
        enquiry.refresh_from_db()
        self.assertEqual(enquiry.stage, Enquiry.Stage.BOOKED)

    def test_an_existing_phone_reuses_the_customer_and_does_not_rename(self):
        booking = self.book(phone="9800000001", name="Somebody Else")
        self.assertEqual(booking.customer_id, self.customer.id)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.name, "ZQ Ramesh Patel")

    def test_a_new_phone_without_a_name_is_refused(self):
        with self.assertRaises(SalesError):
            self.book(phone="9800000099", name="")

    def test_refusals(self):
        with self.assertRaises(SalesError):
            self.book(value=D("0"))
        self.unit.is_active = False
        self.unit.save()
        with self.assertRaises(SalesError):
            self.book()

    def test_cancel_refuses_registered_and_records_refund(self):
        booking = self.book()
        services.record_receipt(booking, amount=D("500000"), received_on=self.today, by=self.user)
        services.mark_registered(booking, by=self.user)
        with self.assertRaises(SalesError):
            services.cancel_booking(booking, reason="x", by=self.user)
        other = self.book(unit=self.units[1], phone="9800000002", name="ZQ Two")
        services.record_receipt(other, amount=D("500000"), received_on=self.today, by=self.user)
        services.cancel_booking(other, reason="loan refused", deduction_pct=D("2"), by=self.user)
        other.refresh_from_db()
        self.assertEqual(other.status, Booking.Status.CANCELLED)
        self.assertEqual(other.refund_amount, D("400000.00"))
        self.assertTrue(other.events.filter(kind=BookingEvent.Kind.CANCELLED).exists())
        with self.assertRaises(SalesError):
            services.record_receipt(other, amount=D("1"), received_on=self.today, by=self.user)
        with self.assertRaises(SalesError):
            services.raise_demand(other, other.milestones.first(), due_on=self.today, by=self.user)

    def test_status_ladder(self):
        booking = self.book()
        services.mark_agreement(booking, on=self.today, by=self.user)
        self.assertEqual(booking.status, Booking.Status.AGREEMENT)
        with self.assertRaises(SalesError):
            services.mark_agreement(booking, by=self.user)
        services.mark_registered(booking, on=self.today, by=self.user)
        self.assertEqual(booking.status, Booking.Status.REGISTERED)
        with self.assertRaises(SalesError):
            services.mark_registered(booking, by=self.user)

    def test_transfer_records_the_old_customer_and_an_event(self):
        booking = self.book()
        new = Customer.objects.create(name="ZQ Buyer Two", phone="9800000002")
        services.transfer_booking(booking, new, note="resale", by=self.user)
        booking.refresh_from_db()
        self.assertEqual(booking.customer_id, new.id)
        self.assertEqual(booking.transferred_from_id, self.customer.id)
        event = booking.events.get(kind=BookingEvent.Kind.TRANSFERRED)
        self.assertIn("ZQ Ramesh Patel", event.detail)
        self.assertIn("ZQ Buyer Two", event.detail)
        with self.assertRaises(SalesError):
            services.transfer_booking(booking, new, by=self.user)


class DemandService(Fixture):

    def test_one_letter_per_milestone(self):
        booking = self.book()
        m1 = booking.milestones.get(sequence=1)
        services.raise_demand(booking, m1, due_on=self.today, raised_on=self.today, by=self.user)
        with self.assertRaises(SalesError):
            services.raise_demand(booking, m1, due_on=self.today, raised_on=self.today, by=self.user)

    def test_due_before_raised_is_refused(self):
        booking = self.book()
        with self.assertRaises(SalesError):
            services.raise_demand(booking, booking.milestones.first(),
                                  due_on=self.today - timedelta(days=1), raised_on=self.today)

    def test_an_ad_hoc_demand(self):
        booking = self.book()
        demand = services.raise_demand(booking, amount=D("12345.678"), due_on=self.today,
                                       raised_on=self.today, note="parking", by=self.user)
        self.assertIsNone(demand.milestone)
        self.assertEqual(demand.amount, D("12345.68"))

    def test_raise_demands_for_a_finished_header_across_bookings(self):
        header = self.header(done=True)
        schedule = [{"name": "booking", "percent": "50"},
                    {"name": "slab", "percent": "50", "task_header": header}]
        a = self.book(schedule=schedule)
        b = self.book(unit=self.units[1], phone="9800000002", name="ZQ B", schedule=schedule)
        c = self.book(unit=self.units[2], phone="9800000003", name="ZQ C")   # not linked
        raised = services.raise_demands_for_milestone(self.project, header, by=self.user)
        self.assertEqual({d.booking_id for d in raised}, {a.id, b.id})
        self.assertEqual(Demand.objects.filter(booking=c).count(), 0)
        # Safe to run twice.
        self.assertEqual(services.raise_demands_for_milestone(self.project, header, by=self.user), [])

    def test_an_unfinished_header_is_refused(self):
        header = self.header(done=False)
        self.book(schedule=[{"name": "slab", "percent": "100", "task_header": header}])
        with self.assertRaises(SalesError):
            services.raise_demands_for_milestone(self.project, header, by=self.user)


# ============================================================= the screens
class ScreensFixture(Fixture):

    def setUp(self):
        super().setUp()
        self.booking = self.book(value=D("5000000"))
        m1, m2 = self.booking.milestones.get(sequence=1), self.booking.milestones.get(sequence=2)
        self.d1 = services.raise_demand(self.booking, m1, due_on=self.today - timedelta(days=40),
                                        raised_on=self.today - timedelta(days=55), by=self.user)
        self.d2 = services.raise_demand(self.booking, m2, due_on=self.today + timedelta(days=10),
                                        raised_on=self.today, by=self.user)
        self.receipt = services.record_receipt(
            self.booking, amount=D("300000"), demand=self.d1, reference="ZQUTR1",
            received_on=self.today - timedelta(days=30), by=self.user)
        self.enquiry = Enquiry.objects.create(project=self.project, name="ZQ Asker",
                                              phone="9800000055", broker_name="ZQ Broker")


class ScreensRender(ScreensFixture):

    def test_home(self):
        response = self.client.get(reverse("sales_home"))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("ZQ Sales Towers", html)
        self.assertIn("50,00,000", html)          # agreement value booked
        self.assertIn("3,00,000", html)           # collected
        self.assertIn("49,50,000", html)          # outstanding
        self.assertIn("2,25,000", html)           # overdue

    def test_units_grid(self):
        response = self.client.get(reverse("sales_units"), {"project": self.project.pk})
        html = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn("ZQ-101", html)
        self.assertIn("Booked", html)
        self.assertIn("ZQ Ramesh Patel", html)
        self.assertIn(reverse("sales_booking_new", args=[self.units[1].pk]), html)
        self.assertNotIn(reverse("sales_booking_new", args=[self.unit.pk]), html)

    def test_units_grid_ignores_a_bad_project_id(self):
        self.assertEqual(self.client.get(reverse("sales_units"), {"project": "x'1"}).status_code, 200)

    def test_unit_form_new_and_edit(self):
        response = self.client.post(reverse("sales_unit_new"), {
            "project": self.project.pk, "number": "ZQ-901", "block": "ZQ", "floor": "9",
            "kind": "3bhk", "carpet_sqft": "1200", "saleable_sqft": "1500", "base_price": "7000000"})
        self.assertEqual(response.status_code, 302)
        unit = Unit.objects.get(project=self.project, number="ZQ-901")
        self.assertEqual(unit.base_price, D("7000000"))
        response = self.client.post(reverse("sales_unit_form", args=[unit.pk]), {
            "number": "ZQ-901", "block": "ZQ", "floor": "9", "kind": "3bhk", "carpet_sqft": "1200",
            "saleable_sqft": "1500", "base_price": "7100000", "is_active": "no"})
        self.assertEqual(response.status_code, 302)
        unit.refresh_from_db()
        self.assertFalse(unit.is_active)
        # A duplicate number is refused.
        response = self.client.post(reverse("sales_unit_new"), {
            "project": self.project.pk, "number": "ZQ-101", "floor": "1", "kind": "2bhk"})
        self.assertEqual(Unit.objects.filter(number="ZQ-101").count(), 1)

    def test_bulk_units(self):
        response = self.client.post(reverse("sales_units_bulk"), {
            "project": self.project.pk, "block": "B", "floor_from": "1", "floor_to": "7",
            "per_floor": "4", "kind": "2bhk", "carpet_sqft": "900", "saleable_sqft": "1100",
            "base_price": "4500000"})
        self.assertEqual(response.status_code, 302)
        numbers = set(Unit.objects.filter(project=self.project, block="B").values_list("number", flat=True))
        self.assertEqual(len(numbers), 28)
        self.assertIn("B-101", numbers)
        self.assertIn("B-704", numbers)
        # Running it again adds nothing and does not fail.
        self.client.post(reverse("sales_units_bulk"), {
            "project": self.project.pk, "block": "B", "floor_from": "1", "floor_to": "7",
            "per_floor": "4", "kind": "2bhk"})
        self.assertEqual(Unit.objects.filter(project=self.project, block="B").count(), 28)

    def test_enquiries_list_and_filters(self):
        response = self.client.get(reverse("sales_enquiries"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("ZQ Asker", response.content.decode())
        response = self.client.get(reverse("sales_enquiries"), {"q": "ZQ Broker", "stage": "open"})
        self.assertIn("ZQ Asker", response.content.decode())
        response = self.client.get(reverse("sales_enquiries"), {"stage": "lost"})
        self.assertNotIn("ZQ Asker", response.content.decode())

    def test_enquiry_form_visit_and_stage(self):
        response = self.client.post(reverse("sales_enquiry_new"), {
            "project": self.project.pk, "name": "ZQ Walker", "phone": "9800000066",
            "source": "walkin", "interested_in": "2bhk", "budget": "4800000"})
        self.assertEqual(response.status_code, 302)
        enquiry = Enquiry.objects.get(phone="9800000066")
        self.assertEqual(self.client.get(reverse("sales_enquiry_form", args=[enquiry.pk])).status_code, 200)
        self.client.post(reverse("sales_enquiry_visit", args=[enquiry.pk]),
                         {"visited_on": "2026-09-01", "note": "liked it"})
        enquiry.refresh_from_db()
        self.assertEqual(enquiry.stage, Enquiry.Stage.VISITED)
        self.assertEqual(SiteVisit.objects.filter(enquiry=enquiry).count(), 1)
        self.client.post(reverse("sales_enquiry_stage", args=[enquiry.pk]), {"stage": "lost"})
        enquiry.refresh_from_db()
        self.assertEqual(enquiry.stage, Enquiry.Stage.VISITED)     # no reason: refused
        self.client.post(reverse("sales_enquiry_stage", args=[enquiry.pk]),
                         {"stage": "lost", "lost_reason": "too dear"})
        enquiry.refresh_from_db()
        self.assertEqual(enquiry.stage, Enquiry.Stage.LOST)
        self.client.post(reverse("sales_enquiry_stage", args=[enquiry.pk]), {"stage": "booked"})
        enquiry.refresh_from_db()
        self.assertEqual(enquiry.stage, Enquiry.Stage.LOST)        # Booked is not typed

    def test_bad_phone_on_an_enquiry_is_refused(self):
        self.client.post(reverse("sales_enquiry_new"), {
            "project": self.project.pk, "name": "ZQ Bad", "phone": "98-00", "source": "walkin"})
        self.assertFalse(Enquiry.objects.filter(name="ZQ Bad").exists())

    def test_booking_new_screen_and_post(self):
        unit = self.units[1]
        response = self.client.get(reverse("sales_booking_new", args=[unit.pk]),
                                   {"enquiry": self.enquiry.pk})
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("ZQ Asker", html)
        self.assertIn("On possession", html)
        post = {"phone": "9800000055", "name": "ZQ Asker", "agreement_value": "4900000",
                "gst_percent": "5", "booked_on": "2026-09-01", "enquiry": self.enquiry.pk}
        for index, (name, pct) in enumerate(calc.DEFAULT_SCHEDULE, 1):
            post[f"ms_name_{index}"] = name
            post[f"ms_pct_{index}"] = str(pct)
        response = self.client.post(reverse("sales_booking_new", args=[unit.pk]), post)
        booking = Booking.objects.get(unit=unit)
        self.assertRedirects(response, reverse("sales_booking", args=[booking.pk]))
        self.assertEqual(booking.enquiry_id, self.enquiry.pk)
        self.enquiry.refresh_from_db()
        self.assertEqual(self.enquiry.stage, Enquiry.Stage.BOOKED)

    def test_booking_new_refuses_a_bad_schedule_and_stays_on_the_form(self):
        unit = self.units[1]
        post = {"phone": "9800000055", "name": "ZQ Asker", "agreement_value": "4900000",
                "gst_percent": "5", "booked_on": "2026-09-01",
                "ms_name_1": "a", "ms_pct_1": "60", "ms_name_2": "b", "ms_pct_2": "60"}
        response = self.client.post(reverse("sales_booking_new", args=[unit.pk]), post)
        self.assertEqual(response.status_code, 200)
        self.assertIn("120", response.content.decode())
        self.assertFalse(Booking.objects.filter(unit=unit).exists())

    def test_booking_detail(self):
        response = self.client.get(reverse("sales_booking", args=[self.booking.pk]))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        for text in (self.booking.number, self.d1.number, self.d2.number, self.receipt.number,
                     "ZQ Ramesh Patel", "Part-paid", "Open", "52,50,000", "3,00,000",
                     "Raise demand", "Record receipt", "Cancel booking", "Transfer", "Save schedule"):
            self.assertIn(text, html)

    def test_booking_schedule_post(self):
        post = {"ms_name_1": "On booking", "ms_pct_1": "10"}
        # d1 is on milestone 1, d2 on milestone 2: both kept; the rest rewritten.
        post.update({"ms_name_2": "On agreement", "ms_pct_2": "10",
                     "ms_name_3": "Rest", "ms_pct_3": "80"})
        response = self.client.post(reverse("sales_booking_schedule", args=[self.booking.pk]), post)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.booking.milestones.count(), 3)
        self.assertEqual(calc.schedule_total_percent(self.booking.milestones.all()), D("100.00"))

    def test_mark_cancel_and_transfer_screens(self):
        self.client.post(reverse("sales_booking_mark", args=[self.booking.pk]),
                         {"step": "agreement", "on": "2026-09-05"})
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, Booking.Status.AGREEMENT)
        response = self.client.get(reverse("sales_booking_cancel", args=[self.booking.pk]),
                                   {"deduction_pct": "2"})
        html = response.content.decode()
        self.assertIn("3,00,000.00", html)          # collected
        self.assertIn("1,00,000.00", html)          # deduction and refund
        self.assertIn("Confirm cancellation", html)
        # Recalculate does not cancel.
        self.client.post(reverse("sales_booking_cancel", args=[self.booking.pk]),
                         {"deduction_pct": "5", "reason": "x", "confirm": "no"})
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, Booking.Status.AGREEMENT)
        response = self.client.get(reverse("sales_booking_transfer", args=[self.booking.pk]))
        self.assertEqual(response.status_code, 200)
        self.client.post(reverse("sales_booking_transfer", args=[self.booking.pk]),
                         {"phone": "9800000088", "name": "ZQ Assignee"})
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.customer.name, "ZQ Assignee")
        self.client.post(reverse("sales_booking_cancel", args=[self.booking.pk]),
                         {"deduction_pct": "2", "reason": "resold", "confirm": "yes"})
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, Booking.Status.CANCELLED)
        self.assertEqual(self.booking.refund_amount, D("200000.00"))
        # The cancelled booking still renders, without the action buttons.
        html = self.client.get(reverse("sales_booking", args=[self.booking.pk])).content.decode()
        # The button, not the word — the ⓘ panel still names it as an instruction.
        self.assertNotIn(reverse("sales_demand_new", args=[self.booking.pk]), html)
        self.assertIn("Cancelled", html)

    def test_customer_form(self):
        url = reverse("sales_customer_form", args=[self.customer.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(url, {"name": "ZQ Ramesh Patel", "phone": "9800000001",
                                          "pan": "abcde1234f", "next": self.booking.pk})
        self.assertRedirects(response, reverse("sales_booking", args=[self.booking.pk]))
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.pan, "ABCDE1234F")
        self.client.post(url, {"name": "ZQ Ramesh Patel", "phone": "9800000001", "pan": "bad"})
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.pan, "ABCDE1234F")

    def test_demand_new_screen_and_post(self):
        response = self.client.get(reverse("sales_demand_new", args=[self.booking.pk]))
        html = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn("On plinth", html)
        self.assertNotIn("1. On booking", html)      # already demanded
        milestone = self.booking.milestones.get(sequence=3)
        response = self.client.post(reverse("sales_demand_new", args=[self.booking.pk]), {
            "milestone": milestone.pk, "raised_on": "2026-09-10", "due_on": "2026-09-25"})
        self.assertEqual(response.status_code, 302)
        demand = Demand.objects.get(milestone=milestone)
        self.assertEqual(demand.amount, D("500000.00"))
        # Ad hoc.
        self.client.post(reverse("sales_demand_new", args=[self.booking.pk]), {
            "milestone": "", "amount": "1000", "raised_on": "2026-09-10", "due_on": "2026-09-25",
            "note": "ZQ parking"})
        self.assertTrue(Demand.objects.filter(booking=self.booking, note="ZQ parking").exists())

    def test_receipt_new_screen_and_post(self):
        response = self.client.get(reverse("sales_receipt_new", args=[self.booking.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.d1.number, response.content.decode())
        response = self.client.post(reverse("sales_receipt_new", args=[self.booking.pk]), {
            "demand": self.d1.pk, "amount": "225000", "received_on": "2026-09-10", "mode": "upi",
            "reference": "ZQUPI2", "tds_amount": "0"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(calc.bulk_demand_figures([self.d1])[self.d1.id]["status"], "paid")
        self.client.post(reverse("sales_receipt_new", args=[self.booking.pk]), {
            "demand": "", "amount": "abc", "received_on": "2026-09-10", "mode": "upi"})
        self.assertEqual(CustomerReceipt.objects.filter(booking=self.booking).count(), 2)

    def test_demands_for_header_post(self):
        header = self.header(done=True)
        m4 = self.booking.milestones.get(sequence=4)
        m4.task_header = header
        m4.save()
        response = self.client.post(reverse("sales_demands_for_header"),
                                    {"project": self.project.pk, "header": header.pk})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Demand.objects.filter(milestone=m4).exists())

    def test_bookings_register(self):
        response = self.client.get(reverse("sales_bookings"))
        html = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.booking.number, html)
        self.assertIn("49,50,000", html)
        response = self.client.get(reverse("sales_bookings"), {"q": "ZQ Ramesh", "status": "booked",
                                                                "project": self.project.pk})
        self.assertIn(self.booking.number, response.content.decode())
        response = self.client.get(reverse("sales_bookings"), {"status": "cancelled"})
        self.assertNotIn(self.booking.number, response.content.decode())

    def test_collections_screen_ages_and_totals(self):
        response = self.client.get(reverse("sales_collections"), {"project": self.project.pk})
        html = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.d1.number, html)
        self.assertIn(self.d2.number, html)
        self.assertIn("31–60 days", html)
        self.assertIn("Not due", html)
        self.assertIn("2,25,000", html)          # balance on d1

    def test_receipts_register_and_range(self):
        response = self.client.get(reverse("sales_receipts"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("ZQUTR1", response.content.decode())
        response = self.client.get(reverse("sales_receipts"), {"from": "2026-09-01", "to": "2026-09-30"})
        self.assertNotIn("ZQUTR1", response.content.decode())
        response = self.client.get(reverse("sales_receipts"), {"from": "2026-08-01", "mode": "neft"})
        self.assertIn("ZQUTR1", response.content.decode())

    def test_excel_exports(self):
        xlsx = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        for name in ("sales_collections_excel", "sales_receipts_excel"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200, name)
            self.assertEqual(response["Content-Type"], xlsx)
            self.assertGreater(len(response.content), 1000)

    def test_no_leaked_template_syntax(self):
        for name, args in (("sales_home", []), ("sales_units", []), ("sales_enquiries", []),
                           ("sales_bookings", []), ("sales_collections", []), ("sales_receipts", []),
                           ("sales_booking", [self.booking.pk]),
                           ("sales_booking_new", [self.units[1].pk]),
                           ("sales_booking_cancel", [self.booking.pk])):
            html = self.client.get(reverse(name, args=args)).content.decode()
            for leak in ("{#", "#}", "{%", "%}"):
                self.assertNotIn(leak, html, f"{leak} leaked on {name}")

    def test_no_project_yet_renders_empty_screens(self):
        CustomerReceipt.objects.all().delete()
        Demand.objects.all().delete()
        Booking.objects.all().delete()
        Enquiry.objects.all().delete()
        Unit.objects.all().delete()
        self.project.status = Project.Status.DRAFT
        self.project.save()
        for name in ("sales_home", "sales_units", "sales_enquiries", "sales_collections"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        self.assertEqual(self.client.get(reverse("sales_unit_new")).status_code, 302)


class DemandLetterPdf(ScreensFixture):

    def test_the_letter_renders_and_the_pdf_is_returned(self):
        with stubbed_weasyprint() as fake:
            response = self.client.get(reverse("sales_demand_pdf", args=[self.d1.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn(self.d1.number, response["Content-Disposition"])
        html = fake.HTML.call_args.kwargs["string"]
        self.assertIn("DEMAND LETTER", html)
        self.assertIn("ZQ Ramesh Patel", html)
        self.assertIn("5,25,000.00", html)              # the demand total
        self.assertIn("2,25,000.00", html)              # balance after the part payment
        self.assertIn("Rs ", html)
        self.assertNotIn("₹", html)
        self.assertNotIn("flex", html)
        for leak in ("{#", "#}", "{%", "%}"):
            self.assertNotIn(leak, html)


# ============================================================ permissions
class Refusals(ScreensFixture):

    def as_role(self, role):
        user = self.make_user(f"zq_{role}", role=role, name="ZQ Person")
        self.client.force_login(user)

    def test_site_engineer_cannot_read_sales(self):
        self.as_role(Role.SITE)
        for name in ("sales_home", "sales_units", "sales_bookings", "sales_collections"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)

    def test_accountant_reads_and_collects_but_does_not_edit(self):
        self.as_role(Role.ACCOUNTANT)
        self.assertEqual(self.client.get(reverse("sales_home")).status_code, 200)
        self.assertEqual(self.client.get(reverse("sales_collections")).status_code, 200)
        self.assertEqual(self.client.get(reverse("sales_receipt_new", args=[self.booking.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("sales_unit_new")).status_code, 403)
        self.assertEqual(self.client.get(reverse("sales_booking_new", args=[self.units[1].pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("sales_booking_mark", args=[self.booking.pk]),
                                          {"step": "agreement"}).status_code, 403)
        self.assertEqual(self.client.get(reverse("sales_booking_cancel", args=[self.booking.pk])).status_code, 403)
        # The buttons are hidden on the booking screen too.
        html = self.client.get(reverse("sales_booking", args=[self.booking.pk])).content.decode()
        self.assertIn("Record receipt", html)
        self.assertNotIn("Cancel booking", html)

    def test_project_manager_edits_but_does_not_collect(self):
        self.as_role(Role.PROJECT_MANAGER)
        self.assertEqual(self.client.get(reverse("sales_unit_new")).status_code, 200)
        self.assertEqual(self.client.get(reverse("sales_demand_new", args=[self.booking.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("sales_receipt_new", args=[self.booking.pk]),
                                          {"amount": "1"}).status_code, 403)
        self.assertEqual(self.client.post(reverse("sales_demands_for_header"), {}).status_code, 403)
        html = self.client.get(reverse("sales_booking", args=[self.booking.pk])).content.decode()
        self.assertNotIn("Record receipt", html)
        self.assertIn("Cancel booking", html)
        self.assertEqual(CustomerReceipt.objects.count(), 1)

    def test_writes_are_post_only(self):
        for name in ("sales_booking_mark", "sales_booking_schedule"):
            self.assertEqual(self.client.get(reverse(name, args=[self.booking.pk])).status_code, 405)
        self.assertEqual(self.client.get(reverse("sales_enquiry_visit", args=[self.enquiry.pk])).status_code, 405)


# ============================================================ query shape
class QueryCounts(Fixture):
    """More rows must not mean more queries — ANCHOR: SALES-CALC-BULK."""

    def fill(self, how_many, start):
        for index in range(how_many):
            unit = Unit.objects.create(project=self.project, number=f"ZQ-Q{start + index:03d}",
                                       block="Q", floor=index // 4 + 1, base_price=D("4000000"))
            booking = services.book_unit(unit, phone=f"97{start + index:08d}", name=f"ZQ Q{start + index}",
                                         agreement_value=D("4000000"), booked_on=self.today, by=self.user)
            for milestone in booking.milestones.all()[:2]:
                demand = services.raise_demand(booking, milestone, due_on=self.today - timedelta(days=index),
                                               raised_on=self.today - timedelta(days=index + 5), by=self.user)
                if index % 2:
                    services.record_receipt(booking, amount=D("1000"), demand=demand,
                                            received_on=self.today, by=self.user)
            Enquiry.objects.create(project=self.project, name=f"ZQ E{start + index}",
                                   phone=f"96{start + index:08d}")

    def count(self, name, params=None):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as context:
            response = self.client.get(reverse(name), params or {})
        self.assertEqual(response.status_code, 200, name)
        return len(context.captured_queries)

    def test_list_screens_do_not_grow_with_the_rows(self):
        self.fill(4, 0)
        screens = [("sales_home", {}), ("sales_units", {"project": self.project.pk}),
                   ("sales_bookings", {}), ("sales_collections", {}), ("sales_receipts", {}),
                   ("sales_enquiries", {})]
        small = {name: self.count(name, params) for name, params in screens}
        self.fill(20, 100)
        for name, params in screens:
            with self.subTest(screen=name):
                self.assertLess(self.count(name, params) - small[name], 10)

    def test_the_booking_screen_is_flat(self):
        booking = self.book()
        for milestone in booking.milestones.all():
            demand = services.raise_demand(booking, milestone, due_on=self.today, raised_on=self.today,
                                           by=self.user)
            services.record_receipt(booking, amount=D("100"), demand=demand, received_on=self.today,
                                    by=self.user)
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as context:
            response = self.client.get(reverse("sales_booking", args=[booking.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertLess(len(context.captured_queries), 25)


# ================================================================= seeding
class SeedCommand(Fixture):

    def test_refuses_without_showcase_projects_and_builds_with_them(self):
        from io import StringIO
        from django.core.management import call_command
        err = StringIO()
        call_command("seed_sales_showcase", stderr=err)
        self.assertIn("seed_showcase", err.getvalue())
        self.assertEqual(Booking.objects.count(), 0)

        showcase = Project.objects.create(code="PRJ-ZQSH", name="Showcase — ZQ Site",
                                          bua_sqft=D("20000"), status=Project.Status.WON)
        TaskHeader.objects.create(project=showcase, activity=self.rcc, name="ZQ 1st slab",
                                  start=date(2026, 8, 1), days=10)
        out = StringIO()
        call_command("seed_sales_showcase", stdout=out)
        self.assertGreater(Unit.objects.filter(project=showcase).count(), 20)
        self.assertGreater(Booking.objects.filter(unit__project=showcase).count(), 5)
        self.assertGreater(Demand.objects.filter(booking__unit__project=showcase).count(), 5)
        self.assertGreater(CustomerReceipt.objects.filter(booking__unit__project=showcase).count(), 3)
        self.assertTrue(Booking.objects.filter(unit__project=showcase,
                                               status=Booking.Status.CANCELLED).exists())
        self.assertTrue(Enquiry.objects.filter(project=showcase, stage=Enquiry.Stage.LOST).exists())
        # Every screen renders on top of it.
        for name in ("sales_home", "sales_bookings", "sales_collections", "sales_receipts"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        # And the schedule invariant held for every booking it made.
        for booking in Booking.objects.filter(unit__project=showcase):
            self.assertEqual(calc.schedule_total_percent(booking.milestones.all()), D("100.00"))

        call_command("seed_sales_showcase", "--remove", stdout=StringIO())
        self.assertEqual(Unit.objects.filter(project=showcase).count(), 0)
        self.assertEqual(Booking.objects.filter(unit__project=showcase).count(), 0)
        self.assertFalse(Customer.objects.filter(phone__startswith="98000").exists())
        # My own fixtures are untouched.
        self.assertEqual(Unit.objects.filter(project=self.project).count(), 4)


class CancelledUnitsAreForSaleAgain(ScreensFixture):

    def test_the_grid_says_cancelled_and_offers_book(self):
        services.cancel_booking(self.booking, reason="withdrew", by=self.user)
        html = self.client.get(reverse("sales_units"), {"project": self.project.pk}).content.decode()
        self.assertIn("Cancelled", html)
        self.assertIn(reverse("sales_booking_new", args=[self.unit.pk]), html)
        # The dashboard counts it as available again.
        html = self.client.get(reverse("sales_home")).content.decode()
        self.assertIn("<div class=\"l\">Units available</div><div class=\"v\">4</div>", html)

    def test_a_cancelled_booking_drops_out_of_collections_and_the_dashboard_money(self):
        services.cancel_booking(self.booking, reason="withdrew", by=self.user)
        html = self.client.get(reverse("sales_collections")).content.decode()
        self.assertNotIn(self.d1.number, html)
        html = self.client.get(reverse("sales_home")).content.decode()
        self.assertNotIn("49,50,000", html)
