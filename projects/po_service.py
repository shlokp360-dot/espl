"""
Creating and moving purchase orders through their lifecycle.

WHAT THIS FILE IS FOR
    generate_purchase_orders   BOM -> one PO per vendor
    approve / mark_delivered / mark_paid
    delete_draft

WHAT DEPENDS ON IT
    The PO screen calls these. Nothing else should change a PO's status or
    create its lines.

THE LIFECYCLE — strictly sequential
    DRAFT -> APPROVED -> DELIVERED -> PAID

    Draft      editable, deletable
    Approved   LOCKED. No changes at all. Sends the PO to the vendor on
               WhatsApp, and captures the vendor's GSTIN if it is missing
    Delivered  records what arrived, through receipts.record_receipt
    Paid       marked when money goes out

    ⚠ Saahil's call over independent flags. Known consequence: an advance paid
    before delivery cannot reach PAID without first marking DELIVERED. The risk
    is someone marking DELIVERED early to unblock a payment, which writes
    received quantities for material that has not arrived. Watch for it in use;
    do not redesign pre-emptively.
"""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from masters.models import CompanyProfile, DocumentType, VendorRate, gstin_format
from .bom_models import NumberSeries, PurchaseOrder, PurchaseOrderLine, _money
from .receipts import record_full_delivery

ZERO = Decimal("0")


class POError(Exception):
    """Something the user needs to fix, phrased for the user rather than the log."""


# Six digits: PO-000001 through PO-999999. At a few hundred orders a year that
# is centuries of headroom, and every number is the same width, so they sort
# and line up in a column.
#
# It cannot run out. Python pads to a MINIMUM width rather than truncating, so
# order one million would simply be PO-1000000 — one character wider, still
# unique, still correct. The database column allows 20 characters.
PO_NUMBER_WIDTH = 6


def next_po_number():
    """
    PO-000001, PO-000002, ...

    Comes from a counter that only ever increases — NOT from the highest number
    already in the table. That distinction matters: unapproved orders are meant
    to be thrown away, and deriving the number from existing rows meant deleting
    PO-000001 handed the same number to the next order. Two different documents
    would then share an identity, one of them possibly already sent to a vendor.

    A gap in the sequence is fine and means an order was discarded. A repeat is
    not. Caught by a test, not by reading the code.
    """
    return f"PO-{NumberSeries.take_next('purchase_order'):0{PO_NUMBER_WIDTH}d}"


def orderable_figures(bom):
    """
    Every line on the BOM, with its figures, fetched in bulk.

    ⚠ WORKED OUT ONCE PER PRESS OF THE BUTTON, then reused by both the
    discontinued check and the generation itself. Doing it twice on a 6,400-line
    BOM cost several thousand queries and several seconds for no gain.
    """
    from . import bom_calc
    return bom_calc.figures_for(
        bom.lines.select_related("vendor", "material", "activity").all())


def discontinued_lines(bom, figures=None):
    """
    Every line about to be ordered that names something switched off.

    >>> ANCHOR: DISCONTINUED-BLOCK <<<
    Deactivating a material or a vendor means "we have stopped using this". Up
    to now that only removed it from the pickers — a line set up months ago kept
    its vendor, and Post POs would happily raise a real order for a discontinued
    product from a supplier the company no longer deals with.

    Saahil's call, 9 Aug 2026: block the posting outright and name the lines.
    His reason, in his words: the base-level user "is not that smart and may
    create a PO with a discontinued product". A warning that can be clicked past
    is not protection for that person.

    Returns a list of (activity, material, vendor, reason) — enough for a message
    that says exactly where to go and what to fix, rather than "something is
    wrong somewhere on this BOM". The reason itself comes from
    bom_calc.discontinued_reason, so this refusal and the red flag on the screen
    can never disagree.

    Only lines that WOULD be ordered are checked. A discontinued material with
    nothing to order is not a problem; it is history sitting quietly on the
    sheet, which is exactly what deactivation is for.
    """
    from . import bom_calc

    figures = orderable_figures(bom) if figures is None else figures

    found = []
    for figure in figures:
        line = figure["line"]
        if line.vendor is None or figure["order_qty"] <= ZERO:
            continue
        reason = bom_calc.discontinued_reason(line)      # the same rule the screen flags with
        if reason:
            found.append((line.activity, line.material, line.vendor, reason))
    return found


