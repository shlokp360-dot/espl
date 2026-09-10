"""
Finance: RA bills on work orders, retention, vendor invoices and payments.

WHAT THIS FILE IS FOR
    RABill / RABillLine   a contractor's running-account bill against a work order
    RetentionRelease      retention handed back after the defect liability period
    VendorInvoice         a supplier's invoice against a material purchase order
    VendorPayment         money that left the bank — the one payments register

WHAT DEPENDS ON IT
    finance/calc.py reads these to produce every figure on a finance screen.
    finance/services.py writes them.

>>> ANCHOR: FIN-MODEL <<<
THE ONE DESIGN DECISION THAT EXPLAINS EVERYTHING ELSE HERE
    An RA bill stores what a person typed — the claimed and certified
    quantities — and frozen copies of the rate, GST and discount from the work
    order line. It stores NO money. Every rupee figure on a bill is computed by
    finance.calc from those quantities and the work order's own terms, the same
    way PurchaseOrder.totals() computes the order. Cumulative certified, retention
    held, advance recovered and paid-to-date are all sums over rows, never a
    number kept in step with them.

⚠ TWO DOCUMENT FAMILIES, DELIBERATELY KEPT APART. A work order (document_type
  WO) is billed by RA bills and settled by payments against them; a purchase
  order (PO) is billed by vendor invoices and settled by payments against those.
  services.py refuses an RA bill on a PO and an invoice on a WO. The one thing
  they share is VendorPayment, because the accountant keys ONE payments register
  into Tally, and a second register would be a second file to reconcile.

⚠ COPY, DON'T LINK. RABillLine.rate / gst_percent / discount_pct are copied from
  the PO line when the bill is created. The work order is locked at approval so
  they cannot drift today; the copy is there so a future correction to an order
  can never rewrite a bill already sent to a contractor.
"""
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class RABill(models.Model):
    """
    One running-account bill from a contractor against one work order.

    ⚠ STRICTLY SEQUENTIAL, like PurchaseOrder: DRAFT → CERTIFIED → APPROVED → PAID.
      Draft      the contractor's claim, typed in; quantities editable
      Certified  our engineer has written the certified quantity on every line
      Approved   money committed; receipts written; LOCKED
      Paid       Σ payments ≥ net payable

    ⚠ ONE OPEN BILL PER WORK ORDER. A second draft while the first is not yet
      approved would make "cumulative certified" ambiguous — which of the two
      counts first? services.create_ra_bill refuses it, and a test proves it.

    ⚠ NO BILL AFTER THE FINAL ONE. `is_final` is the contractor's own claim that
      this closes the contract; approving it marks the work order completed.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        CERTIFIED = "certified", "Certified"
        APPROVED = "approved", "Approved"
        PAID = "paid", "Paid"

    ORDER = [Status.DRAFT, Status.CERTIFIED, Status.APPROVED, Status.PAID]
    OPEN = [Status.DRAFT, Status.CERTIFIED]
    COUNTED = [Status.APPROVED, Status.PAID]        # what "to date" figures sum over

    purchase_order = models.ForeignKey(
        "projects.PurchaseOrder", on_delete=models.PROTECT, related_name="ra_bills")
    number = models.CharField(max_length=20, unique=True, help_text="RA-000001, from NumberSeries")
    # 1st, 2nd, 3rd bill on THIS work order. Computed once at creation, because
    # the printed bill says "RA Bill No. 3" and that must never renumber.
    sequence = models.PositiveSmallIntegerField()
    bill_date = models.DateField()
    contractor_ref = models.CharField(max_length=60, blank=True, help_text="Their invoice number.")
    period_from = models.DateField(null=True, blank=True)
    period_to = models.DateField(null=True, blank=True)
    is_final = models.BooleanField(default=False)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)

    certified_at = models.DateTimeField(null=True, blank=True)
    certified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="ra_bills_certified")
    approved_at = models.DateTimeField(null=True, blank=True)
    # PROTECT, like PurchaseOrder.approved_by: approval commits money and its
    # owner must never vanish.
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="ra_bills_approved")
    paid_at = models.DateTimeField(null=True, blank=True)

    note = models.CharField(max_length=300, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="ra_bills_raised")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["purchase_order_id", "sequence"]
        constraints = [
            models.UniqueConstraint(fields=["purchase_order", "sequence"],
                                    name="finance_one_sequence_per_wo"),
        ]
        indexes = [models.Index(fields=["status"])]

    def __str__(self) -> str:
        return f"{self.number} · {self.purchase_order.number} · {self.get_status_display()}"

    @property
    def is_open(self) -> bool:
        return self.status in self.OPEN

    @property
    def is_editable(self) -> bool:
        """Quantities may change until approval locks the bill."""
        return self.status in self.OPEN

    @property
    def next_status(self):
        index = self.ORDER.index(self.status)
        return self.ORDER[index + 1] if index + 1 < len(self.ORDER) else None


class RABillLine(models.Model):
    """
    One work-order line on one RA bill: what was claimed, what we certified.

    `certified_qty` NULL means "the engineer has not looked yet", which is a
    different fact from "certified zero". The ladder uses the claimed quantity
    until then, and the screen shows both side by side.
    """
    ra_bill = models.ForeignKey(RABill, on_delete=models.CASCADE, related_name="lines")
    po_line = models.ForeignKey(
        "projects.PurchaseOrderLine", on_delete=models.PROTECT, related_name="ra_bill_lines")

    claimed_qty = models.DecimalField(
        max_digits=14, decimal_places=3, default=0, validators=[MinValueValidator(0)])
    certified_qty = models.DecimalField(
        max_digits=14, decimal_places=3, null=True, blank=True,
        validators=[MinValueValidator(0)])

    # FROZEN COPIES from the PO line at creation — see the module docstring.
    rate = models.DecimalField(max_digits=12, decimal_places=2)
    gst_percent = models.DecimalField(max_digits=5, decimal_places=2)
    discount_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    remark = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(fields=["ra_bill", "po_line"],
                                    name="finance_one_line_per_po_line_per_bill"),
        ]

    def __str__(self) -> str:
        return f"{self.ra_bill.number} · line {self.po_line_id}"

    @property
    def qty_for_money(self) -> Decimal:
        """Certified once certified, the claim until then."""
        return self.certified_qty if self.certified_qty is not None else self.claimed_qty


class RetentionRelease(models.Model):
    """
    Retention handed back to the contractor. Normally once, after the defect
    liability period; recorded as its own ledger so the balance is a sum, never
    a stored figure.
    """
    purchase_order = models.ForeignKey(
        "projects.PurchaseOrder", on_delete=models.PROTECT, related_name="retention_releases")
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0)])
    released_on = models.DateField()
    released_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="retention_released")
    reference = models.CharField(max_length=60, blank=True)
    note = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["released_on", "id"]

    def __str__(self) -> str:
        return f"Retention {self.amount} on {self.purchase_order.number}"


class VendorInvoice(models.Model):
    """
    A supplier's invoice against a material purchase order, typed from paper.

    ⚠ THE FIGURES ARE THE VENDOR'S, NOT OURS. taxable / gst / total are what
      their invoice says; the only rule is total = taxable + gst to the paisa.
      Whether it matches our order is a question calc.po_settlement answers by
      comparing, never by refusing to record what arrived in the post.

    Status (open / part-paid / settled) is DERIVED from payments in calc.
    """
    purchase_order = models.ForeignKey(
        "projects.PurchaseOrder", on_delete=models.PROTECT, related_name="vendor_invoices")
    number = models.CharField(max_length=20, unique=True, help_text="VB-000001, our reference")
    vendor_invoice_no = models.CharField(max_length=60)
    invoice_date = models.DateField()
    taxable = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0)])
    gst = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0)])
    total = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0)])
    note = models.CharField(max_length=300, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="vendor_invoices_recorded")
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-invoice_date", "-id"]

    def __str__(self) -> str:
        return f"{self.number} · {self.vendor_invoice_no} · {self.purchase_order.number}"


class VendorPayment(models.Model):
    """
    Money that left the bank, to a vendor or contractor. ONE register for both
    document families — the accountant keys this into Tally.

    ⚠ `amount` IS WHAT LEFT THE BANK and `tds_amount` what was withheld and
      will be deposited with the department. Neither includes the other.

    ⚠ `vendor` IS A COPY of the order's vendor, so the register filters by
      vendor without a join through the order.
    """

    class Kind(models.TextChoices):
        ADVANCE = "advance", "Advance"
        AGAINST_INVOICE = "against_invoice", "Against invoice"
        RA_BILL = "ra_bill", "RA bill"
        RETENTION_RELEASE = "retention_release", "Retention release"

    class Mode(models.TextChoices):
        NEFT = "neft", "NEFT / RTGS"
        CHEQUE = "cheque", "Cheque"
        UPI = "upi", "UPI"
        CASH = "cash", "Cash"
        OTHER = "other", "Other"

    number = models.CharField(max_length=20, unique=True, help_text="PV-000001")
    vendor = models.ForeignKey("masters.Vendor", on_delete=models.PROTECT, related_name="payments")
    purchase_order = models.ForeignKey(
        "projects.PurchaseOrder", on_delete=models.PROTECT, related_name="payments")
    ra_bill = models.ForeignKey(RABill, on_delete=models.PROTECT, null=True, blank=True,
                                related_name="payments")
    vendor_invoice = models.ForeignKey(VendorInvoice, on_delete=models.PROTECT, null=True,
                                       blank=True, related_name="payments")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    paid_on = models.DateField()
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0)])
    tds_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0,
                                     validators=[MinValueValidator(0)])
    mode = models.CharField(max_length=10, choices=Mode.choices, default=Mode.NEFT)
    reference = models.CharField(max_length=60, blank=True, help_text="UTR, cheque number…")
    note = models.CharField(max_length=300, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="vendor_payments_recorded")
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-paid_on", "-id"]
        indexes = [
            models.Index(fields=["purchase_order", "kind"]),
            models.Index(fields=["paid_on"]),
        ]

    def __str__(self) -> str:
        return f"{self.number} · {self.vendor.name} · {self.amount}"

    @property
    def document_number(self) -> str:
        """What the register prints in its Document column: RA bill, invoice or order."""
        if self.ra_bill_id:
            return self.ra_bill.number
        if self.vendor_invoice_id:
            return self.vendor_invoice.number
        return self.purchase_order.number
