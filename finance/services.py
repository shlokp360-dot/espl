"""
Every write in the finance module: atomic, refusing with a message for the
person rather than the log.

>>> ANCHOR: FIN-SERVICES <<<
WHAT THIS FILE IS FOR
    create_ra_bill / update_bill_lines / certify / approve / discard_draft
    record_ra_payment            money against an approved RA bill
    release_retention            after the DLP, or overridden with a note
    record_vendor_invoice        a supplier's invoice on a material PO
    record_invoice_payment       money against that invoice
    record_advance               money before any bill or invoice

WHAT DEPENDS ON IT
    finance/views.py calls these and nothing else writes a finance row.

THE RA BILL LIFECYCLE — strictly sequential
    DRAFT → CERTIFIED → APPROVED → PAID

    Draft      the contractor's claim; claimed and certified quantities editable
    Certified  every line carries a certified quantity within the order's
               remaining quantity; still editable, re-certifies on save
    Approved   LOCKED. Receipts written for the certified quantities. If the
               bill is final the work order is marked completed
    Paid       Σ payments on the bill ≥ its net payable. When every bill on a
               work order is paid and a final bill exists, the order is paid

⚠ WHAT MOVES THE WORK ORDER. Its Completed and Paid steps come from here once
  it has an RA bill — see ANCHOR: RA-BILL-OWNS-THE-WO in projects/po_service.
  Approving the final bill sets the same fields mark_delivered sets, WITHOUT
  calling record_full_delivery: the receipts are the certified quantities, and
  a full-quantity receipt on top of them would double what the BOM shows.
"""
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from masters.models import DocumentType
from projects.bom_models import NumberSeries, PurchaseOrder, Receipt, _money
from projects.receipts import record_receipt

from . import calc
from .models import RABill, RABillLine, RetentionRelease, VendorInvoice, VendorPayment

ZERO = Decimal("0")
NUMBER_WIDTH = 6


class FinanceError(Exception):
    """Something the user needs to fix, phrased for the user."""


def _number(prefix, key):
    """RA-000001 · VB-000001 · PV-000001 — from NumberSeries, never from max()."""
    return f"{prefix}-{NumberSeries.take_next(key):0{NUMBER_WIDTH}d}"


def _decimal(value, what):
    try:
        amount = Decimal(str(value).strip().replace(",", ""))
    except (InvalidOperation, ValueError, AttributeError):
        raise FinanceError(f"{what} could not be read as a number.")
    if amount < ZERO:
        raise FinanceError(f"{what} cannot be negative.")
    return amount


def _qty(value, what):
    return _decimal(value, what).quantize(Decimal("0.001"))


# ================================================================ RA bills

def _require_work_order(po):
    if po.document_type != DocumentType.WO:
        raise FinanceError(f"{po.number} is a purchase order. RA bills are raised on work "
                           f"orders only — record a vendor invoice against it instead.")


