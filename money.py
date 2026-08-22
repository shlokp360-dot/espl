"""
Every figure on every analytics page comes from here.

>>> ANCHOR: ANALYTICS-MONEY <<<

⚠⚠ "SPEND" MEANS MONEY PAID. NOTHING ELSE MAY BE CALLED SPEND.
    Saahil corrected this during the design session and it is the single most
    important word on the module. Three stages, three dates, three different
    numbers that people confuse daily:

        committed   approved onward · counts on `approved_at` · EX-GST
        received    delivered onward · counts on `delivered_at`
        paid        counts on `paid_at` · the NET PAYABLE, after TDS

    A page that adds them together, or labels the wrong one "spend", is worse
    than no page.

⚠ DOCUMENT MONEY COMES FROM `PurchaseOrder.totals()`, NEVER RE-DERIVED.
    That method is the same one the printed PDF uses. Re-summing lines here to
    save a loop would eventually disagree with a document somebody is holding,
    and the document wins every argument.

⚠ THERE IS NO SNAPSHOT TABLE. Every page queries the real tables. A stored
    figure and a live one disagree eventually, and the stored one is always the
    one somebody has already acted on.

⚠ A DRAFT IS NOT COMMITTED. It commits nobody to anything and must never appear
    in a commitment figure. `po_value_now` on the BOM means "about to be
    ordered" and is zero once posted — a different thing entirely.

⚠ SUMMED IN PYTHON OVER PREFETCHED LINES, ON PURPOSE. The same reasoning as
    `totals()` itself: percentage arithmetic in SQL is not portable — SQLite
    integer-divides 10/100 to zero where PostgreSQL does not — so money worked
    out in the database would differ between his laptop and their server. The
    cost is bounded and measured: see `analytics/tests.py`, which asserts the
    query count does not grow with the number of documents.
"""
import re
from datetime import timedelta
from decimal import Decimal

from projects.bom_models import PurchaseOrder

ZERO = Decimal("0.00")

#: stage → the date it counts on. The whole module hangs off this table.
STAGE_DATE = {
    "committed": "approved_at",
    "received": "delivered_at",
    "paid": "paid_at",
}

#: stage → the statuses a document must have reached.
#: ⚠ A document that is PAID has also been committed and received. Counting
#:   "committed" as status=approved ONLY would make a month's commitments shrink
#:   as the invoices were settled, which is the opposite of what commitment means.
STAGE_STATUS = {
    "committed": [PurchaseOrder.Status.APPROVED, PurchaseOrder.Status.DELIVERED,
                  PurchaseOrder.Status.PAID],
    "received": [PurchaseOrder.Status.DELIVERED, PurchaseOrder.Status.PAID],
    "paid": [PurchaseOrder.Status.PAID],
}

#: The ladder's keys, in the order they are printed. Used by the G2N page and by
#: `add_up` so a new step cannot be forgotten in one place and not the other.
LADDER = ["gross", "discount", "taxable", "gst", "cgst", "sgst", "invoice_value",
          "deduction", "round_off", "order_value", "tds", "net_payable"]


def base_queryset(project=None, doc_type=None, vendor=None):
    """
    Documents, with everything a total needs already loaded.

    ⚠ `prefetch_related("lines")` IS LOAD-BEARING, not an optimisation. Without
      it `totals()` fires one query per document, which is 420 today and 4,200
      at ten times the size — the exact mistake this project's own bug list
      records three times.
    """
    rows = (PurchaseOrder.objects
            .select_related("project", "vendor")
            .prefetch_related("lines__bom_line__activity", "lines__bom_line__material"))
    if project:
        rows = rows.filter(project=project)
    if doc_type:
        rows = rows.filter(document_type=doc_type)
    if vendor:
        rows = rows.filter(vendor=vendor)
    return rows


def documents(stage, start, end, project=None, doc_type=None, vendor=None):
    """
    The documents that count for one stage inside one window.

    ⚠ THE DATE FIELD CHANGES WITH THE STAGE, and that is the point. The same
      document appears in April's commitments and July's payments, because it
      was approved in April and paid in July. Both are true.
    """
    field = STAGE_DATE[stage]
    return list(
        base_queryset(project, doc_type, vendor)
        .filter(status__in=STAGE_STATUS[stage],
                **{f"{field}__date__gte": start, f"{field}__date__lte": end})
        .order_by(field))


def add_up(orders):
    """
    The whole ladder, summed across documents.

    Returns the same keys `totals()` does, so a page can print a company-wide
    gross-to-net with exactly the labels that appear on one document.
    """
    out = {key: ZERO for key in LADDER}
    out["line_count"] = 0
    out["count"] = 0
    for order in orders:
        totals = order.totals()
        for key in LADDER:
            out[key] += totals[key]
        out["line_count"] += totals["line_count"]
        out["count"] += 1
    return out