def preview_purchase_orders(bom):
    """
    What pressing Post POs WOULD create. Writes nothing.

    >>> ANCHOR: PO-PREVIEW <<<
    This is the equivalent of SAP's Check: every calculation and every
    validation runs, the result is reported, and not a single row is written.
    The person looks at it and then decides.

    Saahil asked for it after working out the scale — sixteen activities of
    three to four hundred materials. At that size a button that silently creates
    a dozen documents is not a button anyone should trust.

    Returns:
        groups   one per vendor, each {vendor, lines, quantity, basic, gst, total,
                 blocked} — `blocked` names a discontinued material or vendor
        skipped  lines with a quantity typed but NO VENDOR. Nothing is raised for
                 them (Saahil's rule: no vendor, no purchase order) but they are
                 reported so they cannot go unnoticed
    """
    from . import bom_calc

    groups, skipped = {}, []
    for figure in orderable_figures(bom):
        line = figure["line"]
        if figure["order_qty"] <= ZERO:
            continue                        # nobody typed a quantity — not an event
        if line.vendor is None:
            skipped.append(figure)
            continue

        group = groups.setdefault(line.vendor, {
            "vendor": line.vendor, "lines": [], "quantity": ZERO,
            "basic": ZERO, "gst": ZERO, "total": ZERO, "blocked": [],
        })
        gst_percent = ZERO if line.vendor.is_unregistered else line.material.gst_percent
        basic = figure["order_qty"] * figure["vendor_rate"]
        gst = basic * gst_percent / 100

        group["lines"].append({**figure, "gst_percent": gst_percent,
                               "basic": basic, "gst": gst, "total": basic + gst})
        group["quantity"] += figure["order_qty"]
        group["basic"] += basic
        group["gst"] += gst
        group["total"] += basic + gst

        reason = bom_calc.discontinued_reason(line)
        if reason:
            group["blocked"].append((line, reason))

    ordered = sorted(groups.values(), key=lambda g: g["vendor"].code)
    return ordered, skipped


