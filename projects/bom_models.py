"""
The Bill of Materials, Purchase Orders, and goods received.

WHAT THIS FILE IS FOR
    Bom / BomLine        what a project plans to buy, one list per activity
    PurchaseOrder / Line what was actually ordered, from whom, at what price
    Receipt              what actually arrived

WHAT DEPENDS ON IT
    bom_calc.py reads these to produce every number on the BOM screen.
    po_service.py writes them.

⚠ THE ONE DESIGN DECISION THAT EXPLAINS EVERYTHING ELSE HERE
    A BomLine does NOT store how much has been ordered, drafted or received.

    Those three numbers live in ONE place — the purchase orders — and the BOM
    adds them up when it needs them. "In Draft" is not a stored figure kept in
    step with the POs; it IS the sum of that material's draft PO lines, by
    definition.

    Why it matters: if the same fact is written down twice, the two copies can
    disagree. Every path that could cause drift — editing a draft, deleting one,
    approving, receiving, a half-finished save — simply stops existing. It is
    the difference between a bank storing your balance in a box, and a bank
    adding up your transactions.

    The cost is a database query when the screen loads. At a few hundred lines
    that is not something anyone notices.

    The BomLine therefore stores only what a HUMAN types: planned quantity,
    site stock, threshold, remark, chosen vendor.
"""
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

# PO or WO. Defined in masters because the VENDOR carries the default, and
# masters must not import projects — the dependency only runs one way.
from masters.models import DocumentType

# Rupees, to the paisa, rounded half-up — the way a person rounds a bill.
# Money is rounded WHERE IT IS CALCULATED, never in a template: see the note on
# PurchaseOrderLine.basic for the bug that made this a rule.
_PAISA = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(_PAISA, rounding=ROUND_HALF_UP)


def apportion(total: Decimal, weights) -> list:
    """
    Split one document-level amount across its lines so the parts add back to
    the whole EXACTLY.

    >>> ANCHOR: PO-LINE-SHARES <<<
    Saahil, 16 Aug 2026: *"for ex 1000, if there is a value like thousand, then
    if it's split by three line items per say, so it's 333, 333, and 334. So make
    sure that it is auto calculated and settled."*

    ⚠⚠ THE RESIDUAL IS THE WHOLE POINT. Three equal shares of ₹1000 are
       ₹333.333… each. Round each one on its own and they sum to ₹999.99, so the
       accountant's SUM in Excel disagrees with the purchase order by a paisa —
       and a paisa is enough to make somebody distrust the file and re-key it by
       hand, which is the thing this export exists to prevent.

    ⚠ SO IT IS LARGEST-REMAINDER, NOT ROUND-EACH-AND-HOPE. Every share is floored
      to the paisa, then the leftover paise are handed out one at a time to the
      lines with the largest fractional part. The result sums to `total` by
      construction, not by luck, and no share is ever more than a paisa away from
      its true proportion.

    ⚠ TIES GO TO THE LAST LINE, which is why three equal lines give
      333.33 / 333.33 / 333.34 rather than 333.34 / 333.33 / 333.33. Arithmetically
      either is correct; this is the one Saahil described, and matching the mental
      model of the person checking the file is worth more than the coin flip.

    ⚠ IT HANDLES A NEGATIVE TOTAL, because `round_off` is regularly negative. The
      sign is lifted off, the magnitude apportioned, and the sign put back — so
      the parts of −₹0.40 still sum to exactly −₹0.40.

    ⚠ ZERO WEIGHTS SPLIT EVENLY rather than dividing by zero. A document whose
      lines are all zero-value is degenerate but reachable, and it must not 500.
    """
    weights = [Decimal(w) for w in weights]
    count = len(weights)
    if count == 0:
        return []

    sign = -1 if total < 0 else 1
    paise = int((abs(Decimal(total)) * 100).to_integral_value(rounding=ROUND_HALF_UP))

    weight_sum = sum(weights)
    if weight_sum <= 0:
        weights = [Decimal(1)] * count
        weight_sum = Decimal(count)

    exact = [Decimal(paise) * weight / weight_sum for weight in weights]
    shares = [int(value.to_integral_value(rounding=ROUND_FLOOR)) for value in exact]

    # Hand out the leftover paise, biggest fractional part first, later lines
    # winning a tie. `-index` in the sort key is what puts the extra paisa on the
    # LAST of three identical lines.
    leftover = paise - sum(shares)
    order = sorted(range(count), key=lambda i: (exact[i] - shares[i], i), reverse=True)
    for step in range(leftover):
        shares[order[step % count]] += 1

    return [sign * Decimal(share) / 100 for share in shares]


