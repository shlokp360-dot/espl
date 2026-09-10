"""
Sales: the units in a building, who asked about them, who bought them, and
what has been collected against each sale.

>>> ANCHOR: SALES-MODEL <<<

THE CHAIN, IN ONE LINE
    Unit  ←  Booking  →  Customer
                ├── PaymentMilestone   the construction-linked schedule (% rows)
                ├── Demand             a demand letter, frozen from one milestone
                ├── CustomerReceipt    money received, on a demand or on account
                └── BookingEvent       what happened to the booking, and who did it
    Enquiry → SiteVisit                the funnel before a booking exists

⚠ STATUS IS DERIVED WHEREVER IT CAN BE. A unit's status is read from its
    bookings, a demand's from its receipts, and nobody maintains either — the
    same principle as compliance status and delay days. The one status somebody
    TYPES is the booking's own (booked → agreement → registered, or cancelled),
    because those are events a person decides, not arithmetic.

⚠ ONE LIVE BOOKING PER UNIT. A flat sold twice is the worst mistake a developer
    can make, and it is refused three ways: `Booking.clean()`, the service that
    creates bookings, and a partial unique index on the table. The index is the
    one that holds when two people press Book at the same second.

⚠ COPY, DON'T LINK. A demand freezes the amount and GST % it was raised with.
    Reschedule the milestones afterwards and the letter already sent does not
    change under the customer's feet.

⚠ ARITHMETIC LIVES IN `sales/calc.py`. Nothing here adds two numbers.
"""
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q

from masters.models import digits_only
from projects.bom_models import NumberSeries

pan_format = RegexValidator(
    r"^$|^[A-Z]{5}[0-9]{4}[A-Z]$", "A PAN is 10 characters, e.g. ABCDE1234F.")


class UnitKind(models.TextChoices):
    ONE_BHK = "1bhk", "1 BHK"
    TWO_BHK = "2bhk", "2 BHK"
    THREE_BHK = "3bhk", "3 BHK"
    FOUR_BHK = "4bhk", "4 BHK"
    PENTHOUSE = "penthouse", "Penthouse"
    SHOP = "shop", "Shop"
    OFFICE = "office", "Office"
    OTHER = "other", "Other"


class Unit(models.Model):
    """
    One saleable unit in one building — a flat, a shop, an office.

    ⚠ `status` IS A PROPERTY, NOT A COLUMN. See `sales.calc.unit_status`. The
      list screens hand the bookings down in bulk and never touch this property,
      because a query per unit on a 200-unit grid is the shape of a slow screen.
    """

    project = models.ForeignKey("projects.Project", on_delete=models.PROTECT, related_name="units")
    number = models.CharField(max_length=20, help_text='e.g. "A-101".')
    block = models.CharField(max_length=20, blank=True)
    floor = models.IntegerField(default=0)
    kind = models.CharField(max_length=12, choices=UnitKind.choices, default=UnitKind.TWO_BHK)
    carpet_sqft = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"),
                                      validators=[MinValueValidator(0)])
    saleable_sqft = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"),
                                        validators=[MinValueValidator(0)])
    # ⚠ THE WHOLE UNIT, EX-GST. Not a rate per sqft — the price list is written
    #   per unit, and the agreement value on the booking starts from this figure
    #   and may be negotiated away from it.
    base_price = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"),
                                     validators=[MinValueValidator(0)])
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["project", "block", "floor", "number"]
        constraints = [
            models.UniqueConstraint(fields=["project", "number"], name="one_unit_number_per_project"),
        ]

    def __str__(self):
        return f"{self.number} — {self.project.code}"

    @property
    def active_booking(self):
        """The booking that is not cancelled, or None. One query — see the note above."""
        return (self.bookings.exclude(status=Booking.Status.CANCELLED)
                .order_by("-id").first())

    @property
    def status(self):
        from sales import calc
        return calc.unit_status(self, list(self.bookings.order_by("id")))


