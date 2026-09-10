"""
Every rupee figure on a finance screen, in one place.

>>> ANCHOR: FIN-CALC <<<
ONE function per figure, Decimal throughout, rounded half-up to the paisa
WHERE THE FIGURE IS CALCULATED — `_money` from projects.bom_models, the same
function PurchaseOrder.totals() uses, so a bill and the order it bills against
round the same way at every step. Nothing here is summed in SQL: SQLite
integer-divides 10/100 to zero and PostgreSQL does not, so money computed in
the database would differ between the laptop and the server.

THE RA BILL LADDER, in printed order, and why each base is what it is:

    gross_this_bill      Σ qty × rate                 certified qty once certified,
                                                      the claimed qty until then
  - discount             Σ gross_line × disc%         per line, as on the work order
  = taxable              work done this bill, ex-GST — what GST is charged on
  + gst                  Σ taxable_line × gst%        CGST/SGST halves as PO-TOTALS
  = invoice_value        what the contractor's invoice says
  - deduction            invoice_value × deduction%   ⚠ POST-TAX, the same base as
                                                      the order (PO-TOTALS): it is
                                                      not a discount and the tax
                                                      above does not move
  - retention            taxable × retention%         ⚠ ON THE WORK VALUE, EX-GST.
                                                      Retention secures the WORK,
                                                      not the tax on it; GST is
                                                      paid to the contractor in
                                                      full because they owe it to
                                                      the department this month
  - advance_recovery     min(outstanding, taxable × advance ÷ order taxable)
                                                      pro rata to the work done;
                                                      the final bill recovers
                                                      whatever is left
  ± round_off            to the nearest rupee, COMPUTED never stored
  = payable              what we owe on this bill
  - tds                  taxable × tds%              ⚠ on the TAXABLE value, never
                                                      on GST — as on the order
  = net_payable          what leaves the bank

⚠ THE ADVANCE RECOVERY FOLLOWS THE AGREED TERM, NOT THE PAYMENTS REGISTER.
  `outstanding` is the work order's `mobilisation_advance` less what earlier
  approved bills already recovered. It is NOT the sum of advance payments
  actually made, and that is deliberate: a bill approved in March must print
  the same figures in June, and a payment recorded late would otherwise move
  an approved bill's net payable. The gap between advance paid and advance
  recovered is shown on the work order screen for exactly the case where they
  differ.

⚠ EVERY "TO DATE" FIGURE SUMS OVER APPROVED AND PAID BILLS ONLY. A draft or
  certified bill is a claim under discussion; it counts nowhere, exactly as a
  draft purchase order counts nowhere in ANALYTICS-MONEY.

>>> ANCHOR: FIN-CALC-BULK <<<
The list screens call the `bulk_*` functions, which fetch every related row
for a set of work orders in a fixed number of queries and hand them down.
Calling the single-object function inside a loop would be a query per row.
"""
from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from projects.bom_models import PurchaseOrder, _money

from .models import RABill, RetentionRelease, VendorInvoice, VendorPayment

ZERO = Decimal("0")
ONE_RUPEE = Decimal("1")


# ------------------------------------------------------------- one bill line

def line_figures(line, qty=None):
    """
    The money on one RA bill line, from a quantity and the frozen rate.

    `qty` defaults to the certified quantity once there is one, else the
    claimed quantity — the screen shows both, the ladder uses this one.
    """
    quantity = line.qty_for_money if qty is None else Decimal(qty)
    gross = _money(quantity * line.rate)
    discount = _money(gross * line.discount_pct / 100)
    taxable = _money(gross - discount)
    gst = _money(taxable * line.gst_percent / 100)
    return {
        "line": line,
        "qty": quantity,
        "gross": gross,
        "discount": discount,
        "taxable": taxable,
        "gst": gst,
        "total": _money(taxable + gst),
    }


# ------------------------------------------------------------- the ladder