@transaction.atomic
def generate_purchase_orders(bom, user=None, vendor_ids=None):
    """
    Turn everything orderable on the BOM into purchase orders — one per vendor.

    A line is orderable when it has a vendor AND a quantity somebody typed.
    ⚠ NO VENDOR, NO PURCHASE ORDER — Saahil's rule, 9 Aug 2026. A blank vendor
    means the buyer has not decided yet, so nothing is raised and nothing is
    assumed. The preview reports those lines so they are not invisible.

    `vendor_ids` limits generation to the vendors ticked on the preview. Leave
    it out and every vendor with something to order is included.

    ⚠ REFUSES ENTIRELY if any orderable line names a discontinued material or a
    discontinued vendor. Nothing is raised — not even the good lines. Saahil's
    call: raising the rest and mentioning the problem in passing means the
    missing lines are never noticed by the person most likely to miss them.

    ⚠ ALWAYS CREATES NEW POs. Never appends to a vendor's existing draft.
    Saahil's call: "they can always delete the old ones that are not approved."
    Each number is then a clean record of one batch.

    ⚠ NOTHING IS WRITTEN TO THE BOM. The ordered quantity is recorded on the PO
    line and nowhere else, so the BOM's "in draft" figure updates simply because
    there is now a draft PO line to add up. There is no second copy to keep in
    step. Press the button again and nothing happens, because the quantity to
    order has already fallen to zero.

    Returns the purchase orders created, in vendor-code order.
    Raises POError, naming every offending line, when something is discontinued.
    """
    from . import bom_calc

    # Once, for the whole BOM. Both the check below and the grouping after it
    # read these same figures.
    figures = orderable_figures(bom)

    # Only judge what is actually being created. A discontinued line belonging
    # to a vendor nobody ticked must not block the vendors they did tick.
    relevant = (figures if vendor_ids is None
                else [f for f in figures if f["line"].vendor_id in vendor_ids])
    blocked = discontinued_lines(bom, figures=relevant)
    if blocked:
        detail = "\n".join(
            f"    {activity.name} → {material.code} {material.name} · "
            f"{vendor.code} {vendor.name} — {reason}"
            for activity, material, vendor, reason in blocked)
        raise POError(
            f"Nothing was ordered. {len(blocked)} line"
            f"{' names' if len(blocked) == 1 else 's name'} something that has been switched off:\n"
            f"{detail}\n"
            f"    Pick a different material or vendor on those lines, or set the order quantity to "
            f"zero. If it really should still be bought, switch it back on in the master."
        )

    by_vendor = {}
    for figure in figures:
        line = figure["line"]
        if line.vendor is None or figure["order_qty"] <= ZERO:
            continue
        if vendor_ids is not None and line.vendor_id not in vendor_ids:
            continue                        # not ticked on the preview
        by_vendor.setdefault(line.vendor, []).append(figure)

    # >>> ANCHOR: DOC-TERMS <<<
    # Fetched once, outside the loop, rather than once per vendor.
    company = CompanyProfile.get_solo()

    orders, consumed = [], []
    for vendor in sorted(by_vendor, key=lambda v: v.code):
        # >>> ANCHOR: DOCUMENT-TYPE <<<
        # THE VENDOR DECIDES WHAT KIND OF DOCUMENT THIS IS. A supplier gets a
        # purchase order, a labour contractor a work order. Because the BOM is
        # already grouped by vendor above, the type falls out per group with
        # nothing for anyone to choose — and it is switchable per order later,
        # for the fabricator who both supplies and installs.
        doc_type = vendor.default_document_type
        order = PurchaseOrder.objects.create(
            number=next_po_number(), project=bom.project, vendor=vendor,
            document_type=doc_type,
            # Whoever pressed Post POs. Already a parameter of this function —
            # it was being used for the receipts and not for the document.
            created_by=user,
            # ⚠ A COPY, taken now. Editing the company's standard terms next year
            #   must never rewrite the terms on an order already sent to someone.
            #   Copy-don't-link; the live activity reserve stays the only
            #   documented exception in the system.
            terms=company.wo_terms if doc_type == DocumentType.WO else company.po_terms,
            # Pre-filled, then editable — the site is the usual answer, not
            # always the right one.
            delivery_address=bom.project.site_address,
        )
        PurchaseOrderLine.objects.bulk_create([
            PurchaseOrderLine(
                purchase_order=order,
                bom_line=figure["line"],
                quantity=figure["order_qty"],
                # Frozen copies. Later changes to the master or the vendor's
                # rate must never alter an order already placed.
                rate=figure["vendor_rate"],
                # An unregistered supplier cannot charge GST, whatever the
                # material master says. Still editable while the order is a
                # draft, like every other figure on it.
                gst_percent=ZERO if vendor.is_unregistered else figure["line"].material.gst_percent,
            )
            for figure in by_vendor[vendor]
        ])
        # The override has been consumed. Clearing it means the next round
        # re-suggests from the fresh numbers instead of repeating this one.
        consumed += [figure["line"].id for figure in by_vendor[vendor]
                     if figure["line"].order_qty_override is not None]
        orders.append(order)

    if consumed:
        # One UPDATE rather than one save per line. A 6,400-line BOM would
        # otherwise write thousands of rows one at a time.
        from .bom_models import BomLine
        BomLine.objects.filter(id__in=consumed).update(order_qty_override=None)

    return orders


