"""
The acts of selling: booking a unit, raising a demand, recording money,
cancelling and transferring. Every write to a booking goes through here.

>>> ANCHOR: SALES-SERVICES <<<

⚠ EACH ONE IS ATOMIC AND RAISES `SalesError` WITH A SENTENCE. The view
  catches it and shows it; nothing half-written survives a refusal. A view
  never writes a Booking, a Demand or a receipt directly.

⚠ EVERY ACT LEAVES A `BookingEvent`. Six months later the question is "who
  cancelled this and when", and the answer must not depend on somebody having
  remembered to write it down.
"""
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from sales import calc
from sales.models import (
    Booking, BookingEvent, Customer, CustomerReceipt, Demand, Enquiry, PaymentMilestone,
)
from tasks.models import Subtask


class SalesError(Exception):
    """A refusal with a reason a person can read."""


def _event(booking, kind, detail, by):
    BookingEvent.objects.create(booking=booking, kind=kind, detail=detail[:300], by=by)


def find_or_create_customer(phone, name="", email="", pan="", address=""):
    """
    ⚠ BY PHONE, NEVER BY NAME. An existing customer's details are NOT
      overwritten from a booking form — that belongs on their own record.
    """
    phone = (phone or "").strip()
    if not phone.isdigit():
        raise SalesError("A customer's phone is digits only, and it is required.")
    existing = Customer.objects.filter(phone=phone).first()
    if existing:
        return existing, False
    if not (name or "").strip():
        raise SalesError(f"No customer answers to {phone}. Type a name to create one.")
    customer = Customer(name=name.strip(), phone=phone, email=(email or "").strip(),
                        pan=(pan or "").strip().upper(), address=(address or "").strip())
    try:
        customer.full_clean()
    except ValidationError as error:
        raise SalesError(" ".join(" ".join(v) for v in error.message_dict.values()))
    customer.save()
    return customer, True


def write_schedule(booking, rows, by=None, note="Schedule saved"):
    """
    >>> ANCHOR: SALES-SCHEDULE <<<
    Replace the booking's schedule with `rows` — dicts of name, percent and
    optional due_on / task_header. Refused unless the percents total 100.

    ⚠ A MILESTONE THAT ALREADY HAS A DEMAND IS KEPT AS IT IS. Its row cannot
      be deleted from under the letter; the new rows are matched by sequence.
    """
    clean = []
    for index, row in enumerate(rows, 1):
        name = (row.get("name") or "").strip()
        if not name:
            continue
        try:
            percent = Decimal(str(row.get("percent") or "0"))
        except ArithmeticError:
            raise SalesError(f"Row {index}: the percent is not a number.")
        if percent < 0:
            raise SalesError(f"Row {index}: a percent cannot be negative.")
        clean.append({"name": name[:120], "percent": percent,
                      "due_on": row.get("due_on"), "task_header": row.get("task_header")})
    try:
        calc.validate_schedule(clean)
    except ValueError as error:
        raise SalesError(str(error))

    with transaction.atomic():
        existing = {m.sequence: m for m in booking.milestones.all()}
        demanded_ids = set(Demand.objects.filter(booking=booking, milestone__isnull=False)
                           .values_list("milestone_id", flat=True))
        # ⚠ THE 100 IS CHECKED ON WHAT WILL BE SAVED. A demanded milestone keeps
        #   its percent whatever the row says, so a row that tries to change it
        #   is refused rather than silently ignored — otherwise the rows could
        #   add to 100 and the saved schedule to something else.
        for sequence, row in enumerate(clean, 1):
            current = existing.get(sequence)
            if current and current.pk in demanded_ids and row["percent"] != current.percent:
                raise SalesError(
                    f"Milestone {sequence} ({current.name}) already has a demand letter; "
                    f"its {current.percent}% cannot change.")
        kept = []
        for sequence, row in enumerate(clean, 1):
            current = existing.pop(sequence, None)
            if current is None:
                current = PaymentMilestone(booking=booking, sequence=sequence)
            if current.pk and current.pk in demanded_ids:
                # The letter is out; only the dates and the link may move.
                current.due_on = row["due_on"]
                current.task_header = row["task_header"]
            else:
                current.name, current.percent = row["name"], row["percent"]
                current.due_on, current.task_header = row["due_on"], row["task_header"]
            current.save()
            kept.append(current)
        for leftover in existing.values():
            if leftover.pk in demanded_ids:
                raise SalesError(
                    f"Milestone {leftover.sequence} ({leftover.name}) already has a demand "
                    f"letter and cannot be removed.")
            leftover.delete()
        if by is not None:
            _event(booking, BookingEvent.Kind.SCHEDULE, note, by)
    return kept