def bill_ladder(bill, po, lines, po_taxable, previous_recovered):
    """
    The full ladder for one bill. Pure: everything it needs is passed in.

    po_taxable          the work order's own taxable (PurchaseOrder.totals()),
                        the base the advance is spread over
    previous_recovered  advance already recovered on earlier approved bills
    """
    rows = [line_figures(line) for line in lines]
    gross = _money(sum((r["gross"] for r in rows), ZERO))
    discount = _money(sum((r["discount"] for r in rows), ZERO))
    taxable = _money(sum((r["taxable"] for r in rows), ZERO))
    gst = _money(sum((r["gst"] for r in rows), ZERO))

    invoice_value = _money(taxable + gst)
    deduction = _money(invoice_value * po.deduction_pct / 100)       # post-tax, as PO-TOTALS
    retention = _money(taxable * po.retention_pct / 100)             # on the work value, ex-GST

    advance_outstanding = max(ZERO, _money(po.mobilisation_advance - previous_recovered))
    if bill.is_final:
        advance_recovery = advance_outstanding
    elif po_taxable > ZERO and po.mobilisation_advance > ZERO:
        pro_rata = _money(taxable * po.mobilisation_advance / po_taxable)
        advance_recovery = min(advance_outstanding, pro_rata)
    else:
        advance_recovery = ZERO

    after = _money(invoice_value - deduction - retention - advance_recovery)
    payable = after.quantize(ONE_RUPEE, rounding=ROUND_HALF_UP)
    round_off = _money(payable - after)
    tds = _money(taxable * po.tds_pct / 100)

    cgst = _money(gst / 2)
    return {
        "bill": bill,
        "lines": rows,
        "line_count": len(rows),
        "gross": gross,
        "discount": discount,
        "taxable": taxable,
        "gst": gst,
        "cgst": cgst,
        "sgst": _money(gst - cgst),          # subtraction, so the halves tie exactly
        "invoice_value": invoice_value,
        "deduction": deduction,
        "retention": retention,
        "advance_outstanding": advance_outstanding,
        "advance_recovery": advance_recovery,
        "round_off": round_off,
        "payable": payable,
        "tds": tds,
        "net_payable": _money(payable - tds),
        "certified": all(line.certified_qty is not None for line in lines),
    }


def wo_ladders(po, bills, po_taxable=None):
    """
    Ladders for every bill on one work order, in sequence, carrying the advance
    recovered from one approved bill to the next.

    `bills` must be every bill on the order with `lines` prefetched. Returns
    {bill.id: ladder}.
    """
    po_taxable = po.totals()["taxable"] if po_taxable is None else po_taxable
    ladders, recovered = {}, ZERO
    for bill in sorted(bills, key=lambda b: b.sequence):
        ladder = bill_ladder(bill, po, list(bill.lines.all()), po_taxable, recovered)
        ladders[bill.id] = ladder
        if bill.status in RABill.COUNTED:
            recovered = _money(recovered + ladder["advance_recovery"])
    return ladders


def bill_figures(bill):
    """The ladder for one bill, on its own. Queries the order's other bills."""
    po = (PurchaseOrder.objects.prefetch_related("lines").get(pk=bill.purchase_order_id))
    bills = list(RABill.objects.filter(purchase_order=po).prefetch_related("lines"))
    return wo_ladders(po, bills)[bill.id]


def bulk_bill_figures(bills):
    """
    {bill.id: ladder} for any set of bills, across work orders, in a fixed
    number of queries. Fetches the WHOLE order's bills so the advance carry is
    right even when the caller filtered some bills out.
    """
    po_ids = {bill.purchase_order_id for bill in bills}
    if not po_ids:
        return {}
    orders = {po.id: po for po in
              PurchaseOrder.objects.filter(pk__in=po_ids).prefetch_related("lines")}
    every = defaultdict(list)
    for bill in RABill.objects.filter(purchase_order_id__in=po_ids).prefetch_related("lines"):
        every[bill.purchase_order_id].append(bill)
    out = {}
    for po_id, po_bills in every.items():
        out.update(wo_ladders(orders[po_id], po_bills))
    return out


# ------------------------------------------------------------- cumulative

def _sum(values):
    return _money(sum(values, ZERO))


def _wo_summary(po, bills, ladders, releases, payments, today):
    """One work order's cumulative position. Everything already fetched."""
    counted = [b for b in bills if b.status in RABill.COUNTED]
    approved_open = [b for b in bills if b.status == RABill.Status.APPROVED]
    paid_on_bill = defaultdict(Decimal)
    for payment in payments:
        if payment.ra_bill_id:
            paid_on_bill[payment.ra_bill_id] += payment.amount

    po_totals = po.totals()
    contract_value = po_totals["taxable"]
    certified_to_date = _sum(ladders[b.id]["taxable"] for b in counted)
    billed_to_date = _sum(ladders[b.id]["invoice_value"] for b in counted)
    retention_held = _sum(ladders[b.id]["retention"] for b in counted)
    retention_released = _sum(r.amount for r in releases)
    advance_recovered = _sum(ladders[b.id]["advance_recovery"] for b in counted)
    advance_paid = _sum(p.amount for p in payments if p.kind == VendorPayment.Kind.ADVANCE)
    paid_to_date = _sum(p.amount for p in payments)
    tds_withheld = _sum(p.tds_amount for p in payments)
    payable_now = _sum(max(ZERO, ladders[b.id]["net_payable"] - paid_on_bill[b.id])
                       for b in approved_open)

    end = dlp_end(po, bills)
    balance = _money(retention_held - retention_released)
    return {
        "po": po,
        "contract_value": contract_value,
        "order_value": po_totals["order_value"],
        "certified_to_date": certified_to_date,
        "remaining_value": _money(contract_value - certified_to_date),
        "billed_to_date": billed_to_date,
        "retention_held": retention_held,
        "retention_released": retention_released,
        "retention_balance": balance,
        "advance_agreed": po.mobilisation_advance,
        "advance_paid": advance_paid,
        "advance_recovered": advance_recovered,
        "advance_outstanding": max(ZERO, _money(po.mobilisation_advance - advance_recovered)),
        "paid_to_date": paid_to_date,
        "tds_withheld": tds_withheld,
        "payable_now": payable_now,
        "bill_count": len(bills),
        "open_bill": next((b for b in bills if b.is_open), None),
        "final_bill": next((b for b in bills if b.is_final and b.status in RABill.COUNTED), None),
        "dlp_end": end,
        "retention_eligible": _eligible(end, balance, today),
        "paid_on_bill": dict(paid_on_bill),
    }