class Customer(models.Model):
    """
    The person who buys. Identified by phone, exactly as a vendor is.

    ⚠ PHONE IS THE IDENTITY, NEVER THE NAME. Two Patels with two flats are two
      customers; one Patel typed twice is one. The booking form looks the phone
      up first and creates a customer only when nobody answers to it.
    """

    name = models.CharField(max_length=160)
    phone = models.CharField(max_length=15, unique=True, validators=[digits_only],
                             help_text="Digits only. This is the customer's identity.")
    email = models.EmailField(blank=True)
    pan = models.CharField(max_length=10, blank=True, validators=[pan_format],
                           help_text="Needed on the agreement and for TDS. Upper case.")
    address = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.phone})"

    def save(self, *args, **kwargs):
        self.pan = (self.pan or "").strip().upper()
        super().save(*args, **kwargs)


class EnquirySource(models.TextChoices):
    WALK_IN = "walkin", "Walk-in"
    REFERRAL = "referral", "Referral"
    BROKER = "broker", "Broker"
    PORTAL = "portal", "Portal"
    HOARDING = "hoarding", "Hoarding"
    OTHER = "other", "Other"


class Enquiry(models.Model):
    """
    Somebody who asked. Not a customer until they book — the name and phone are
    typed here and copied across at booking, so a hundred window-shoppers do not
    fill the customer list.
    """

    class Stage(models.TextChoices):
        NEW = "new", "New"
        VISITED = "visited", "Visited"
        NEGOTIATING = "negotiating", "Negotiating"
        BOOKED = "booked", "Booked"
        LOST = "lost", "Lost"

    OPEN_STAGES = [Stage.NEW, Stage.VISITED, Stage.NEGOTIATING]

    project = models.ForeignKey("projects.Project", on_delete=models.PROTECT, related_name="enquiries")
    name = models.CharField(max_length=160)
    phone = models.CharField(max_length=15, validators=[digits_only])
    email = models.EmailField(blank=True)
    source = models.CharField(max_length=10, choices=EnquirySource.choices, default=EnquirySource.WALK_IN)
    broker_name = models.CharField(max_length=120, blank=True)
    interested_in = models.CharField(max_length=12, choices=UnitKind.choices, blank=True)
    budget = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True,
                                 validators=[MinValueValidator(0)])
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name="enquiries_assigned")
    stage = models.CharField(max_length=12, choices=Stage.choices, default=Stage.NEW)
    lost_reason = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name_plural = "enquiries"

    def __str__(self):
        return f"{self.name} — {self.project.code}"

    @property
    def is_open(self):
        return self.stage in self.OPEN_STAGES


class SiteVisit(models.Model):
    """One visit to the site by one enquiry. Recording it moves the stage to Visited."""

    enquiry = models.ForeignKey(Enquiry, on_delete=models.CASCADE, related_name="visits")
    visited_on = models.DateField()
    note = models.CharField(max_length=300, blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name="site_visits_recorded")

    class Meta:
        ordering = ["-visited_on", "-id"]

    def __str__(self):
        return f"{self.enquiry.name} visited {self.visited_on}"


def _number(key, prefix):
    return f"{prefix}-{NumberSeries.take_next(key):06d}"