def book_unit(unit, *, phone, name="", email="", pan="", address="", agreement_value,
              gst_percent=Decimal("5"), booked_on=None, schedule=None, enquiry=None, by=None):
    """
    Sell a unit. Creates the customer if the phone is new, the booking, its
    schedule, and moves the enquiry to Booked.

    >>> ANCHOR: SALES-ONE-BOOKING <<<
    ⚠ REFUSED IF THE UNIT HAS A LIVE BOOKING — checked here so the person gets
      a sentence, and held by the partial unique index if two people race.
    """
    if not unit.is_active:
        raise SalesError(f"{unit.number} is inactive and cannot be booked.")
    try:
        value = Decimal(str(agreement_value))
    except ArithmeticError:
        raise SalesError("The agreement value is not a number.")
    if value <= 0:
        raise SalesError("The agreement value must be more than zero.")
    try:
        gst = Decimal(str(gst_percent))
    except ArithmeticError:
        raise SalesError("The GST % is not a number.")
    if gst < 0:
        raise SalesError("The GST % cannot be negative.")

    rows = schedule if schedule is not None else [
        {"name": name_, "percent": pct} for name_, pct in calc.DEFAULT_SCHEDULE]

    with transaction.atomic():
        live = Booking.objects.filter(unit=unit).exclude(status=Booking.Status.CANCELLED).first()
        if live:
            raise SalesError(
                f"{unit.number} already has a live booking, {live.number} "
                f"({live.get_status_display()}). Cancel that one first.")
        customer, _created = find_or_create_customer(phone, name, email, pan, address)
        booking = Booking(unit=unit, customer=customer, enquiry=enquiry,
                          booked_on=booked_on or timezone.localdate(),
                          agreement_value=calc._money(value), gst_percent=gst, created_by=by)
        try:
            booking.full_clean(exclude=["number"])
        except ValidationError as error:
            raise SalesError(" ".join(" ".join(v) for v in error.message_dict.values()))
        booking.save()
        write_schedule(booking, rows)
        _event(booking, BookingEvent.Kind.BOOKED,
               f"Booked to {customer.name} at Rs {booking.agreement_value}", by)
        if enquiry is not None and enquiry.stage != Enquiry.Stage.BOOKED:
            enquiry.stage = Enquiry.Stage.BOOKED
            enquiry.save(update_fields=["stage", "updated_at"])
    return booking


def raise_demand(booking, milestone=None, *, due_on=None, raised_on=None, amount=None,
                 note="", by=None):
    """
    Raise a demand letter. From a milestone (the amount is its % of the
    agreement value) or, with `amount`, an ad-hoc letter.

    ⚠ ONE LETTER PER MILESTONE. A second demand for the same slab is refused;
      the first letter is the one the customer holds.
    """
    if not booking.is_live:
        raise SalesError(f"{booking.number} is cancelled. Nothing more can be demanded on it.")
    if milestone is not None:
        if milestone.booking_id != booking.id:
            raise SalesError("That milestone belongs to another booking.")
        if Demand.objects.filter(milestone=milestone).exists():
            raise SalesError(f"{milestone.name} already has a demand letter.")
        value = calc.milestone_amount(booking.agreement_value, milestone.percent)
        due = due_on or milestone.due_on
    else:
        if amount is None:
            raise SalesError("Choose a milestone or type an amount.")
        try:
            value = calc._money(Decimal(str(amount)))
        except ArithmeticError:
            raise SalesError("The amount is not a number.")
        due = due_on
    if value <= 0:
        raise SalesError("A demand for zero cannot be raised.")
    raised = raised_on or timezone.localdate()
    if due is None:
        raise SalesError("Type the date this demand is due by.")
    if due < raised:
        raise SalesError("The due date is before the date it is raised.")

    with transaction.atomic():
        demand = Demand.objects.create(
            booking=booking, milestone=milestone, raised_on=raised, due_on=due,
            amount=value, gst_percent=booking.gst_percent, note=note[:300], raised_by=by)
        _event(booking, BookingEvent.Kind.DEMAND,
               f"{demand.number} raised for Rs {calc.demand_total(demand)}"
               + (f" ({milestone.name})" if milestone else ""), by)
    return demand


def header_is_complete(task_header):
    """A header is done when every subtask under it is done, and it has at least one."""
    rows = list(Subtask.objects.filter(header=task_header))
    return bool(rows) and all(row.status == Subtask.Status.DONE for row in rows)


def raise_demands_for_milestone(project, task_header, *, due_days=15, by=None, require_done=True):
    """
    >>> ANCHOR: SALES-SCHEDULE <<<
    The slab is cast: raise the letter on every live booking of the project
    whose schedule links this header and has no demand for it yet. Returns
    the demands raised. Skips bookings that already have one — safe to run
    twice.
    """
    if task_header.project_id != project.id:
        raise SalesError("That task header belongs to another project.")
    if require_done and not header_is_complete(task_header):
        raise SalesError(f"{task_header.name} is not finished yet — not every subtask is done.")
    today = timezone.localdate()
    raised = []
    milestones = (PaymentMilestone.objects
                  .filter(task_header=task_header, booking__unit__project=project)
                  .exclude(booking__status=Booking.Status.CANCELLED)
                  .exclude(demands__isnull=False)
                  .select_related("booking"))
    for milestone in milestones:
        raised.append(raise_demand(milestone.booking, milestone,
                                   due_on=milestone.due_on or today + timedelta(days=due_days),
                                   raised_on=today, by=by))
    return raised