@transaction.atomic
def create_ra_bill(po, user, lines, is_final=False, bill_date=None, contractor_ref="",
                   period_from=None, period_to=None, note=""):
    """
    A new bill on a work order, from the contractor's claim.

    `lines` is {po_line_id: claimed_qty}. Lines with no claim are left off the
    bill; a bill with no lines is refused.

    Refuses on: a purchase order, a work order not yet approved, a bill already
    open on this order, or an order whose final bill has been approved.
    """
    _require_work_order(po)
    if po.status == PurchaseOrder.Status.DRAFT:
        raise FinanceError(f"{po.number} is still a draft. Approve the work order before "
                           f"raising a bill on it.")
    existing = list(RABill.objects.filter(purchase_order=po))
    open_bill = next((b for b in existing if b.is_open), None)
    if open_bill is not None:
        raise FinanceError(f"{open_bill.number} is still {open_bill.get_status_display().lower()} "
                           f"on {po.number}. Approve or discard it before raising another.")
    final = next((b for b in existing if b.is_final and b.status in RABill.COUNTED), None)
    if final is not None:
        raise FinanceError(f"{final.number} was the final bill on {po.number} and it is "
                           f"approved. No further bill can be raised.")

    po_lines = {line.id: line for line in po.lines.all()}
    claims = []
    for raw_id, raw_qty in (lines or {}).items():
        line_id = int(raw_id)
        if line_id not in po_lines:
            raise FinanceError("One of the lines is not on this work order.")
        qty = _qty(raw_qty, "A claimed quantity")
        if qty > ZERO:
            claims.append((po_lines[line_id], qty))
    if not claims:
        raise FinanceError("Nothing was claimed. Type a quantity on at least one line.")

    bill = RABill.objects.create(
        purchase_order=po,
        number=_number("RA", "ra_bill"),
        sequence=len(existing) + 1,
        bill_date=bill_date or date.today(),
        contractor_ref=(contractor_ref or "").strip()[:60],
        period_from=period_from or None,
        period_to=period_to or None,
        is_final=bool(is_final),
        note=(note or "").strip()[:300],
        created_by=user,
    )
    RABillLine.objects.bulk_create([
        RABillLine(ra_bill=bill, po_line=po_line, claimed_qty=qty,
                   # Frozen copies — the bill must keep saying what it said.
                   rate=po_line.rate, gst_percent=po_line.gst_percent,
                   discount_pct=po_line.discount_pct)
        for po_line, qty in claims
    ])
    return bill


def _check_cumulative(bill, certified):
    """
    >>> ANCHOR: FIN-CUMULATIVE <<<
    Cumulative certified — earlier approved bills PLUS this one — may not exceed
    the work order line's quantity. Refused with the line named and the excess
    stated, because "over-certified" without a number sends the engineer back
    to a calculator.
    """
    before = calc.certified_before(bill.purchase_order, exclude_bill=bill)
    problems = []
    for line in bill.lines.select_related("po_line__bom_line__material"):
        qty = certified.get(line.id)
        if qty is None:
            continue
        total = before[line.po_line_id] + qty
        if total > line.po_line.quantity:
            material = line.po_line.bom_line.material
            excess = total - line.po_line.quantity
            problems.append(
                f"{material.code} {material.name}: {before[line.po_line_id]} already certified "
                f"+ {qty} now = {total}, which is {excess} over the order's "
                f"{line.po_line.quantity}.")
    if problems:
        raise FinanceError("Not certified. " + " ".join(problems))


@transaction.atomic
def update_bill_lines(bill, claimed=None, certified=None, remarks=None, is_final=None,
                      contractor_ref=None, bill_date=None, period_from=None, period_to=None,
                      note=None):
    """
    Save what was typed on an open bill. Certified quantities are checked
    against the order's remaining quantity here too, so a bad figure is refused
    when it is typed rather than when somebody presses Certify.
    """
    if not bill.is_editable:
        raise FinanceError(f"{bill.number} is {bill.get_status_display().lower()} and locked.")
    claimed = {int(k): _qty(v, "A claimed quantity") for k, v in (claimed or {}).items()}
    typed = {}
    for key, value in (certified or {}).items():
        value = "" if value is None else str(value).strip()
        typed[int(key)] = None if value == "" else _qty(value, "A certified quantity")

    for line in bill.lines.all():
        if line.id in claimed:
            line.claimed_qty = claimed[line.id]
        if line.id in typed:
            line.certified_qty = typed[line.id]
        if remarks and line.id in remarks:
            line.remark = (remarks[line.id] or "").strip()[:200]
        line.save()

    if is_final is not None:
        bill.is_final = bool(is_final)
    if contractor_ref is not None:
        bill.contractor_ref = contractor_ref.strip()[:60]
    if bill_date is not None:
        bill.bill_date = bill_date
    if period_from is not None:
        bill.period_from = period_from or None
    if period_to is not None:
        bill.period_to = period_to or None
    if note is not None:
        bill.note = note.strip()[:300]
    bill.save()

    _check_cumulative(bill, {line.id: line.certified_qty for line in bill.lines.all()
                             if line.certified_qty is not None})
    return bill