# --------------------------------------------------------------- what is owed
#
# ⚠ PAYABLES COUNT FROM DELIVERY, NOT FROM APPROVAL. Saahil's answer in the
#   design session. Approving commits the money; taking delivery is what makes
#   it owed. A payables page built on approval would show a bill for material
#   still sitting at the supplier.

_DAYS_IN_TERMS = re.compile(r"(\d+)")

#: The house default when a vendor's terms cannot be read.
#:
#: ⚠ SAAHIL'S DECISION, 14 AUG, AND IT OVERTURNS AN EARLIER ONE. This module
#:   originally refused to invent a due date and put such documents in a
#:   "terms unknown" bucket. His call — "sure, have a default of 30 days for
#:   payment terms" — and it is the right one for a business where 173 of 174
#:   vendors have nothing typed in that field: a page that ages almost nothing
#:   is a page nobody opens.
#:
#: ⚠ THE OLD OBJECTION IS ANSWERED RATHER THAN IGNORED. An assumed date can put
#:   a real invoice in the wrong bucket, so `credit_days` still reports WHETHER
#:   it had to assume, every screen counts how many rows were assumed, and the
#:   ⓘ says so. The number is visible, not silent.
#:
#: ⚠ ONE CONSTANT, ONE PLACE. When they want it configurable it becomes a field
#:   on CompanyProfile and this line reads it — a ten-minute change, and not
#:   worth a migration until somebody asks.
DEFAULT_CREDIT_DAYS = 30


def credit_days(vendor):
    """
    Days after delivery that a vendor's invoice falls due, and whether we guessed.

    Returns `(days, assumed)`. `Vendor.payment_terms` is free text — "30 days",
    "45", "Advance", "" — so anything with a number in it gives that number and
    `assumed=False`; anything else gives the house default and `assumed=True`.
    """
    found = _DAYS_IN_TERMS.search(getattr(vendor, "payment_terms", "") or "") if vendor else None
    if found:
        return int(found.group(1)), False
    return DEFAULT_CREDIT_DAYS, True


def due_date(order):
    """When an order's invoice falls due. None only when it has not been delivered."""
    if order.delivered_at is None:
        return None
    days, _assumed = credit_days(order.vendor)
    return order.delivered_at.date() + timedelta(days=days)


def terms_assumed(order):
    """Whether this document's due date rests on the house default."""
    _days, assumed = credit_days(order.vendor)
    return assumed


# ------------------------------------------------------------- the settlement
#
# >>> ANCHOR: ANALYTICS-SETTLEMENT <<<
#
# ⚠ THE QUESTION A BUSINESS HEAD ACTUALLY ASKS: how much have we paid, and how
#     much is still to pay. Saahil's words — "the officials, the business heads
#     would want to know how much is to be paid and how much has been paid to
#     understand their books better."
#
# ⚠⚠ ALL THREE BUCKETS ARE ON ONE BASIS AND THEY ADD BACK TO THE TOTAL. That is
#     the whole discipline of this function. Committed is normally quoted ex-GST
#     and paid is normally quoted net of TDS — both correct, and putting those
#     two numbers side by side under a heading called "settlement" would produce
#     a gap that is pure arithmetic and looks like missing money. So every figure
#     here is `net_payable`: what actually leaves, or will leave, the bank.
#
#         settled            paid
#       + payable_now        delivered, not paid — the bill on the desk
#       + not_yet_payable    approved, not delivered — coming, not owed
#       = obligation         everything approved onward
#
#     A test asserts the three sum to the total. If a status is ever added to the
#     lifecycle, that test fails rather than the page quietly losing a bucket.
#
# ⚠ TDS IS NAMED, NOT LOST. `order_value` is what vendors invoice; `net_payable`
#     is what leaves the bank; the difference is tax withheld on their behalf. A
#     books page that showed only one of those invites "why does this not match
#     the ledger".

def settlement(project=None, doc_type=None, vendor=None):
    """
    Paid, owed now, and coming — plus what the vendors actually invoiced.

    ⚠ NOT FILTERED BY PERIOD. "How much do we still owe" is a question about
      today, not about a month: an invoice from March that is unpaid in August
      is still unpaid in August, and a period filter would hide the oldest and
      most urgent debts. The Overview's PTD/CPD figures answer the other
      question — what moved *in* a period.
    """
    rows = base_queryset(project, doc_type, vendor).exclude(
        status=PurchaseOrder.Status.DRAFT)

    buckets = {
        "settled": [],
        "payable_now": [],
        "not_yet_payable": [],
    }
    for order in rows:
        if order.status == PurchaseOrder.Status.PAID:
            buckets["settled"].append(order)
        elif order.status == PurchaseOrder.Status.DELIVERED:
            buckets["payable_now"].append(order)
        else:                                   # APPROVED, not yet delivered
            buckets["not_yet_payable"].append(order)

    totals = {name: add_up(orders) for name, orders in buckets.items()}
    obligation = sum((totals[name]["net_payable"] for name in buckets), ZERO)
    invoiced = sum((totals[name]["order_value"] for name in buckets), ZERO)

    return {
        "orders": buckets,
        "settled": totals["settled"],
        "payable_now": totals["payable_now"],
        "not_yet_payable": totals["not_yet_payable"],
        "obligation": obligation,
        # What the vendors bill, before the tax we withhold on their behalf.
        "invoiced": invoiced,
        "tds": invoiced - obligation,
        "settled_pct": int(round(totals["settled"]["net_payable"] * 100 / obligation))
        if obligation else 0,
    }