class Bom(models.Model):
    """
    One bill of materials per project.

    Created by the explicit "Generate BOM" button once the customer has accepted
    the quote. That gate is COMMERCIAL, not editorial — it does not contradict
    "no approval workflow on estimates". It simply means you do not plan
    purchases for work nobody has agreed to pay for.

    ⚠ OPEN QUESTION, see PROJECT-CONTEXT.md: one BOM per project, or several?
    Modelled as one for now because nothing yet needs more. If several are ever
    needed, this becomes a ForeignKey and every `project.bom` reference changes.
    """
    project = models.OneToOneField("projects.Project", on_delete=models.CASCADE, related_name="bom")
    generated_at = models.DateTimeField(auto_now_add=True)
    generated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                     null=True, blank=True, related_name="boms_generated")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "BOM"
        verbose_name_plural = "BOMs"

    def __str__(self) -> str:
        return f"BOM for {self.project.code}"


class BomLine(models.Model):
    """
    One material planned under one activity.

    Keyed on (bom, activity, material) but deliberately NOT unique on it — the
    same material may appear twice under one activity, with a remark to tell
    them apart ("footing & plinth" vs "slab pour 2"). The screen warns when you
    add a material that is already there; it does not refuse.
    """
    bom = models.ForeignKey(Bom, on_delete=models.CASCADE, related_name="lines")
    # ⚠ masters.Activity since slice 8 — the activity master moved apps because
    #   it is master data. The TABLE is unchanged, so this FK still points at
    #   exactly the rows it always did.
    activity = models.ForeignKey("masters.Activity", on_delete=models.PROTECT, related_name="bom_lines")
    material = models.ForeignKey("masters.Material", on_delete=models.PROTECT, related_name="bom_lines")

    remark = models.CharField(
        max_length=200, blank=True,
        help_text='Tells duplicate lines apart, e.g. "footing & plinth" vs "slab pour 2".',
    )

    # ---- the only quantities a human types -----------------------------
    planned_qty = models.DecimalField(
        max_digits=14, decimal_places=3, default=0, validators=[MinValueValidator(0)],
        help_text="How much this project needs. The BOQ carries money only, never quantities.",
    )
    stock_qty = models.DecimalField(
        max_digits=14, decimal_places=3, default=0, validators=[MinValueValidator(0)],
        help_text="What is on site now. Entered or bulk-uploaded, never calculated.",
    )
    min_qty = models.DecimalField(
        max_digits=14, decimal_places=3, default=0, validators=[MinValueValidator(0)],
        help_text="Reorder threshold. Below this the line is flagged.",
    )
    order_qty_override = models.DecimalField(
        max_digits=14, decimal_places=3, null=True, blank=True, validators=[MinValueValidator(0)],
        help_text="Leave blank to use the suggested quantity. Type a number to override it — "
                  "ordering 20 of a planned 150 is normal, and so is ordering extra.",
    )

    # >>> ANCHOR: PLANNING-RATE <<<
    # THE RATE THIS PROJECT PLANS AT. Blank means "use the material master's
    # estimation rate", which is what every line did before this field existed.
    #
    # WHY IT HAD TO BECOME EDITABLE (Saahil, 10 Aug)
    #   For cement the master rate is a fair company-wide benchmark and you vary
    #   the QUANTITY per project. For a material sold as a lump — signage, a
    #   security deposit, a lightning arrestor — the quantity is always 1 and the
    #   AMOUNT is what varies per project. With the rate locked to the master,
    #   planning one project's signage meant editing company master data and
    #   moving the figure on every other project at the same time.
    #
    #   He asked whether such lines needed a planned-AMOUNT field instead.
    #   ⚠ THEY DO NOT, AND THAT WAS REJECTED — DO NOT REOPEN IT. An amount-only
    #   line would give estimated_value two formulas and force
    #   suggested_order_qty to branch, because that subtraction is
    #   quantity-minus-quantity: "3 bags approved" cannot be taken away from
    #   "₹85,000 planned". One special case would have become four, spread
    #   across bom_calc.
    #
    #   What protects the arithmetic is not that the quantity is 1 — it is that
    #   there IS a quantity. The logic works identically at 0.3, which is what
    #   makes stage billing ("30% completion") an ordinary line rather than a
    #   special case.
    #
    # ⚠ Whoever edits this moves the number their own work is measured against.
    #   The same risk was already accepted for the live-linked activity reserve,
    #   and rate changes are in scope for the audit trail.
    planned_rate = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)],
        help_text="What this project plans to pay per unit. Blank uses the material master's "
                  "estimation rate. For a Lumpsum material, quantity 1 and the amount here.",
    )

    # ---- who it would be bought from -----------------------------------
    vendor = models.ForeignKey("masters.Vendor", on_delete=models.PROTECT, null=True, blank=True,
                               related_name="bom_lines")
    vendor_rate = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)],
        help_text="Pre-filled from the vendor's rate, editable. Blank falls back to the "
                  "material's estimation rate.",
    )

    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["activity__sort_order", "sort_order", "id"]
        indexes = [models.Index(fields=["bom", "activity"])]

    def __str__(self) -> str:
        return f"{self.material.code} under {self.activity.abbreviation}"


