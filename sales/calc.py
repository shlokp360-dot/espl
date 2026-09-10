"""
Every figure the sales screens show, and nothing else.

>>> ANCHOR: SALES-CALC <<<

⚠ ONE FUNCTION PER FIGURE. A number on a sales screen, a demand letter or an
  Excel export comes from here, by name. A template never adds; a view never
  repeats a formula that lives here. If a figure is wrong, this is the only
  file to open.

⚠ DECIMAL, ROUNDED HALF-UP TO THE PAISA AT THE POINT IT IS CALCULATED — the
  same `_money` as the purchase-order ladder. Never float, never SQL: SQLite
  integer-divides `10 / 100` to zero, PostgreSQL does not, and a sum that
  agrees on the laptop and disagrees on the server is worse than a slow one.

⚠ THE LEDGER CONVENTION. A demand is a DEBIT to the customer (they owe it), a
  receipt is a CREDIT (they paid it). `credit` on a receipt is amount + TDS,
  because the buyer's TDS deposit is money paid on the developer's behalf.

>>> ANCHOR: SALES-CALC-BULK <<<
⚠ THE LIST SCREENS USE THE BULK FUNCTIONS. `bulk_booking_figures` walks every
  booking's demands and receipts in TWO queries, however many bookings there
  are. A per-booking call inside a loop is the shape every slow screen in this
  system has had, and the query-count tests in sales/tests.py exist to catch
  it coming back.
"""
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

_PAISA = Decimal("0.01")
ZERO = Decimal("0")

#: TDS under section 194-IA: 1% withheld by the buyer when the consideration
#: is above fifty lakh. The threshold and rate are the law's, not ours.
TDS_THRESHOLD = Decimal("5000000")
TDS_PERCENT = Decimal("1")

#: >>> ANCHOR: SALES-SCHEDULE <<<
#: The default construction-linked schedule a new booking starts with. The
#: booking form shows it as editable rows; what is saved is whatever the rows
#: say, as long as they add to 100. (name, percent)
DEFAULT_SCHEDULE = [
    ("On booking", Decimal("10")),
    ("On agreement", Decimal("10")),
    ("On plinth", Decimal("10")),
    ("On 1st slab", Decimal("15")),
    ("On 3rd slab", Decimal("15")),
    ("On top slab", Decimal("15")),
    ("On finishing", Decimal("15")),
    ("On possession", Decimal("10")),
]

AGEING_BUCKETS = [
    ("not_due", "Not due"),
    ("0_30", "0–30 days"),
    ("31_60", "31–60 days"),
    ("61_90", "61–90 days"),
    ("90_plus", "90+ days"),
]