@transaction.atomic
def approve(purchase_order, user=None, gstin=None):
    """
    Commit the order to the vendor. Locks it permanently.

    >>> ANCHOR: GSTIN-CAPTURE <<<
    A purchase order cannot legally be issued without the vendor's GSTIN, so
    approval HARD-BLOCKS when it is missing. Supply `gstin` and it is saved to
    the VENDOR MASTER, not just to this order — captured once, never asked
    again. None of the 173 vendors has one yet, so this will fire on the first
    PO to every single vendor.

    Raises POError with a message meant for the user.
    """
    if purchase_order.status != PurchaseOrder.Status.DRAFT:
        raise POError(f"{purchase_order.number} is already {purchase_order.get_status_display()}. "
                      f"Only a draft can be approved.")
    if not purchase_order.lines.exists():
        raise POError(f"{purchase_order.number} has no lines. There is nothing to approve.")

    vendor = purchase_order.vendor
    if gstin:
        cleaned = gstin.strip().upper()
        try:
            gstin_format(cleaned)
        except Exception:
            raise POError(f"'{cleaned}' is not a valid GSTIN. It should be 15 characters — "
                          f"a 2-digit state code, a 10-character PAN, then 3 more, "
                          f"e.g. 24ABCDE1234F1Z5.")
        vendor.gst_number = cleaned
        # `state` MUST be in update_fields. Vendor.save() derives it from the
        # first two digits of the GSTIN when it is blank, and blank is exactly
        # what it is the first time a GSTIN is captured — so leaving it out
        # meant the derived state was worked out and then thrown away, and the
        # vendor stayed stateless forever.
        #
        # That matters beyond tidiness: a Gujarat vendor (GSTIN starting 24) is
        # billed CGST + SGST and everyone else IGST, and the purchase-order PDF
        # decides which to print from this field. Caught by running it.
        vendor.save(update_fields=["gst_number", "state", "updated_at"])

    # An unregistered supplier — the hardware shop down the road, a cash
    # purchase — has no GSTIN and never will. Blocking them would mean that
    # spend simply never gets recorded, which defeats the purpose: it still has
    # to reach the budget and the analytics. The tick lives on the vendor, so
    # this is decided once rather than argued about on every order.
    if not vendor.gst_number and not vendor.is_unregistered:
        raise POError(f"{vendor.name} has no GST number. A purchase order cannot be issued "
                      f"without one. Enter it to approve — it will be saved to the vendor and "
                      f"never asked for again. If this is a local or street supplier with no GST "
                      f"registration, tick 'unregistered' on the vendor instead.")

    purchase_order.status = PurchaseOrder.Status.APPROVED
    purchase_order.approved_at = timezone.now()
    purchase_order.approved_by = user
    purchase_order.vendor_gstin = vendor.gst_number      # frozen onto the document

    # ⚠ FREEZE THE DELIVERY ADDRESS TOO. While the order was a draft the screen
    #   could fall back to the project's site address, which is convenient. Once
    #   it is issued it must carry its own copy: somebody editing the project
    #   next month cannot be allowed to change where a document already sent to a
    #   vendor said to deliver.
    if not purchase_order.delivery_address:
        purchase_order.delivery_address = purchase_order.project.site_address

    purchase_order.save()

    capture_vendor_rates(purchase_order)

    # The WhatsApp send belongs here, once the Business API account exists.
    # Deliberately not stubbed out — an empty function that looks like it sends
    # something is worse than an obvious gap.
    return purchase_order


def capture_vendor_rates(purchase_order):
    """
    Write each line's rate back to the vendor/material master.

    >>> ANCHOR: VENDOR-RATE-CAPTURE <<<
    ⚠⚠ THE RATE CAPTURED IS NET OF THE LINE DISCOUNT — `taxable / quantity`, not
       the typed `rate`. Saahil's decision. "₹340 with 5% off" and "₹323 flat"
       are the same purchase and have to compare as the same number; capturing
       the quoted figure would make a vendor who discounts look dearer than one
       who does not.

    ⚠ REPLACES THE EXISTING ROW, SAP-STYLE. `update_or_create` on the unique
      (vendor, material) pair. The previous rate is not kept here and does not
      need to be: it is still on the order that set it.

    ⚠ THIS RUNS ON APPROVAL AND NOWHERE ELSE. Not on a draft — a draft is a
      working document that may never be sent, and a rate nobody committed to is
      not evidence of anything. Delivery and payment do not touch the rate
      either, because neither changes what was agreed.

    ⚠ WORK ORDERS CAPTURE TOO. A contractor's rate for a scope is the same
      question as a supplier's rate for a bag of cement, and the line carries a
      material either way — there is no `document_type` test here on purpose.

    ⚠ A ZERO QUANTITY IS SKIPPED RATHER THAN DIVIDED BY. It should not survive
      validation, but this is the only division in the write path and an
      exception here would fail an approval that is otherwise perfectly good.

    ⚠ TWO LINES FOR THE SAME MATERIAL ON ONE ORDER — possible, because a BOM can
      carry the same material under two activities (see ANCHOR: STOCK-ECHO). The
      last line wins, which is the same rule as the last order winning. Ordered
      by id so it is at least deterministic.

    ⚠ ROUNDS HALF UP, like every other money figure in this system. Python's
      default is half-EVEN, which would put a paisa somewhere different from the
      rest of the ladder.
    """
    for line in purchase_order.lines.select_related("bom_line__material").order_by("id"):
        if not line.quantity:
            continue
        rate = _money(line.taxable / line.quantity)
        VendorRate.objects.update_or_create(
            vendor=purchase_order.vendor,
            material=line.bom_line.material,
            defaults={"rate": rate, "source_po_line": line},
        )