class Booking(models.Model):
    """
    One unit sold to one customer. The document everything else hangs off.

    >>> ANCHOR: SALES-ONE-BOOKING <<<
    ⚠⚠ A UNIT MAY HAVE AT MOST ONE BOOKING THAT IS NOT CANCELLED. Enforced by
       `clean()`, by `services.book_unit`, and by the partial unique index in
       Meta. The index is what holds under a race; the other two are what give
       a person a sentence instead of an IntegrityError.

    ⚠ THE LADDER OF STATUSES IS TYPED, NOT DERIVED, because each rung is a
      decision with a date: booked → agreement (the agreement is signed) →
      registered (the sale deed is registered). Cancelled can happen from
      booked or agreement, never from registered — a registered sale is
      somebody else's property.

    ⚠ `agreement_value` IS EX-GST, like every figure in this system. GST is
      added on every demand at the booking's `gst_percent`, frozen on the
      demand at the moment it is raised.
    """

    class Status(models.TextChoices):
        BOOKED = "booked", "Booked"
        AGREEMENT = "agreement", "Agreement"
        REGISTERED = "registered", "Registered"
        CANCELLED = "cancelled", "Cancelled"

    LIVE_STATUSES = [Status.BOOKED, Status.AGREEMENT, Status.REGISTERED]

    number = models.CharField(max_length=12, unique=True, blank=True)
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="bookings")
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="bookings")
    enquiry = models.ForeignKey(Enquiry, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="bookings")
    booked_on = models.DateField()
    agreement_value = models.DecimalField(max_digits=14, decimal_places=2,
                                          validators=[MinValueValidator(Decimal("0.01"))])
    # 5% for ordinary residential, 1% for affordable housing. Editable per booking.
    gst_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("5"),
                                      validators=[MinValueValidator(0)])
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.BOOKED)
    agreement_on = models.DateField(null=True, blank=True)
    registered_on = models.DateField(null=True, blank=True)
    cancelled_on = models.DateField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=300, blank=True)
    refund_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    # Set by transfer_booking: the customer this sale was moved away from.
    transferred_from = models.ForeignKey(Customer, on_delete=models.PROTECT, null=True, blank=True,
                                         related_name="bookings_transferred_away")
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="bookings_created")

    class Meta:
        ordering = ["-booked_on", "-id"]
        constraints = [
            # >>> ANCHOR: SALES-ONE-BOOKING <<<
            models.UniqueConstraint(fields=["unit"], condition=~Q(status="cancelled"),
                                    name="one_live_booking_per_unit"),
        ]

    def __str__(self):
        return f"{self.number} — {self.unit.number}"

    @property
    def is_live(self):
        return self.status != self.Status.CANCELLED

    def clean(self):
        if self.status == self.Status.CANCELLED:
            return
        clash = Booking.objects.filter(unit_id=self.unit_id).exclude(status=self.Status.CANCELLED)
        if self.pk:
            clash = clash.exclude(pk=self.pk)
        other = clash.first()
        if other:
            raise ValidationError(
                f"{self.unit.number} already has a live booking, {other.number} "
                f"({other.get_status_display()}). Cancel that one first.")

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = _number("booking", "BK")
        super().save(*args, **kwargs)


class BookingEvent(models.Model):
    """
    What happened to a booking, and who did it. Append-only, like UserEvent.

    ⚠ `detail` IS A SENTENCE, NOT A DIFF — "Transferred from Mehta to Shah" is
      what somebody wants to read, and it is written once, here.
    """

    class Kind(models.TextChoices):
        BOOKED = "booked", "Booked"
        AGREEMENT = "agreement", "Agreement signed"
        REGISTERED = "registered", "Registered"
        CANCELLED = "cancelled", "Cancelled"
        TRANSFERRED = "transferred", "Transferred"
        DEMAND = "demand", "Demand raised"
        RECEIPT = "receipt", "Receipt recorded"
        SCHEDULE = "schedule", "Schedule changed"

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="events")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    detail = models.CharField(max_length=300, blank=True)
    by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                           null=True, blank=True, related_name="booking_events")
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["at", "id"]

    def __str__(self):
        return f"{self.booking.number}: {self.get_kind_display()}"