class NumberSeries(models.Model):
    """
    A counter that only ever goes up. One row per kind of document.

    WHY THIS EXISTS AT ALL
        Purchase order numbers used to be worked out from the orders already in
        the database — take the highest and add one. That is wrong the moment
        one is deleted: delete PO-0001 and the next order becomes PO-0001 again,
        so two different documents share a number over time. Since unapproved
        orders are meant to be disposable, that would have happened constantly.

        Caught by a test, not by reading the code.

    A gap in the numbers is fine and expected — it means an order was thrown
    away. A REPEAT is not, because a number printed on a document sent to a
    vendor has to keep meaning one thing forever.

    This is the same idea as SAP's internal number ranges, kept deliberately
    small: one key, one counter.
    """
    key = models.CharField(max_length=30, unique=True, help_text='e.g. "purchase_order"')
    last_number = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "number series"

    def __str__(self) -> str:
        return f"{self.key}: {self.last_number}"

    @classmethod
    def take_next(cls, key):
        """
        Hand out the next number and remember it.

        `select_for_update` locks the row for the moment it takes, so two people
        pressing Post POs at the same time cannot be handed the same number.
        """
        from django.db import transaction
        with transaction.atomic():
            series, _ = cls.objects.select_for_update().get_or_create(key=key)
            series.last_number += 1
            series.save(update_fields=["last_number", "updated_at"])
            return series.last_number