def _refuse_if_billed_by_ra(purchase_order, word):
    """
    >>> ANCHOR: RA-BILL-OWNS-THE-WO <<<
    Once a work order has an RA bill, its Completed and Paid steps belong to
    the finance module: the final bill's approval marks it completed with the
    CERTIFIED quantities as receipts, and the last payment marks it paid. The
    hand buttons would write a full-quantity receipt on top of the certified
    ones, or call a work order paid while a bill is still open — so they are
    refused and the person is sent to the screen that owns it.

    ⚠ Imported inside the function: finance imports projects, not the other
      way round, and a module-level import here would make that a cycle.
    """
    from finance.models import RABill
    if RABill.objects.filter(purchase_order=purchase_order).exists():
        raise POError(f"{purchase_order.number} is billed through RA bills, so it cannot be "
                      f"marked {word} here. Open Finance → RA bills for this work order: the "
                      f"final bill marks it completed and the last payment marks it paid.")


@transaction.atomic
def mark_delivered(purchase_order, received_on=None, note="", user=None):
    """
    Record the order as arrived, and write a receipt for every line.

    Receipts go through receipts.record_receipt — the single door for received
    quantities, which the task management module will use later.
    """
    if purchase_order.status != PurchaseOrder.Status.APPROVED:
        raise POError(f"{purchase_order.number} is {purchase_order.get_status_display()}. "
                      f"Only an approved order can be marked delivered.")
    _refuse_if_billed_by_ra(purchase_order, "completed")

    record_full_delivery(purchase_order, received_on=received_on, note=note)
    purchase_order.status = PurchaseOrder.Status.DELIVERED
    purchase_order.delivered_at = timezone.now()
    # ⚠ WHO, as well as when. The site engineer who saw the lorry is not the
    #   person who approved the order, and the matrix says so.
    purchase_order.delivered_by = user
    purchase_order.save(update_fields=["status", "delivered_at", "delivered_by", "updated_at"])
    return purchase_order


@transaction.atomic
def mark_paid(purchase_order, user=None):
    """Record that payment has gone out. The end of the lifecycle."""
    if purchase_order.status != PurchaseOrder.Status.DELIVERED:
        raise POError(f"{purchase_order.number} is {purchase_order.get_status_display()}. "
                      f"Only a delivered order can be marked paid. If you have paid an advance "
                      f"before delivery, that is not yet recorded here — see PROJECT-CONTEXT.md.")
    _refuse_if_billed_by_ra(purchase_order, "paid")

    purchase_order.status = PurchaseOrder.Status.PAID
    purchase_order.paid_at = timezone.now()
    purchase_order.paid_by = user
    purchase_order.save(update_fields=["status", "paid_at", "paid_by", "updated_at"])
    return purchase_order


@transaction.atomic
def delete_draft(purchase_order):
    """
    Throw away an unapproved order.

    Safe precisely because the BOM stores nothing: the quantity was only ever
    recorded on these PO lines, so deleting them is all that is required. The
    quantity reappears under "to order" on its own, because it is no longer
    there to subtract.
    """
    if purchase_order.status != PurchaseOrder.Status.DRAFT:
        raise POError(f"{purchase_order.number} is {purchase_order.get_status_display()} and "
                      f"cannot be deleted. Only drafts can be thrown away.")
    number = purchase_order.number
    purchase_order.delete()
    return number