@transaction.atomic
def certify(bill, user, certified=None):
    """
    Our engineer's quantities, on every line. Sets CERTIFIED.

    `certified` is {line_id: qty}; leave it out to certify what is already typed.
    Every line must carry a figure — an uncertified line is not "zero", it is
    "not looked at", and a bill with one of those cannot be approved.
    """
    if bill.status not in RABill.OPEN:
        raise FinanceError(f"{bill.number} is {bill.get_status_display().lower()}. Only an open "
                           f"bill can be certified.")
    if certified:
        update_bill_lines(bill, certified=certified)
    lines = list(bill.lines.all())
    missing = [line for line in lines if line.certified_qty is None]
    if missing:
        raise FinanceError(f"{len(missing)} line{'s have' if len(missing) > 1 else ' has'} no "
                           f"certified quantity yet. Type one on every line — 0 if nothing "
                           f"was done.")
    _check_cumulative(bill, {line.id: line.certified_qty for line in lines})

    bill.status = RABill.Status.CERTIFIED
    bill.certified_at = timezone.now()
    bill.certified_by = user
    bill.save(update_fields=["status", "certified_at", "certified_by", "updated_at"])
    return bill


@transaction.atomic
def approve(bill, user):
    """
    Commit the bill. Locks it, writes receipts for the certified quantities
    and — on the final bill — marks the work order completed.

    >>> ANCHOR: TASK-MODULE <<<
    Receipts go through projects.receipts.record_receipt with source RA_BILL,
    the single door for received quantities. A zero certified line writes no
    receipt: record_receipt refuses zero, and nothing arrived.
    """
    if bill.status != RABill.Status.CERTIFIED:
        raise FinanceError(f"{bill.number} is {bill.get_status_display().lower()}. Only a "
                           f"certified bill can be approved.")
    lines = list(bill.lines.select_related("po_line"))
    if any(line.certified_qty is None for line in lines):
        raise FinanceError(f"{bill.number} has a line with no certified quantity.")
    _check_cumulative(bill, {line.id: line.certified_qty for line in lines})

    po = bill.purchase_order
    if po.status not in (PurchaseOrder.Status.APPROVED, PurchaseOrder.Status.DELIVERED):
        raise FinanceError(f"{po.number} is {po.get_status_display().lower()}, so a bill on it "
                           f"cannot be approved.")

    now = timezone.now()
    bill.status = RABill.Status.APPROVED
    bill.approved_at = now
    bill.approved_by = user
    bill.save(update_fields=["status", "approved_at", "approved_by", "updated_at"])

    for line in lines:
        if line.certified_qty > ZERO:
            record_receipt(line.po_line, line.certified_qty, received_on=bill.bill_date,
                           source=Receipt.Source.RA_BILL, note=f"{bill.number}")

    if bill.is_final and po.status == PurchaseOrder.Status.APPROVED:
        # The same fields po_service.mark_delivered sets, without its receipts.
        po.status = PurchaseOrder.Status.DELIVERED
        po.delivered_at = now
        po.delivered_by = user
        po.save(update_fields=["status", "delivered_at", "delivered_by", "updated_at"])
    return bill


@transaction.atomic
def discard_draft(bill):
    """Throw an open bill away. Its number is not reused."""
    if not bill.is_open:
        raise FinanceError(f"{bill.number} is {bill.get_status_display().lower()} and cannot "
                           f"be discarded.")
    if bill.payments.exists():
        raise FinanceError(f"{bill.number} has a payment against it and cannot be discarded.")
    number = bill.number
    bill.delete()
    return number


def _payment(po, user, kind, amount, paid_on, mode, reference, tds_amount, note,
             ra_bill=None, vendor_invoice=None):
    amount = _money(_decimal(amount, "The amount"))
    tds = _money(_decimal(tds_amount or 0, "The TDS amount"))
    if amount <= ZERO and tds <= ZERO:
        raise FinanceError("The amount must be more than zero.")
    if mode not in VendorPayment.Mode.values:
        raise FinanceError("Pick a payment mode.")
    return VendorPayment.objects.create(
        number=_number("PV", "vendor_payment"),
        vendor=po.vendor, purchase_order=po, ra_bill=ra_bill, vendor_invoice=vendor_invoice,
        kind=kind, paid_on=paid_on or date.today(), amount=amount, tds_amount=tds,
        mode=mode, reference=(reference or "").strip()[:60], note=(note or "").strip()[:300],
        recorded_by=user)