def record_receipt(booking, *, amount, received_on=None, mode="neft", reference="",
                   tds_amount=Decimal("0"), demand=None, by=None):
    """Money in. On a demand, or on account when no demand is given."""
    if not booking.is_live:
        raise SalesError(f"{booking.number} is cancelled. Record a refund instead, not a receipt.")
    try:
        value = calc._money(Decimal(str(amount)))
        tds = calc._money(Decimal(str(tds_amount or 0)))
    except ArithmeticError:
        raise SalesError("The amount is not a number.")
    if value <= 0:
        raise SalesError("A receipt must be for more than zero.")
    if tds < 0:
        raise SalesError("TDS cannot be negative.")
    if demand is not None and demand.booking_id != booking.id:
        raise SalesError("That demand belongs to another booking.")

    with transaction.atomic():
        receipt = CustomerReceipt.objects.create(
            booking=booking, demand=demand, received_on=received_on or timezone.localdate(),
            amount=value, mode=mode, reference=reference[:120], tds_amount=tds, recorded_by=by)
        _event(booking, BookingEvent.Kind.RECEIPT,
               f"{receipt.number}: Rs {calc.receipt_credit(receipt)} received"
               + (f" against {demand.number}" if demand else " on account"), by)
    return receipt


def mark_agreement(booking, on=None, by=None):
    if booking.status != Booking.Status.BOOKED:
        raise SalesError(f"{booking.number} is {booking.get_status_display()}; "
                         "only a Booked sale can move to Agreement.")
    booking.status = Booking.Status.AGREEMENT
    booking.agreement_on = on or timezone.localdate()
    booking.save(update_fields=["status", "agreement_on"])
    _event(booking, BookingEvent.Kind.AGREEMENT, f"Agreement signed on {booking.agreement_on}", by)
    return booking


def mark_registered(booking, on=None, by=None):
    if booking.status not in (Booking.Status.BOOKED, Booking.Status.AGREEMENT):
        raise SalesError(f"{booking.number} is {booking.get_status_display()}; "
                         "it cannot be registered from there.")
    booking.status = Booking.Status.REGISTERED
    booking.registered_on = on or timezone.localdate()
    if booking.agreement_on is None:
        booking.agreement_on = booking.registered_on
    booking.save(update_fields=["status", "registered_on", "agreement_on"])
    _event(booking, BookingEvent.Kind.REGISTERED, f"Registered on {booking.registered_on}", by)
    return booking


def cancel_booking(booking, *, reason, deduction_pct=Decimal("0"), on=None, by=None):
    """
    Cancel. The unit becomes bookable again; the refund figure is recorded.

    ⚠ A REGISTERED SALE CANNOT BE CANCELLED HERE. The deed is registered; undoing
      it is a legal act outside this system.
    """
    if booking.status == Booking.Status.REGISTERED:
        raise SalesError(f"{booking.number} is registered. A registered sale cannot be cancelled here.")
    if booking.status == Booking.Status.CANCELLED:
        raise SalesError(f"{booking.number} is already cancelled.")
    if not (reason or "").strip():
        raise SalesError("Type the reason for cancelling.")
    try:
        pct = Decimal(str(deduction_pct or 0))
    except ArithmeticError:
        raise SalesError("The deduction % is not a number.")
    if pct < 0 or pct > 100:
        raise SalesError("The deduction % must be between 0 and 100.")

    with transaction.atomic():
        deduction, refund = calc.refund_on_cancel(booking, pct)
        booking.status = Booking.Status.CANCELLED
        booking.cancelled_on = on or timezone.localdate()
        booking.cancel_reason = reason.strip()[:300]
        booking.refund_amount = refund
        booking.save(update_fields=["status", "cancelled_on", "cancel_reason", "refund_amount"])
        _event(booking, BookingEvent.Kind.CANCELLED,
               f"Cancelled: {booking.cancel_reason}. Deduction Rs {deduction}, refund Rs {refund}", by)
    return booking


def transfer_booking(booking, new_customer, *, note="", by=None):
    """Move a live booking to another customer, keeping who it came from."""
    if not booking.is_live:
        raise SalesError(f"{booking.number} is cancelled and cannot be transferred.")
    if new_customer.id == booking.customer_id:
        raise SalesError(f"{booking.number} already belongs to {new_customer.name}.")
    with transaction.atomic():
        old = booking.customer
        booking.transferred_from = old
        booking.customer = new_customer
        booking.save(update_fields=["transferred_from", "customer"])
        _event(booking, BookingEvent.Kind.TRANSFERRED,
               f"Transferred from {old.name} to {new_customer.name}" + (f". {note}" if note else ""), by)
    return booking