#: Ageing, from the due date. The first bucket is money not yet owed; the rest
#: are how late we are. ⚠ "Terms unknown" is a bucket rather than an assumption —
#: see credit_days.
AGEING = [
    ("not_due", "Not due yet"),
    ("d30", "1–30 days over"),
    ("d60", "31–60 days over"),
    ("d90", "61–90 days over"),
    ("older", "Over 90 days"),
]


def ageing(orders, today):
    """
    Unpaid documents, bucketed by how far past their due date they are.

    ⚠ THE "TERMS UNKNOWN" BUCKET IS GONE — every document now has a due date,
      because a vendor with nothing in its terms takes the house default of 30
      days. What has NOT gone is the honesty: each bucket counts how many of its
      rows rest on that assumption, and the screen prints the number.
    """
    out = {key: {"label": label, "orders": [], "total": ZERO, "assumed": 0}
           for key, label in AGEING}
    for order in orders:
        due = due_date(order)
        if due is None or due >= today:
            key = "not_due"
        else:
            over = (today - due).days
            key = "d30" if over <= 30 else "d60" if over <= 60 else "d90" if over <= 90 else "older"
        out[key]["orders"].append(order)
        out[key]["total"] += order.totals()["net_payable"]
        if terms_assumed(order):
            out[key]["assumed"] += 1
    return [dict(out[key], key=key) for key, _label in AGEING]


def days_to_pay(orders):
    """
    Average days from approval to payment, and the count it is based on.

    ⚠ FROM APPROVAL, NOT FROM DELIVERY. This measures US — how long we sit on a
      bill once we have agreed to it. Measured from delivery it would blend our
      behaviour with the vendor's, and the whole point of the number is to know
      which of the two is slow.
    """
    spans = [(order.paid_at.date() - order.approved_at.date()).days
             for order in orders if order.paid_at and order.approved_at]
    return (round(sum(spans) / len(spans)) if spans else 0), len(spans)


def by_vendor(orders):
    """One row per vendor: how many documents and what they come to."""
    rows = {}
    for order in orders:
        entry = rows.setdefault(order.vendor_id, {
            "vendor": order.vendor, "count": 0, "net": ZERO, "invoiced": ZERO})
        totals = order.totals()
        entry["count"] += 1
        entry["net"] += totals["net_payable"]
        entry["invoiced"] += totals["order_value"]
    # ⚠ The withheld tax is worked out HERE, not in the template. Subtraction in
    #   a template needs a filter, and a filter is where the next arithmetic bug
    #   goes to hide.
    for entry in rows.values():
        entry["tds"] = entry["invoiced"] - entry["net"]
    return sorted(rows.values(), key=lambda row: row["net"], reverse=True)


def by_activity(orders):
    """
    Money split across activities, from the LINES.

    ⚠⚠ EX-GST, AND IT CANNOT HONESTLY BE ANYTHING ELSE. A document's deduction,
      round-off and TDS are properties of the whole document, not of one line —
      there is no non-arbitrary way to split them across trades. So this is the
      line-level taxable value, which is also the basis the BOQ reserve uses, and
      the screen says so. It will NOT add up to net payable, and a page that
      pretended otherwise would be inventing a split.

    ⚠ A line whose BOM line has no activity is grouped under "Unassigned" rather
      than dropped, because money that vanishes from a chart is worse than money
      that is awkward to explain.
    """
    rows = {}
    for order in orders:
        for line in order.lines.all():
            activity = getattr(line.bom_line, "activity", None)
            key = activity.pk if activity else 0
            entry = rows.setdefault(key, {
                "activity": activity,
                "label": activity.name if activity else "Unassigned",
                "value": ZERO})
            entry["value"] += line.taxable
    return sorted(rows.values(), key=lambda row: row["value"], reverse=True)


def outstanding(project=None, doc_type=None, vendor=None):
    """
    Delivered and not yet paid — what is actually owed today, at any date.

    ⚠ NOT FILTERED BY PERIOD, DELIBERATELY. An invoice from March that is still
      unpaid in August is still owed in August; a payables page that only showed
      this month's would quietly hide the oldest and most urgent debts.
    """
    return list(
        base_queryset(project, doc_type, vendor)
        .filter(status=PurchaseOrder.Status.DELIVERED)
        .order_by("delivered_at"))