def _money(value) -> Decimal:
    return Decimal(value).quantize(_PAISA, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------- one figure
def milestone_amount(agreement_value, percent) -> Decimal:
    """What one schedule row is worth, ex-GST."""
    return _money(Decimal(agreement_value) * Decimal(percent) / 100)


def gst_on(amount, gst_percent) -> Decimal:
    return _money(Decimal(amount) * Decimal(gst_percent) / 100)


def demand_gst(demand) -> Decimal:
    return gst_on(demand.amount, demand.gst_percent)


def demand_total(demand) -> Decimal:
    return _money(Decimal(demand.amount) + demand_gst(demand))


def booking_gst(booking) -> Decimal:
    return gst_on(booking.agreement_value, booking.gst_percent)


def booking_total(booking) -> Decimal:
    """Agreement value plus GST — everything the customer will ever pay."""
    return _money(Decimal(booking.agreement_value) + booking_gst(booking))


def receipt_credit(receipt) -> Decimal:
    """What the customer is credited for: what reached the bank plus the TDS they deposited."""
    return _money(Decimal(receipt.amount) + Decimal(receipt.tds_amount or 0))


def suggested_tds(booking, amount=None) -> Decimal:
    """
    The TDS the buyer is expected to withhold on a payment.

    ⚠ ON THE AGREEMENT VALUE, NOT ON THIS PAYMENT, is the threshold; the 1% is
      of the payment being made. `amount` defaults to the whole agreement
      value so the booking screen can show the total expected.
    """
    if Decimal(booking.agreement_value) <= TDS_THRESHOLD:
        return ZERO
    base = Decimal(booking.agreement_value if amount is None else amount)
    return _money(base * TDS_PERCENT / 100)


def schedule_total_percent(rows) -> Decimal:
    """`rows` are milestones or (name, percent) pairs or dicts with 'percent'."""
    total = ZERO
    for row in rows:
        if isinstance(row, dict):
            total += Decimal(row["percent"])
        elif isinstance(row, (tuple, list)):
            total += Decimal(row[1])
        else:
            total += Decimal(row.percent)
    return _money(total)


def validate_schedule(rows):
    """
    >>> ANCHOR: SALES-SCHEDULE <<<
    Raise ValueError unless the rows add to exactly 100. The message carries
    the actual total, because "must be 100" without the number sends somebody
    back to add it up by hand.
    """
    if not rows:
        raise ValueError("The schedule has no rows. A booking needs at least one milestone.")
    total = schedule_total_percent(rows)
    if total != Decimal("100"):
        raise ValueError(f"The schedule adds to {total}%, not 100%. Adjust the rows.")
    return total


# ---------------------------------------------------- sums over one booking
def collected(booking, receipts=None) -> Decimal:
    rows = list(booking.receipts.all()) if receipts is None else receipts
    return _money(sum((receipt_credit(r) for r in rows), ZERO))


def demanded(booking, demands=None) -> Decimal:
    """Everything demanded so far, GST included."""
    rows = list(booking.demands.all()) if demands is None else demands
    return _money(sum((demand_total(d) for d in rows), ZERO))


def outstanding(booking, receipts=None) -> Decimal:
    """Total payable less everything collected. Never below zero on screen."""
    return _money(booking_total(booking) - collected(booking, receipts))


def due_balance(booking, demands=None, receipts=None) -> Decimal:
    """What has been demanded and not yet paid — the figure to chase."""
    balance = demanded(booking, demands) - collected(booking, receipts)
    return _money(balance) if balance > 0 else ZERO


def allocate_receipts(demands, receipts):
    """
    How much of each demand has been paid, as {demand_id: Decimal}.

    ⚠ A RECEIPT ON A DEMAND PAYS THAT DEMAND. A RECEIPT ON ACCOUNT PAYS THE
      OLDEST OPEN DEMAND FIRST, then the next — the customer paid before the
      letter or without quoting it, and the money is still theirs against the
      earliest thing they owe. Excess over every demand stays as an advance.
    """
    paid = defaultdict(lambda: ZERO)
    on_account = ZERO
    for receipt in receipts:
        if receipt.demand_id:
            paid[receipt.demand_id] += receipt_credit(receipt)
        else:
            on_account += receipt_credit(receipt)
    for demand in sorted(demands, key=lambda d: (d.due_on, d.raised_on, d.id)):
        if on_account <= 0:
            break
        gap = demand_total(demand) - paid[demand.id]
        if gap > 0:
            take = min(gap, on_account)
            paid[demand.id] += take
            on_account -= take
    return {d.id: _money(paid[d.id]) for d in demands}


def demand_status(demand, paid_amount) -> str:
    """open / part_paid / paid, from what has been allocated to it."""
    total = demand_total(demand)
    if paid_amount >= total:
        return "paid"
    if paid_amount > 0:
        return "part_paid"
    return "open"


def demand_balance(demand, paid_amount) -> Decimal:
    balance = demand_total(demand) - Decimal(paid_amount)
    return _money(balance) if balance > 0 else ZERO


def percent_of(part, whole) -> Decimal:
    """`part` as a percentage of `whole`, one decimal. Zero when there is no whole."""
    if not whole:
        return ZERO
    return (Decimal(part) * 100 / Decimal(whole)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def days_past(due_on, today) -> int:
    """Days since the due date. Negative while it is still in the future."""
    return (today - due_on).days


def ageing_bucket(due_on, today) -> str:
    days = (today - due_on).days
    if days < 0:
        return "not_due"
    if days <= 30:
        return "0_30"
    if days <= 60:
        return "31_60"
    if days <= 90:
        return "61_90"
    return "90_plus"


def overdue(booking, today, demands=None, receipts=None) -> Decimal:
    """The unpaid part of every demand whose due date has passed."""
    demand_rows = list(booking.demands.all()) if demands is None else demands
    receipt_rows = list(booking.receipts.all()) if receipts is None else receipts
    paid = allocate_receipts(demand_rows, receipt_rows)
    return _money(sum((demand_balance(d, paid[d.id]) for d in demand_rows if d.due_on < today), ZERO))


def refund_on_cancel(booking, deduction_pct, receipts=None):
    """
    What goes back to the customer: collected less the agreed deduction.

    ⚠ THE DEDUCTION IS A PERCENT OF THE AGREEMENT VALUE, capped at what was
      actually collected — a forfeiture clause reads "10% of the consideration",
      and it cannot take back more than was paid. Returns (deduction, refund).
    """
    got = collected(booking, receipts)
    deduction = _money(Decimal(booking.agreement_value) * Decimal(deduction_pct or 0) / 100)
    if deduction > got:
        deduction = got
    return deduction, _money(got - deduction)


def unit_status(unit, bookings) -> str:
    """
    available / booked / registered / cancelled, from the unit's bookings.

    ⚠ CANCELLED MEANS "WAS SOLD, IS FOR SALE AGAIN". A unit whose only bookings
      are cancelled is bookable, and the KPI counts it with the available ones;
      it reads Cancelled on the grid so the person selling it knows there is a
      history to look at.
    """
    live = [b for b in bookings if b.status != "cancelled"]
    if live:
        return "registered" if live[-1].status == "registered" else "booked"
    return "cancelled" if bookings else "available"


def is_bookable(status) -> bool:
    return status in ("available", "cancelled")


# --------------------------------------------------------------- the ledger
def ledger(booking, demands, receipts):
    """
    The customer's statement: every demand and receipt in date order, with a
    running balance. Positive balance = the customer owes; negative = advance.
    """
    rows = []
    for demand in demands:
        rows.append({"on": demand.raised_on, "sort": (demand.raised_on, 0, demand.id),
                     "kind": "demand", "ref": demand.number,
                     "text": demand.milestone.name if demand.milestone_id and demand.milestone else demand.note,
                     "debit": demand_total(demand), "credit": ZERO})
    for receipt in receipts:
        rows.append({"on": receipt.received_on, "sort": (receipt.received_on, 1, receipt.id),
                     "kind": "receipt", "ref": receipt.number,
                     "text": f"{receipt.get_mode_display()} {receipt.reference}".strip(),
                     "debit": ZERO, "credit": receipt_credit(receipt)})
    rows.sort(key=lambda r: r["sort"])
    balance = ZERO
    for row in rows:
        balance = _money(balance + row["debit"] - row["credit"])
        row["balance"] = balance
        # Shown without the sign, with the word "advance" doing the work of the minus.
        row["advance"] = balance < 0
        row["balance_shown"] = abs(balance)
    return rows


# ------------------------------------------------------------------ in bulk
def bulk_booking_figures(bookings, today=None):
    """
    >>> ANCHOR: SALES-CALC-BULK <<<
    {booking_id: {agreement, gst, total, demanded, collected, outstanding,
                  due, overdue}} for a list of bookings, in two queries.
    """
    from sales.models import CustomerReceipt, Demand

    rows = list(bookings)
    ids = [b.id for b in rows]
    demands_by = defaultdict(list)
    receipts_by = defaultdict(list)
    if ids:
        for demand in Demand.objects.filter(booking_id__in=ids).order_by("due_on", "id"):
            demands_by[demand.booking_id].append(demand)
        for receipt in CustomerReceipt.objects.filter(booking_id__in=ids).order_by("received_on", "id"):
            receipts_by[receipt.booking_id].append(receipt)
    out = {}
    for booking in rows:
        demand_rows, receipt_rows = demands_by[booking.id], receipts_by[booking.id]
        got = collected(booking, receipt_rows)
        out[booking.id] = {
            "agreement": _money(booking.agreement_value),
            "gst": booking_gst(booking),
            "total": booking_total(booking),
            "demanded": demanded(booking, demand_rows),
            "collected": got,
            "outstanding": _money(booking_total(booking) - got),
            "due": due_balance(booking, demand_rows, receipt_rows),
            "overdue": overdue(booking, today, demand_rows, receipt_rows) if today else ZERO,
        }
    return out


def bulk_demand_figures(demands):
    """
    {demand_id: {gst, total, paid, balance, status}} for a list of demands,
    in one query for the receipts of every booking involved.
    """
    from sales.models import CustomerReceipt, Demand

    rows = list(demands)
    booking_ids = {d.booking_id for d in rows}
    if not booking_ids:
        return {}
    # ⚠ EVERY DEMAND OF THOSE BOOKINGS, NOT ONLY THE ONES LISTED — an on-account
    #   receipt is allocated oldest-first across the whole booking, so a filtered
    #   list would allocate wrongly if it saw only part of the picture.
    all_demands = defaultdict(list)
    for demand in Demand.objects.filter(booking_id__in=booking_ids):
        all_demands[demand.booking_id].append(demand)
    receipts_by = defaultdict(list)
    for receipt in CustomerReceipt.objects.filter(booking_id__in=booking_ids).order_by("received_on", "id"):
        receipts_by[receipt.booking_id].append(receipt)
    paid_by_booking = {bid: allocate_receipts(all_demands[bid], receipts_by[bid]) for bid in booking_ids}
    out = {}
    for demand in rows:
        paid = paid_by_booking[demand.booking_id].get(demand.id, ZERO)
        out[demand.id] = {
            "gst": demand_gst(demand),
            "total": demand_total(demand),
            "paid": paid,
            "balance": demand_balance(demand, paid),
            "status": demand_status(demand, paid),
        }
    return out


def bulk_unit_status(units):
    """{unit_id: status} in one query over the bookings of every unit given."""
    from sales.models import Booking

    rows = list(units)
    by_unit = defaultdict(list)
    if rows:
        for booking in Booking.objects.filter(unit_id__in=[u.id for u in rows]).order_by("id"):
            by_unit[booking.unit_id].append(booking)
    return {u.id: unit_status(u, by_unit[u.id]) for u in rows}