class PurchaseOrder(models.Model):
    """
    One order to one vendor. May span several activities — Sambhav Hardware
    supplies cement, wire and window sections, and that is one order, one
    delivery, one bill.

    Every generation creates a NEW numbered PO. It is never appended to an
    existing draft: unapproved ones are disposable, and each number is then a
    clean record of one batch.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        APPROVED = "approved", "Approved"
        DELIVERED = "delivered", "Delivered"
        PAID = "paid", "Paid"

    # Strictly sequential — Saahil's call over independent flags.
    # ⚠ Known consequence, accepted: an advance paid before delivery cannot
    # reach PAID without first marking DELIVERED. Watch for anyone marking
    # DELIVERED early to unblock a payment — that writes received quantities
    # for material that has not arrived.
    ORDER = [Status.DRAFT, Status.APPROVED, Status.DELIVERED, Status.PAID]

    number = models.CharField(max_length=20, unique=True, help_text="Auto-generated, e.g. PO-0001")
    project = models.ForeignKey("projects.Project", on_delete=models.PROTECT, related_name="purchase_orders")
    vendor = models.ForeignKey("masters.Vendor", on_delete=models.PROTECT, related_name="purchase_orders")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)

    raised_on = models.DateField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                    null=True, blank=True, related_name="pos_approved")
    delivered_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    # ⚠ WHO, NOT JUST WHEN. `approved_at` and `approved_by` have been a pair
    #   since slice 5a; the other two steps recorded only a timestamp, and
    #   "who marked this paid" is the question somebody asks six months later
    #   with an invoice in their hand. The matrix gives these three steps to
    #   three different roles, so the name is the point rather than decoration.
    #
    # ⚠ SET_NULL, NOT PROTECT, and deliberately different from `approved_by`.
    #   Approval is the moment money is committed and its owner must never
    #   vanish; delivery and payment are records of an act. A user is never
    #   deleted in this system anyway — they are deactivated — so this only
    #   matters if somebody reaches past the app into the database.
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="purchase_orders_raised")
    delivered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="purchase_orders_delivered")
    paid_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="purchase_orders_paid")

    # A frozen copy, taken at approval. The vendor master may be corrected
    # later; this document must keep showing what was on it when it was issued.
    vendor_gstin = models.CharField(max_length=15, blank=True)

    # >>> ANCHOR: DOCUMENT-TYPE <<<
    # Purchase Order or Work Order. Copied from the vendor when the draft is
    # created, and switchable on the Post POs preview before anything is
    # written — see masters.Vendor.default_document_type for why the VENDOR
    # decides it rather than the materials on the lines.
    document_type = models.CharField(
        max_length=2, choices=DocumentType.choices, default=DocumentType.PO)

    # ---- what prints on the document -----------------------------------
    # >>> ANCHOR: DOC-TERMS <<<
    # ⚠ A COPY of CompanyProfile.po_terms / .wo_terms, taken when this draft was
    #   created. NEVER read live. Editing the company's standard terms next year
    #   must not rewrite the terms on an order already sent to a vendor.
    terms = models.TextField(blank=True)
    delivery_address = models.TextField(
        blank=True, help_text="Pre-filled from the project's site address. Prints as SHIP TO.")
    required_by = models.DateField(null=True, blank=True, help_text="When the site needs it.")

    # ---- the money adjustments, typed on this document -------------------
    # ⚠ NO DEFAULTS, DELIBERATELY (Saahil, 10 Aug). These are single numbers
    #   that genuinely vary order to order, and a default would be applied
    #   without thought. The TERMS are the exception, because nobody retypes
    #   three paragraphs.
    #
    # ⚠ deduction_pct IS APPLIED AFTER GST, and it is NOT a discount.
    #   Saahil's call over the recommendation. The consequence, recorded once
    #   and not to be relitigated: the GST we print sits on the UNDISCOUNTED
    #   taxable value, so the vendor's invoice will show a different taxable
    #   value every time it is used. That is why it must print as
    #   "Less: agreed deduction (post-tax)" and never as "Discount" — calling it
    #   a discount invites the reader to expect the tax to have moved.
    deduction_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=0, validators=[MinValueValidator(0)],
        help_text="Agreed deduction on the whole bill, applied AFTER GST.")

    # ⚠ TDS IS NOT A DISCOUNT AND NEVER SITS IN THE ORDER VALUE. It is withheld
    #   from the PAYMENT, computed on the TAXABLE value and never on the GST,
    #   and it does not reduce what the vendor bills us. Hence the document ends
    #   ORDER VALUE (what they invoice) → less TDS → NET PAYABLE (what we pay).
    #   Applicability and rate are Saahil's CA's call, not ours.
    tds_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=0, validators=[MinValueValidator(0)],
        help_text="Withheld from payment, computed on the taxable value. Leave 0 if not applicable.")
    tds_section = models.CharField(
        max_length=10, blank=True, help_text='e.g. 194Q for goods, 194C for a contractor.')

    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-raised_on", "-id"]
        indexes = [
            models.Index(fields=["project", "vendor"]),
            models.Index(fields=["status"]),
            # For the dashboards Saahil asked for. ⚠ He wanted approved orders
            # copied into a separate reporting table; they are already rows in
            # this one, and a denormalised copy would be a second source of
            # truth that drifts — the exact failure this project already had
            # when the BOM cached approved / in-draft / received. Indexes, not
            # tables. A materialised view only if something ever measures slow.
            models.Index(fields=["status", "approved_at"]),
            models.Index(fields=["vendor", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.number} · {self.vendor.name} · {self.get_status_display()}"

    @property
    def is_editable(self) -> bool:
        """
        Only a draft can be changed. Approving locks the document outright —
        this supersedes the earlier rule where an edit merely cleared approval.
        """
        return self.status == self.Status.DRAFT

    @property
    def next_status(self):
        """The one status this PO may move to next, or None at the end."""
        index = self.ORDER.index(self.status)
        return self.ORDER[index + 1] if index + 1 < len(self.ORDER) else None

    @property
    def status_word(self):
        """
        What the status is CALLED on this document.

        Material is delivered; labour is completed. Same status underneath, same
        receipts written — only the word changes, because the person reading the
        button takes it literally.
        """
        if self.document_type == DocumentType.WO and self.status == self.Status.DELIVERED:
            return "Completed"
        return self.get_status_display()

    @property
    def type_label(self):
        return "Work Order" if self.document_type == DocumentType.WO else "Purchase Order"

    # ---- the totals ladder ----------------------------------------------
    def totals(self):
        """
        Every money figure on this document, in the order it is printed.

        >>> ANCHOR: PO-TOTALS <<<
        ONE implementation, used by the document list, the detail screen and the
        PDF. A vendor's row in the list must never disagree with the order you
        open from it, and the only way to guarantee that is for both to be this
        function.

        THE LADDER, and why it is shaped like this:

            gross            qty x rate, before anything
          - discount         the per-line percentages
          = taxable          what GST is charged on
          + gst              CGST+SGST or IGST — the split is presentation, the
                             amount is the same either way
          = invoice_value    what the vendor's invoice will say
          - deduction        ⚠ AFTER GST, and NOT a discount. Saahil's call. The
                             GST above sits on the UNDISCOUNTED taxable value, so
                             the vendor's invoice will show a different taxable
                             figure. It must print as "agreed deduction
                             (post-tax)" — calling it a discount invites the
                             reader to expect the tax to have moved.
          +/- round_off      to the nearest rupee. COMPUTED, NEVER STORED: a
                             stored round-off drifts out of step with the figures
                             it was derived from.
          = order_value      what the vendor invoices us
            ----
          - tds              ⚠ NOT a discount and NOT part of the order. Withheld
                             from the PAYMENT, computed on the TAXABLE value and
                             never on the GST. It does not reduce what the vendor
                             bills.
          = net_payable      what actually leaves the bank

        ⚠ Every step rounds to 2dp as it goes, because this ends up on a tax
          document. Rounding only at the end lets a long tail through.

        ⚠ Iterates the lines in PYTHON rather than summing in SQL, deliberately.
          Two reasons: the figures then come from the same properties the lines
          themselves print, so they cannot drift; and percentage arithmetic in
          SQL is not portable — SQLite integer-divides 10/100 to zero while
          PostgreSQL does not, which would mean different money on the laptop and
          on the client's server. Callers should prefetch `lines`.
        """
        lines = list(self.lines.all())
        gross = _money(sum((line.basic for line in lines), Decimal("0")))
        discount = _money(sum((line.discount_amount for line in lines), Decimal("0")))
        taxable = _money(sum((line.taxable for line in lines), Decimal("0")))
        gst = _money(sum((line.gst_amount for line in lines), Decimal("0")))

        invoice_value = _money(taxable + gst)
        deduction = _money(invoice_value * self.deduction_pct / 100)
        after = _money(invoice_value - deduction)
        order_value = after.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        round_off = _money(order_value - after)
        tds = _money(taxable * self.tds_pct / 100)

        return {
            "line_count": len(lines),
            "gross": gross,
            "discount": discount,
            "taxable": taxable,
            "gst": gst,
            # The halves must add back to the whole exactly — hence subtraction
            # rather than halving twice, which loses a paisa on odd amounts.
            "cgst": _money(gst / 2),
            "sgst": _money(gst - _money(gst / 2)),
            "invoice_value": invoice_value,
            "deduction": deduction,
            "round_off": round_off,
            "order_value": order_value,
            "tds": tds,
            "net_payable": _money(order_value - tds),
        }

    def line_shares(self):
        """
        Every document-level amount split across the lines, adding back exactly.

        >>> ANCHOR: PO-LINE-SHARES <<<
        WHY THIS EXISTS: the accountant filters the register export in Excel and
        pushes it into Tally. The document-level figures used to be REPEATED on
        every line, so a four-line order printed its TDS four times and summing
        the column gave four times the real TDS. Saahil: *"the header discounts
        have to be distributed properly across all the line items so the numbers
        add up properly for them, and they can simply input that full and final
        value entirely for their accounting."*

        ⚠⚠ THE BASES FOLLOW THE LADDER IN `totals()`, THEY ARE NOT PICKED FOR
           CONVENIENCE.
             deduction  is charged on the INVOICE VALUE (post-tax), so it is
                        apportioned on each line's `total` — taxable plus GST.
             tds        is computed on the TAXABLE value and never on the GST,
                        so it is apportioned on each line's `taxable`.
             round_off  belongs to the document as a whole; it rides on the same
                        base as the deduction so `order_value` still ties.
           Using one base for all three would have been simpler and would have
           put TDS on the wrong money.

        ⚠ IT READS `totals()` AND APPORTIONS WHAT IT FINDS. It does not recompute
          a single percentage. `PO-TOTALS` is the one implementation of this
          ladder, and a second one here would be free to disagree with the
          printed order — which is the whole failure this codebase keeps
          designing out.

        ⚠ EVERY LIST IT RETURNS SUMS TO ITS FIGURE IN `totals()` EXACTLY, and
          that is asserted per order in the tests rather than assumed.

        Returns one dict per line, in `self.lines` order.
        """
        lines = list(self.lines.all())
        totals = self.totals()

        by_total = [line.total for line in lines]
        by_taxable = [line.taxable for line in lines]

        deductions = apportion(totals["deduction"], by_total)
        round_offs = apportion(totals["round_off"], by_total)
        tds_shares = apportion(totals["tds"], by_taxable)

        shares = []
        for index, line in enumerate(lines):
            order_value = _money(line.total - deductions[index] + round_offs[index])
            shares.append({
                "line": line,
                "deduction": deductions[index],
                "round_off": round_offs[index],
                "tds": tds_shares[index],
                "order_value": order_value,
                "net_payable": _money(order_value - tds_shares[index]),
            })
        return shares


class PurchaseOrderLine(models.Model):
    """
    One material on one purchase order.

    ⚠ EVERY PO LINE TRACES BACK TO A BOM LINE. There is deliberately no way to
    add a material straight onto a PO: everything bought was planned somewhere,
    so planned-versus-actual always reconciles and nothing is purchased off the
    books.
    """
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="lines")
    bom_line = models.ForeignKey(BomLine, on_delete=models.PROTECT, related_name="po_lines")

    quantity = models.DecimalField(max_digits=14, decimal_places=3, validators=[MinValueValidator(0)])

    # FROZEN COPIES, taken when the line is created. Later changes to the
    # material master or the vendor's rate must never alter an order already
    # placed. (The activity reserve is the one live-linked exception in the
    # whole system — see EstimateLine.)
    rate = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    gst_percent = models.DecimalField(max_digits=5, decimal_places=2, default=18)

    # Percentage only — Saahil was explicit that a line discount is never an
    # amount. Reduces the TAXABLE value, so GST is charged on the discounted
    # figure, which is what the vendor's invoice will also show.
    discount_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=0, validators=[MinValueValidator(0)])

    # >>> ANCHOR: PO-LINE-REFERENCE <<<
    # Free text the VENDOR reads: "slab pour, Block A 4th floor, split over two
    # trips". About fifty words.
    #
    # ⚠ NOT the same field as BomLine.remark, and it must never be merged with
    #   it. The BOM remark tells duplicate PLANNING lines apart ("first pour" /
    #   "second pour") and is nobody's business outside the office. This one is
    #   printed and sent.
    #
    # It matters most on a work order, where master names like SIGNAGE are
    # deliberately generic and the scope of the job lives here.
    reference = models.CharField(max_length=300, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["bom_line"])]

    def __str__(self) -> str:
        return f"{self.purchase_order.number} · {self.bom_line.material.code} × {self.quantity}"

    # ---- money. The ONLY place in the system where GST appears. ----------
    #
    # ⚠ EVERY FIGURE IS ROUNDED TO 2 DECIMALS HERE, WHERE IT IS CALCULATED.
    #   Not in the template. Saahil found five-decimal figures on his own screen:
    #   the money fields are all 2dp in the database, but derived properties were
    #   never rounded, so a division or a percentage grew a tail that the screen
    #   filters hid and Admin, exports and the PDF did not. A tax document
    #   showing a five-decimal total is not defensible.
    @property
    def basic(self) -> Decimal:
        return _money(self.quantity * self.rate)

    @property
    def discount_amount(self) -> Decimal:
        return _money(self.basic * self.discount_pct / 100)

    @property
    def taxable(self) -> Decimal:
        """What GST is charged on, and what counts against the activity reserve."""
        return _money(self.basic - self.discount_amount)

    @property
    def gst_amount(self) -> Decimal:
        return _money(self.taxable * self.gst_percent / 100)

    @property
    def total(self) -> Decimal:
        return _money(self.taxable + self.gst_amount)


class Receipt(models.Model):
    """
    Material that actually arrived.

    >>> ANCHOR: TASK-MODULE <<<
    Written ONLY through projects.receipts.record_receipt(). Today that is
    called when a PO is marked Delivered. Later the task management module will
    call the same function. Nothing else should create these rows — see the
    docstring on record_receipt for why.

    Kept as its own table rather than a number on the PO line so that partial
    deliveries are recorded honestly: 300 today, 200 next week, each with its
    own date, rather than one figure edited twice.
    """

    class Source(models.TextChoices):
        MANUAL = "manual", "Marked delivered by hand"
        TASK_MODULE = "task", "Task management module"

    po_line = models.ForeignKey(PurchaseOrderLine, on_delete=models.PROTECT, related_name="receipts")
    quantity = models.DecimalField(max_digits=14, decimal_places=3, validators=[MinValueValidator(0)])
    received_on = models.DateField()
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.MANUAL)
    note = models.CharField(max_length=200, blank=True)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-received_on", "-id"]

    def __str__(self) -> str:
        return f"{self.po_line.bom_line.material.code} × {self.quantity} on {self.received_on}"