@transaction.atomic
def record_ra_payment(bill, user, amount, paid_on=None, mode=VendorPayment.Mode.NEFT,
                      reference="", tds_amount=0, note=""):
    """
    Money against an approved bill. Part payments are allowed; the bill is
    PAID once Σ amount ≥ its net payable. Refuses more than is left to pay.
    """
    if bill.status != RABill.Status.APPROVED:
        raise FinanceError(f"{bill.number} is {bill.get_status_display().lower()}. Only an "
                           f"approved, unpaid bill takes a payment.")
    ladder = calc.bill_figures(bill)
    already = _money(sum((p.amount for p in bill.payments.all()), ZERO))
    left = _money(ladder["net_payable"] - already)
    amount = _money(_decimal(amount, "The amount"))
    if amount > left:
        raise FinanceError(f"{bill.number} has {left} left to pay; {amount} is more than that.")

    payment = _payment(bill.purchase_order, user, VendorPayment.Kind.RA_BILL, amount, paid_on,
                       mode, reference, tds_amount, note, ra_bill=bill)

    if _money(already + amount) >= ladder["net_payable"]:
        bill.status = RABill.Status.PAID
        bill.paid_at = timezone.now()
        bill.save(update_fields=["status", "paid_at", "updated_at"])
        _settle_work_order(bill.purchase_order, user)
    return payment


def _settle_work_order(po, user):
    """Every bill paid and a final bill approved → the work order is PAID."""
    bills = list(RABill.objects.filter(purchase_order=po))
    if not bills or not any(b.is_final for b in bills):
        return
    if any(b.status != RABill.Status.PAID for b in bills):
        return
    if po.status != PurchaseOrder.Status.DELIVERED:
        return
    po.status = PurchaseOrder.Status.PAID
    po.paid_at = timezone.now()
    po.paid_by = user
    po.save(update_fields=["status", "paid_at", "paid_by", "updated_at"])


@transaction.atomic
def release_retention(po, user, amount, released_on=None, reference="", note="", override=False):
    """
    Hand retention back. Refuses more than the balance, and refuses before the
    DLP has run unless `override` is set WITH a note saying why — that path is
    the Admin's, and the note is what the auditor reads.

    Writes the RetentionRelease ledger row AND a VendorPayment of kind
    retention_release, because the money left the bank and the payments
    register is what goes to Tally.
    """
    _require_work_order(po)
    summary = calc.cumulative(po, today=released_on or date.today())
    amount = _money(_decimal(amount, "The amount"))
    if amount <= ZERO:
        raise FinanceError("The amount must be more than zero.")
    if amount > summary["retention_balance"]:
        raise FinanceError(f"{po.number} holds {summary['retention_balance']} retention; "
                           f"{amount} is more than that.")
    if not summary["retention_eligible"]:
        end = summary["dlp_end"]
        reason = (f"its defect liability period runs until {end:%d/%m/%Y}" if end
                  else "no final bill has been approved yet, so the defect liability period "
                       "has not started")
        if not override:
            raise FinanceError(f"Retention on {po.number} cannot be released — {reason}. "
                               f"An Admin can override this with a note.")
        if not (note or "").strip():
            raise FinanceError("An early release needs a note saying why.")

    release = RetentionRelease.objects.create(
        purchase_order=po, amount=amount, released_on=released_on or date.today(),
        released_by=user, reference=(reference or "").strip()[:60],
        note=(note or "").strip()[:300])
    _payment(po, user, VendorPayment.Kind.RETENTION_RELEASE, amount, release.released_on,
             VendorPayment.Mode.NEFT, reference, 0, note)
    return release


# ================================================================ purchase orders

