"""
Sales velocity — how fast units move, and how the money follows them.

⚠ EVERY RUPEE COMES FROM `sales.calc`: a demand is `calc.demand_total`, a
    receipt is `calc.receipt_credit`, a unit's state is `calc.bulk_unit_status`.
    This module counts and groups by month; it re-derives nothing.

⚠ THE FISCAL YEAR, LIKE EVERY OTHER ANALYTICS PAGE — April to March, the
    months that have begun (see analytics.periods). A cancelled booking is
    not a sale and is left out; a registered one is still a booking in the
    month it was booked.

⚠ DAYS TO BOOK IS ONLY MEASURED WHERE THE ENQUIRY IS LINKED. A booking with
    no enquiry has no start date to count from, so it is left out and the
    screen prints how many were counted rather than pretending.
"""
from collections import defaultdict
from decimal import Decimal

from django.utils import timezone

from sales import calc

ZERO = Decimal("0.00")


def _key(day):
    return f"{day.year:04d}-{day.month:02d}"


def bookings_by_month(bookings, months):
    """{"2026-04": count, …} over the fiscal months given."""
    counts = defaultdict(int)
    for booking in bookings:
        counts[_key(booking.booked_on)] += 1
    return [{"key": key, "label": label.split()[0], "count": counts.get(key, 0)}
            for key, label in months]


def days_to_book(bookings):
    """Average days from the enquiry being raised to the booking, and the count behind it."""
    spans = [(booking.booked_on - timezone.localdate(booking.enquiry.created_at)).days
             for booking in bookings if booking.enquiry_id and booking.enquiry]
    spans = [span for span in spans if span >= 0]
    return (round(sum(spans) / len(spans)) if spans else 0), len(spans)


def money_by_month(demands, receipts, months):
    """Demanded (GST included) and collected (credit, TDS included) per fiscal month."""
    demanded, collected = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO)
    for demand in demands:
        demanded[_key(demand.raised_on)] += calc.demand_total(demand)
    for receipt in receipts:
        collected[_key(receipt.received_on)] += calc.receipt_credit(receipt)
    return [{"key": key, "label": label.split()[0],
             "demanded": demanded.get(key, ZERO), "collected": collected.get(key, ZERO)}
            for key, label in months]


def units_by_project(projects, units):
    """Available, booked and registered per project, from the bookings — one query."""
    status_of = calc.bulk_unit_status(units)
    rows = []
    for project in projects:
        own = [unit for unit in units if unit.project_id == project.id]
        statuses = [status_of[unit.id] for unit in own]
        row = {
            "project": project,
            "units": len(own),
            "available": sum(1 for status in statuses if calc.is_bookable(status)),
            "booked": sum(1 for status in statuses if status == "booked"),
            "registered": sum(1 for status in statuses if status == "registered"),
        }
        row["sold_pct"] = calc.percent_of(row["booked"] + row["registered"], row["units"])
        rows.append(row)
    return rows
