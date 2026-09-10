"""
Vendor performance — one row per vendor, from the documents in the period.

⚠ EVERY MONEY FIGURE COMES FROM `PurchaseOrder.totals()` through
    `analytics.money`, and the plan rate from `bom_calc.planning_rate`. This
    module adds them up per vendor and takes averages; it re-derives no rule.

⚠ THREE MEASURES, THREE DIFFERENT PEOPLE:
      price vs plan   line taxable against quantity × the rate THIS PROJECT
                      planned at — did we buy at the rate we planned for?
                      (the same comparison as bom_calc.rate_variance, summed)
      days to pay     approval to payment — that measures US, not the vendor,
                      and is on the row so the two are read together
      lateness        delivered_at against required_by, where the order set
                      one. A document with no required-by date cannot be late
                      and is COUNTED rather than assumed — an invented due
                      date would call a punctual vendor late.

⚠ SORTABLE, BY A WHITELIST. The sort key travels in the query string so a
    view can be bookmarked; anything not in `SORTS` falls back to committed.
"""
from decimal import Decimal

from django.utils import timezone

from analytics import money
from projects.bom_calc import planning_rate
from projects.bom_models import PurchaseOrder

ZERO = Decimal("0.00")

#: key in the query string → (heading, the row field, default direction)
SORTS = {
    "vendor": ("Vendor", "name", "asc"),
    "documents": ("Documents", "documents", "desc"),
    "committed": ("Committed", "committed", "desc"),
    "paid": ("Paid", "paid", "desc"),
    "days_to_pay": ("Days to pay", "days_to_pay", "desc"),
    "price_pct": ("Price vs plan", "price_pct", "desc"),
    "late_days": ("Late", "late_days", "desc"),
}


def scorecard(orders):
    """One row per vendor over the documents given (already committed onward)."""
    rows = {}
    for order in orders:
        row = rows.setdefault(order.vendor_id, {
            "vendor": order.vendor,
            "name": order.vendor.name if order.vendor else "—",
            "documents": 0,
            "committed": ZERO,
            "paid": ZERO,
            "actual": ZERO,          # Σ line taxable
            "plan": ZERO,            # Σ quantity × planning rate
            "orders": [],
            "late": [],              # days late, one per dated and delivered order
            "no_due_date": 0,
        })
        totals = order.totals()
        row["documents"] += 1
        row["committed"] += totals["taxable"]
        if order.status == PurchaseOrder.Status.PAID:
            row["paid"] += totals["net_payable"]
        row["orders"].append(order)
        for line in order.lines.all():
            row["actual"] += line.taxable
            row["plan"] += line.quantity * planning_rate(line.bom_line)
        if order.required_by is None:
            row["no_due_date"] += 1
        elif order.delivered_at is not None:
            # ⚠ The local date, not the UTC one — a delivery logged at 11pm
            #   is not a day late because the server keeps UTC.
            row["late"].append((timezone.localdate(order.delivered_at) - order.required_by).days)

    for row in rows.values():
        row["days_to_pay"], row["paid_count"] = money.days_to_pay(row["orders"])
        row["price_diff"] = row["actual"] - row["plan"]
        row["price_pct"] = (((row["actual"] - row["plan"]) * 100 / row["plan"]).quantize(Decimal("0.1"))
                            if row["plan"] else None)
        row["late_count"] = len(row["late"])
        row["late_days"] = (round(sum(row["late"]) / len(row["late"])) if row["late"] else None)
        del row["orders"]
    return list(rows.values())


def sort(rows, key, direction):
    """Order the scorecard; unknown keys and directions fall back quietly."""
    heading, field, default = SORTS.get(key, SORTS["committed"])
    reverse = (direction or default) == "desc"
    if field == "name":
        return sorted(rows, key=lambda row: row["name"].lower(), reverse=reverse)
    # None sorts last whichever way, so a vendor with no figure never tops a list.
    figured = [row for row in rows if row[field] is not None]
    blank = [row for row in rows if row[field] is None]
    return sorted(figured, key=lambda row: row[field], reverse=reverse) + blank
