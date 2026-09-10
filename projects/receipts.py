"""
Recording material that has arrived on site.

>>> ANCHOR: TASK-MODULE <<<
THIS FILE IS THE CONNECTION POINT FOR THE FUTURE TASK MANAGEMENT MODULE.

    Today, `record_receipt` is called when a purchase order is marked Delivered
    — one receipt per line, for the full ordered quantity.

    Later, the task management module will record what actually turned up on
    site, and it will call THIS SAME FUNCTION. It must not reach into the BOM,
    or create Receipt rows directly, or adjust stock itself.

    Why insist on one door: the BOM's "received" figure is the sum of these
    rows. Anything that writes them by another route produces numbers nobody
    can explain — and by the time someone notices, the wrong figure has been on
    a purchase order for a month.

WHAT DEPENDS ON IT
    bom_calc.received_qty() sums what this function writes. That is the whole
    contract.
"""
from datetime import date
from decimal import Decimal

from django.db import transaction

from .bom_models import Receipt

ZERO = Decimal("0")


@transaction.atomic
def record_receipt(po_line, quantity, received_on=None, source=Receipt.Source.MANUAL, note=""):
    """
    Record that `quantity` of `po_line` arrived.

    THE ONLY WAY A RECEIVED QUANTITY EVER CHANGES.

    Args:
        po_line:     the PurchaseOrderLine that was delivered against
        quantity:    how much arrived. Partial deliveries are normal — call this
                     again when the rest turns up, and each gets its own date
        received_on: defaults to today
        source:      MANUAL now; TASK_MODULE when that module calls in
        note:        free text, e.g. "short by 2 bags, driver noted"

    Returns the Receipt.

    Raises ValueError on a quantity of zero or less. Deliberately: a zero
    receipt records nothing but looks like a delivery happened, and an attempt
    to record one is a bug in the caller, not a normal event.

    NOT ENFORCED, on purpose: receiving more than was ordered. Over-delivery
    happens — a vendor rounds up to a full bundle — and refusing it would leave
    someone unable to record what is physically on site. The BOM shows received
    exceeding ordered, which is visible and true.
    """
    amount = Decimal(str(quantity))
    if amount <= ZERO:
        raise ValueError(
            f"Cannot record a receipt of {quantity}. A receipt records material that arrived, "
            f"so the quantity must be more than zero."
        )

    return Receipt.objects.create(
        po_line=po_line,
        quantity=amount,
        received_on=received_on or date.today(),
        source=source,
        note=note,
    )


@transaction.atomic
def record_full_delivery(purchase_order, received_on=None, note=""):
    """
    Record every line on a purchase order as fully delivered.

    Called when someone marks a PO Delivered by hand — the honest interpretation
    of that click is "all of it arrived".

    Skips lines that already have receipts, so pressing it twice cannot double
    the received quantity. Returns the receipts it created, which may be empty.
    """
    created = []
    for line in purchase_order.lines.all():
        already = sum((r.quantity for r in line.receipts.all()), ZERO)
        outstanding = line.quantity - already
        if outstanding > ZERO:
            created.append(record_receipt(line, outstanding, received_on=received_on, note=note))
    return created