def _line_rows(po, bills, ladders):
    """Per work-order line: ordered, certified to date, remaining."""
    certified = defaultdict(Decimal)
    for bill in bills:
        if bill.status in RABill.COUNTED:
            for line in bill.lines.all():
                if line.certified_qty is not None:
                    certified[line.po_line_id] += line.certified_qty
    rows = []
    for po_line in po.lines.all():
        done = certified[po_line.id]
        rows.append({
            "po_line": po_line,
            "quantity": po_line.quantity,
            "certified_to_date": done,
            "remaining": po_line.quantity - done,
        })
    return rows


def bulk_cumulative(orders, today=None):
    """
    {po.id: summary} for a set of work orders, each summary carrying the
    per-line rows under "lines" and the bill ladders under "ladders".

    Four queries whatever the count: bills, bill lines, releases, payments —
    plus the order lines the caller prefetched.
    """
    today = today or date.today()
    orders = list(orders)
    if not orders:
        return {}
    po_ids = [po.id for po in orders]
    bills = defaultdict(list)
    for bill in (RABill.objects.filter(purchase_order_id__in=po_ids)
                 .prefetch_related("lines").order_by("purchase_order_id", "sequence")):
        bills[bill.purchase_order_id].append(bill)
    releases = defaultdict(list)
    for release in (RetentionRelease.objects.filter(purchase_order_id__in=po_ids)
                    .select_related("released_by")):
        releases[release.purchase_order_id].append(release)
    payments = defaultdict(list)
    for payment in (VendorPayment.objects.filter(purchase_order_id__in=po_ids)
                    .select_related("ra_bill")):
        payments[payment.purchase_order_id].append(payment)

    out = {}
    for po in orders:
        po_bills = bills[po.id]
        ladders = wo_ladders(po, po_bills)
        summary = _wo_summary(po, po_bills, ladders, releases[po.id], payments[po.id], today)
        summary["bills"] = po_bills
        summary["ladders"] = ladders
        summary["lines"] = _line_rows(po, po_bills, ladders)
        summary["releases"] = releases[po.id]
        summary["payments"] = payments[po.id]
        out[po.id] = summary
    return out


def cumulative(po, today=None):
    """One work order's position. See bulk_cumulative for the keys."""
    if not hasattr(po, "_prefetched_objects_cache") or "lines" not in po._prefetched_objects_cache:
        po = PurchaseOrder.objects.prefetch_related("lines__bom_line__material").get(pk=po.pk)
    return bulk_cumulative([po], today=today)[po.id]


def certified_before(po, exclude_bill=None):
    """
    {po_line_id: Σ certified_qty} over the order's APPROVED and PAID bills —
    what an incoming certification is checked against.
    """
    done = defaultdict(Decimal)
    counted = RABill.objects.filter(purchase_order=po, status__in=RABill.COUNTED)
    if exclude_bill is not None:
        counted = counted.exclude(pk=exclude_bill.pk)
    for bill in counted.prefetch_related("lines"):
        for line in bill.lines.all():
            if line.certified_qty is not None:
                done[line.po_line_id] += line.certified_qty
    return done


# ------------------------------------------------------------- DLP & retention

def dlp_end(po, bills=None):
    """
    The defect liability period ends `dlp_months` after the FINAL bill's
    approval. None until a final bill has been approved — before that there is
    no date to count from, and an invented one would release retention early.
    """
    if bills is None:
        bills = list(RABill.objects.filter(purchase_order=po))
    final = next((b for b in bills if b.is_final and b.status in RABill.COUNTED
                  and b.approved_at), None)
    if final is None:
        return None
    return _add_months(final.approved_at.date(), po.dlp_months)