@transaction.atomic
def update_draft_line(po_line, quantity=None, rate=None, gst_percent=None,
                      discount_pct=None, reference=None):
    """
    Change what a person may change on a draft line.

    Nothing needs to be written back to the BOM afterwards — the BOM reads these
    lines directly, so the change is visible the moment it is saved. That is the
    whole reason "In Draft" is never stored: reduce a draft from 300 to 200 and
    100 returns to "still to buy" on its own, with no code remembering to do it.

    ⚠ GST% AND DISCOUNT ARE EDITABLE HERE ON PURPOSE. GST normally comes from the
      material master, but one-off cases exist and a buyer who cannot correct the
      figure will put the order through anyway with the wrong tax on it. The
      discount is a percentage only — Saahil was explicit that a line discount is
      never typed as an amount.
    """
    order = po_line.purchase_order
    if not order.is_editable:
        raise POError(f"{order.number} is {order.get_status_display()} and locked. "
                      f"Approved orders cannot be changed.")

    if quantity is not None:
        amount = Decimal(str(quantity))
        if amount < ZERO:
            raise POError("A quantity cannot be negative.")
        po_line.quantity = amount
    if rate is not None:
        amount = Decimal(str(rate))
        if amount < ZERO:
            raise POError("A rate cannot be negative.")
        po_line.rate = amount
    if gst_percent is not None:
        amount = Decimal(str(gst_percent))
        if amount < ZERO or amount > 100:
            raise POError("A GST percentage must be between 0 and 100.")
        po_line.gst_percent = amount
    if discount_pct is not None:
        amount = Decimal(str(discount_pct))
        if amount < ZERO or amount > 100:
            raise POError("A discount must be between 0 and 100 per cent.")
        po_line.discount_pct = amount
    if reference is not None:
        po_line.reference = str(reference)[:300]

    po_line.save()
    return po_line


@transaction.atomic
def update_draft_document(order, deduction_pct=None, tds_pct=None, tds_section=None,
                          terms=None, delivery_address=None, required_by=None,
                          retention_pct=None, dlp_months=None, mobilisation_advance=None):
    """
    The document-level fields: the post-tax deduction, TDS, terms and delivery,
    and on a work order the retention, defect liability and advance terms.

    >>> ANCHOR: WO-TERMS <<<
    The three work-order terms are bounded here rather than in the model:
    retention 0–50%, DLP 0–60 months, an advance of at least zero and never
    more than the order's own taxable value — an advance bigger than the work
    could never be recovered from the bills.

    ⚠ NEITHER PERCENTAGE HAS A DEFAULT, and that is deliberate (Saahil, 10 Aug).
      They are single numbers that genuinely vary order to order, and a default
      would be applied by someone who never thought about it. The TERMS are the
      exception — nobody retypes three paragraphs, so they arrive copied from the
      company profile.

    ⚠ THE DEDUCTION IS NOT A DISCOUNT. It comes off AFTER GST, so the tax on this
      document sits on the undiscounted taxable value and the vendor's invoice
      will show a different taxable figure. That is why it prints as "agreed
      deduction (post-tax)" and must never be labelled a discount.
    """
    if not order.is_editable:
        raise POError(f"{order.number} is {order.get_status_display()} and locked.")

    for name, value, label in (("deduction_pct", deduction_pct, "deduction"),
                               ("tds_pct", tds_pct, "TDS")):
        if value is None:
            continue
        amount = Decimal(str(value))
        if amount < ZERO or amount > 100:
            raise POError(f"The {label} percentage must be between 0 and 100.")
        setattr(order, name, amount)

    if tds_section is not None:
        order.tds_section = str(tds_section)[:10]
    if terms is not None:
        order.terms = str(terms)
    if delivery_address is not None:
        order.delivery_address = str(delivery_address)
    if required_by is not None:
        order.required_by = required_by or None

    if retention_pct is not None:
        amount = Decimal(str(retention_pct))
        if amount < ZERO or amount > 50:
            raise POError("Retention must be between 0 and 50 per cent.")
        order.retention_pct = amount
    if dlp_months is not None:
        try:
            months = int(str(dlp_months).strip() or 0)
        except ValueError:
            raise POError("The defect liability period must be a whole number of months.")
        if months < 0 or months > 60:
            raise POError("The defect liability period must be between 0 and 60 months.")
        order.dlp_months = months
    if mobilisation_advance is not None:
        amount = _money(Decimal(str(mobilisation_advance)))
        if amount < ZERO:
            raise POError("A mobilisation advance cannot be negative.")
        taxable = order.totals()["taxable"]
        if amount > taxable:
            raise POError(f"A mobilisation advance of {amount} is more than the order's basic "
                          f"value of {taxable}. It could never be recovered from the bills.")
        order.mobilisation_advance = amount

    order.save()
    return order


@transaction.atomic
def remove_draft_line(po_line):
    """
    Take a line off a draft order. Its quantity returns to "to order" by itself.

    Removing the last line deletes the order too — an order with no lines is not
    a document, it is a leftover.
    """
    order = po_line.purchase_order
    if not order.is_editable:
        raise POError(f"{order.number} is {order.get_status_display()} and locked.")
    po_line.delete()
    if not order.lines.exists():
        order.delete()
        return None
    return order