class PaymentMilestone(models.Model):
    """
    One row of the construction-linked payment schedule.

    >>> ANCHOR: SALES-SCHEDULE <<<
    ⚠ THE PERCENTS OF ONE BOOKING MUST TOTAL 100. Checked by
      `calc.validate_schedule` whenever the schedule is written as a whole; a
      schedule that adds to 95 leaves 5% of the flat never demanded, and one
      that adds to 105 sends a letter for money that was never agreed.

    ⚠ `task_header` IS THE LINK TO THE SITE. A milestone tied to "3rd slab" on
      the work board becomes due the day the last subtask under that header is
      ticked done — `services.raise_demands_for_milestone` raises the letters
      for every booking on the project in one go. A milestone with no header
      ("On booking", "On possession") is raised by hand.
    """

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="milestones")
    sequence = models.PositiveIntegerField(default=1)
    name = models.CharField(max_length=120)
    percent = models.DecimalField(max_digits=6, decimal_places=2,
                                  validators=[MinValueValidator(0)])
    due_on = models.DateField(null=True, blank=True)
    task_header = models.ForeignKey("tasks.TaskHeader", on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name="payment_milestones")

    class Meta:
        ordering = ["booking", "sequence", "id"]

    def __str__(self):
        return f"{self.sequence}. {self.name} ({self.percent}%)"


class Demand(models.Model):
    """
    A demand letter: "this much is now due, by this date".

    ⚠ FROZEN. `amount` and `gst_percent` are copied from the milestone and the
      booking at the moment the letter is raised, and never re-read. The letter
      the customer holds must match the row here for as long as either exists.

    ⚠ STATUS IS DERIVED FROM RECEIPTS — `calc.demand_status`. Open, part-paid
      or paid, and nobody types it.
    """

    number = models.CharField(max_length=12, unique=True, blank=True)
    booking = models.ForeignKey(Booking, on_delete=models.PROTECT, related_name="demands")
    milestone = models.ForeignKey(PaymentMilestone, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name="demands")
    raised_on = models.DateField()
    due_on = models.DateField()
    amount = models.DecimalField(max_digits=14, decimal_places=2,
                                 validators=[MinValueValidator(Decimal("0.01"))])
    gst_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("5"))
    note = models.CharField(max_length=300, blank=True)
    raised_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                  null=True, blank=True, related_name="demands_raised")

    class Meta:
        ordering = ["raised_on", "id"]

    def __str__(self):
        return f"{self.number} — {self.booking.number}"

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = _number("demand", "DL")
        super().save(*args, **kwargs)

    # Convenience for a single document; list screens use calc directly.
    @property
    def gst_amount(self):
        from sales import calc
        return calc.demand_gst(self)

    @property
    def total(self):
        from sales import calc
        return calc.demand_total(self)


class ReceiptMode(models.TextChoices):
    CHEQUE = "cheque", "Cheque"
    NEFT = "neft", "NEFT / RTGS"
    UPI = "upi", "UPI"
    CASH = "cash", "Cash"
    OTHER = "other", "Other"


class CustomerReceipt(models.Model):
    """
    Money received from a customer.

    ⚠ A RECEIPT MAY SIT ON A DEMAND OR ON ACCOUNT. A customer who pays before
      the letter is raised is not refused; the receipt has no demand and the
      ledger still credits it.

    ⚠ TDS IS PART OF WHAT THE CUSTOMER PAID. When the agreement value is above
      fifty lakh the buyer withholds 1% and deposits it with the government in
      the developer's name (section 194-IA). The customer is credited for
      `amount + tds_amount`; the bank received only `amount`. Both are kept.
    """

    number = models.CharField(max_length=12, unique=True, blank=True)
    booking = models.ForeignKey(Booking, on_delete=models.PROTECT, related_name="receipts")
    demand = models.ForeignKey(Demand, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name="receipts")
    received_on = models.DateField()
    amount = models.DecimalField(max_digits=14, decimal_places=2,
                                 validators=[MinValueValidator(Decimal("0.01"))])
    mode = models.CharField(max_length=10, choices=ReceiptMode.choices, default=ReceiptMode.NEFT)
    reference = models.CharField(max_length=120, blank=True,
                                 help_text="Cheque number, UTR, UPI reference.")
    tds_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"),
                                     validators=[MinValueValidator(0)])
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name="customer_receipts_recorded")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["received_on", "id"]

    def __str__(self):
        return f"{self.number} — {self.booking.number}"

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = _number("customer_receipt", "RC")
        super().save(*args, **kwargs)

    @property
    def credit(self):
        from sales import calc
        return calc.receipt_credit(self)