def _add_months(day, months):
    month = day.month - 1 + months
    year = day.year + month // 12
    month = month % 12 + 1
    last = [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
            31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
    return date(year, month, min(day.day, last))


def _eligible(end, balance, today):
    return end is not None and today >= end and balance > ZERO


def retention_eligible(po, today=None):
    """Whether retention may be released today: DLP over and a balance held."""
    today = today or date.today()
    summary = cumulative(po, today=today)
    return summary["retention_eligible"]


# ------------------------------------------------------------- vendor invoices

def invoice_settled(invoice, payments):
    """
    What has been applied to an invoice: money paid PLUS TDS withheld. The TDS
    discharges the vendor's invoice too — they get the credit from the
    department — so an invoice is settled when the two together reach its total.
    """
    return _sum(p.amount + p.tds_amount for p in payments if p.vendor_invoice_id == invoice.id)


def invoice_status(invoice, settled):
    if settled <= ZERO:
        return "open"
    if settled < invoice.total:
        return "part_paid"
    return "settled"


def bulk_invoice_figures(invoices, payments=None):
    """{invoice.id: {settled, balance, status}} for a set of invoices, one query."""
    invoices = list(invoices)
    if not invoices:
        return {}
    if payments is None:
        payments = list(VendorPayment.objects.filter(vendor_invoice_id__in=[i.id for i in invoices]))
    by_invoice = defaultdict(Decimal)
    for payment in payments:
        if payment.vendor_invoice_id:
            by_invoice[payment.vendor_invoice_id] += payment.amount + payment.tds_amount
    out = {}
    for invoice in invoices:
        settled = _money(by_invoice[invoice.id])
        out[invoice.id] = {
            "settled": settled,
            "balance": max(ZERO, _money(invoice.total - settled)),
            "status": invoice_status(invoice, settled),
        }
    return out


def po_settlement(po, invoices=None, payments=None):
    """
    Where a purchase order stands: what we agreed, what was invoiced, what was
    paid, and what is left.

        net_payable      the ORDER's net payable, from PurchaseOrder.totals()
        invoiced_total   Σ vendor invoice totals (their figures)
        paid_total       Σ payment.amount on this order, every kind
        tds_withheld     Σ payment.tds_amount
        balance          net_payable − paid_total — what is still to pay
        over_invoiced    invoiced_total > order_value: the three-way flag at
                         amount level (quantities are not on an invoice)
    """
    if invoices is None:
        invoices = list(VendorInvoice.objects.filter(purchase_order=po))
    if payments is None:
        payments = list(VendorPayment.objects.filter(purchase_order=po))
    totals = po.totals()
    paid_total = _sum(p.amount for p in payments)
    tds_withheld = _sum(p.tds_amount for p in payments)
    invoiced_total = _sum(i.total for i in invoices)
    invoice_rows = bulk_invoice_figures(invoices, payments)
    open_balance = _sum(row["balance"] for row in invoice_rows.values())
    advance_paid = _sum(p.amount for p in payments if p.kind == VendorPayment.Kind.ADVANCE)
    return {
        "po": po,
        "order_value": totals["order_value"],
        "net_payable": totals["net_payable"],
        "order_tds": totals["tds"],
        "invoiced_total": invoiced_total,
        "invoiced_taxable": _sum(i.taxable for i in invoices),
        "invoiced_gst": _sum(i.gst for i in invoices),
        "invoice_count": len(invoices),
        "paid_total": paid_total,
        "tds_withheld": tds_withheld,
        "advance_paid": advance_paid,
        "balance": _money(totals["net_payable"] - paid_total),
        "invoice_balance": open_balance,
        "over_invoiced": invoiced_total > totals["order_value"],
        "invoices": invoice_rows,
        "settled": paid_total >= totals["net_payable"],
    }


def bulk_po_settlement(orders):
    """{po.id: po_settlement} for a set of purchase orders in two queries."""
    orders = list(orders)
    if not orders:
        return {}
    po_ids = [po.id for po in orders]
    invoices, payments = defaultdict(list), defaultdict(list)
    for invoice in VendorInvoice.objects.filter(purchase_order_id__in=po_ids):
        invoices[invoice.purchase_order_id].append(invoice)
    for payment in VendorPayment.objects.filter(purchase_order_id__in=po_ids):
        payments[payment.purchase_order_id].append(payment)
    return {po.id: po_settlement(po, invoices[po.id], payments[po.id]) for po in orders}


# ------------------------------------------------------------- registers

def payments_total(payments):
    """Totals for a register of payments: amount and TDS, in Python."""
    payments = list(payments)
    return {
        "count": len(payments),
        "amount": _sum(p.amount for p in payments),
        "tds": _sum(p.tds_amount for p in payments),
    }