def _require_purchase_order(po):
    if po.document_type == DocumentType.WO:
        raise FinanceError(f"{po.number} is a work order. Contractors are billed through RA "
                           f"bills, not vendor invoices.")
    if po.status == PurchaseOrder.Status.DRAFT:
        raise FinanceError(f"{po.number} is still a draft. Approve it first.")


@transaction.atomic
def record_vendor_invoice(po, user, vendor_invoice_no, invoice_date, taxable, gst, total, note=""):
    """
    A supplier's invoice, typed from paper. total must equal taxable + gst to
    the paisa — the one arithmetic check, because a typo here is a typo in Tally.
    """
    _require_purchase_order(po)
    vendor_invoice_no = (vendor_invoice_no or "").strip()
    if not vendor_invoice_no:
        raise FinanceError("Type the vendor's invoice number.")
    if VendorInvoice.objects.filter(purchase_order__vendor=po.vendor,
                                    vendor_invoice_no__iexact=vendor_invoice_no).exists():
        raise FinanceError(f"Invoice {vendor_invoice_no} from {po.vendor.name} is already "
                           f"recorded.")
    taxable = _money(_decimal(taxable, "The taxable value"))
    gst = _money(_decimal(gst, "The GST"))
    total = _money(_decimal(total, "The total"))
    if total != _money(taxable + gst):
        raise FinanceError(f"Total {total} is not taxable {taxable} + GST {gst} = "
                           f"{_money(taxable + gst)}. Check the figures against the invoice.")
    if total <= ZERO:
        raise FinanceError("An invoice for nothing cannot be recorded.")
    return VendorInvoice.objects.create(
        purchase_order=po, number=_number("VB", "vendor_invoice"),
        vendor_invoice_no=vendor_invoice_no[:60], invoice_date=invoice_date or date.today(),
        taxable=taxable, gst=gst, total=total, note=(note or "").strip()[:300], recorded_by=user)


@transaction.atomic
def record_invoice_payment(invoice, user, amount, paid_on=None, mode=VendorPayment.Mode.NEFT,
                           reference="", tds_amount=0, note=""):
    """Money against a vendor invoice. Part payments allowed; not more than is left."""
    po = invoice.purchase_order
    figures = calc.bulk_invoice_figures([invoice])[invoice.id]
    amount = _money(_decimal(amount, "The amount"))
    tds = _money(_decimal(tds_amount or 0, "The TDS amount"))
    if _money(amount + tds) > figures["balance"]:
        raise FinanceError(f"{invoice.number} has {figures['balance']} left to settle; "
                           f"{_money(amount + tds)} (amount plus TDS) is more than that.")
    payment = _payment(po, user, VendorPayment.Kind.AGAINST_INVOICE, amount, paid_on, mode,
                       reference, tds, note, vendor_invoice=invoice)
    _settle_purchase_order(po, user)
    return payment


@transaction.atomic
def record_advance(po, user, amount, paid_on=None, mode=VendorPayment.Mode.NEFT, reference="",
                   tds_amount=0, note=""):
    """Money out before any bill or invoice — on a purchase order or a work order."""
    if po.status == PurchaseOrder.Status.DRAFT:
        raise FinanceError(f"{po.number} is still a draft. Approve it before paying an advance.")
    payment = _payment(po, user, VendorPayment.Kind.ADVANCE, amount, paid_on, mode, reference,
                       tds_amount, note)
    if po.document_type == DocumentType.PO:
        _settle_purchase_order(po, user)
    return payment


def _settle_purchase_order(po, user):
    """Σ payments ≥ the order's net payable, and it is delivered → PAID."""
    if po.document_type != DocumentType.PO or po.status != PurchaseOrder.Status.DELIVERED:
        return
    if calc.po_settlement(po)["settled"]:
        # The same fields po_service.mark_paid sets.
        po.status = PurchaseOrder.Status.PAID
        po.paid_at = timezone.now()
        po.paid_by = user
        po.save(update_fields=["status", "paid_at", "paid_by", "updated_at"])
