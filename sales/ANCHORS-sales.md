# ANCHORS — sales

Rows to add to `ANCHORS.md`, in its style. Each `>>> ANCHOR: NAME <<<` below
appears as a comment in the code at the place named.

## Rows for "How to use this"

```
Something wrong with...              Search for
-----------------------------------  -------------------------------------
a unit's status, or a customer's     ANCHOR: SALES-MODEL
  identity
a unit booked twice                  ANCHOR: SALES-ONE-BOOKING
a schedule that does not add to 100, ANCHOR: SALES-SCHEDULE
  or a demand raised for a slab
any rupee figure on a sales screen,  ANCHOR: SALES-CALC
  the demand letter or an export
a sales list screen that has got     ANCHOR: SALES-CALC-BULK
  slow
booking, cancelling, transferring,   ANCHOR: SALES-SERVICES
  raising a demand, recording money
who may open which sales screen      ANCHOR: SALES-SCREENS
```

## Rows for "Every anchor, and where it lives"

```
ANCHOR                     Lives in                        What it governs
-------------------------  ------------------------------  ------------------------------
SALES-MODEL                sales/models.py                 the chain Unit→Booking→Customer, derived statuses
SALES-ONE-BOOKING          sales/models.py, services.py    one live booking per unit, three ways
SALES-SCHEDULE             calc.py, models.py, services.py  percents total 100; header-linked demands
SALES-CALC                 sales/calc.py                   every sales figure, Decimal, one place
SALES-CALC-BULK            sales/calc.py                   list screens: two queries, not two per row
SALES-SERVICES             sales/services.py               every write to a booking, atomic, with a history row
SALES-SCREENS              sales/views.py                  who may read, edit, collect
```

## The long-form entries

### `SALES-MODEL` — `sales/models.py`
**Unit ← Booking → Customer, with the schedule, demands, receipts and history hanging off the
booking.** A customer is identified by PHONE, exactly as a vendor is — two Patels with two flats
are two customers, one Patel typed twice is one — and the booking form looks the phone up before
it creates anybody.

**⚠ STATUS IS DERIVED WHEREVER IT CAN BE.** A unit's status (available / booked / registered /
cancelled) is read from its bookings; a demand's (open / part-paid / paid) from its receipts.
Nobody maintains either, so nothing can quietly disagree with reality. The one typed status is the
booking's own ladder — booked → agreement → registered, or cancelled — because those are decisions
with dates, not arithmetic.

**⚠ CANCELLED ON A UNIT MEANS "WAS SOLD, IS FOR SALE AGAIN".** It is bookable, and the KPI counts
it with the available ones; the word stays on the grid so the person selling it knows there is a
history to look at.

**⚠ COPY, DON'T LINK.** A demand freezes `amount` and `gst_percent` at the moment it is raised.
Change the booking's GST afterwards and the letter the customer holds does not move. A test proves it.

### `SALES-ONE-BOOKING` — `sales/models.py`, `sales/services.py`
**A unit may have at most one booking that is not cancelled — enforced three ways.**
`Booking.clean()` and `services.book_unit` give a person a sentence naming the clashing booking;
the partial unique index `one_live_booking_per_unit` (`UniqueConstraint(fields=["unit"],
condition=~Q(status="cancelled"))`) is what holds when two people press Book in the same second.
Tested at all three levels, including the `IntegrityError` under a direct create.

### `SALES-SCHEDULE` — `sales/calc.py`, `sales/models.py`, `sales/services.py`
**The construction-linked payment schedule: rows of (name, percent), and the percents must total
exactly 100.** `calc.DEFAULT_SCHEDULE` is the eight-row template a new booking starts with
(10/10/10/15/15/15/15/10); the booking form shows it as editable rows and `calc.validate_schedule`
refuses anything else, with the actual total in the message.

**⚠⚠ THE 100 IS CHECKED ON WHAT WILL BE SAVED, NOT ON WHAT WAS TYPED.** A milestone that already
has a demand letter keeps its name and percent whatever the rows say — the letter is out. So a row
that tries to change that percent is REFUSED rather than silently kept, otherwise the typed rows
could add to 100 and the saved schedule to something else. Deleting such a row is refused too.

**⚠ A MILESTONE MAY LINK A HEADER TASK.** "A milestone is a header task" is the vocabulary rule, and
here it is literal: `PaymentMilestone.task_header` points at `tasks.TaskHeader`. When every subtask
under that header is Done, `services.raise_demands_for_milestone(project, header)` raises the
letter on every live booking of the project whose schedule links it and has no demand yet. Safe
to run twice; refused while the header is unfinished. The button is on the Collections screen.

### `SALES-CALC` — `sales/calc.py`
**Every figure a sales screen, the demand letter or an Excel export shows, one function each, all
`Decimal`, rounded half-up to the paisa where calculated.** `milestone_amount`, `demand_gst`,
`demand_total`, `booking_gst`, `booking_total`, `receipt_credit`, `collected`, `demanded`,
`outstanding`, `due_balance`, `overdue`, `demand_status`, `unit_status`, `ledger`,
`refund_on_cancel`, `suggested_tds`, `ageing_bucket`. A template never adds; a view never repeats a
formula. Sums are done in Python over prefetched rows, never in SQL — SQLite integer-divides
percentages.

**⚠ THE LEDGER CONVENTION.** A demand is a debit (the customer owes it), a receipt a credit. A
receipt's credit is `amount + tds_amount`: under section 194-IA the buyer withholds 1% above fifty
lakh and deposits it in the developer's name, so the customer is credited for both while the bank
received only the amount. `suggested_tds(booking, amount=None)` gives the 1% when the agreement
value crosses the threshold, zero below it.

**⚠ AN ON-ACCOUNT RECEIPT PAYS THE OLDEST OPEN DEMAND FIRST** (`allocate_receipts`) — the customer
paid before the letter or without quoting it, and the money is still theirs against the earliest
thing they owe. Excess stays as an advance and the ledger says so in words, not with a minus sign.

**⚠ REFUND ON CANCEL** is collected less a deduction that is a percent of the AGREEMENT value
(a forfeiture clause reads "10% of the consideration"), capped at what was actually collected.

### `SALES-CALC-BULK` — `sales/calc.py`
**`bulk_booking_figures`, `bulk_demand_figures`, `bulk_unit_status` — every list screen's
figures in two queries however many rows there are.** The dashboard, the unit grid, the booking
register, collections and receipts all use them. `sales/tests.py::QueryCounts` renders each screen
with 4 rows and then 24 and asserts fewer than 10 extra queries.

**⚠ `bulk_demand_figures` FETCHES EVERY DEMAND OF THE BOOKINGS INVOLVED, not only the ones listed** —
on-account receipts are allocated oldest-first across the whole booking, so a filtered list
would allocate wrongly if it saw only part of the picture.

### `SALES-SERVICES` — `sales/services.py`
**Every write to a booking is one function here, atomic, raising `SalesError` with a sentence, and
leaving a `BookingEvent` row.** `book_unit` (customer by phone, booking, schedule, marks the
enquiry Booked), `raise_demand` (one letter per milestone, or ad hoc), `raise_demands_for_milestone`,
`record_receipt`, `mark_agreement`, `mark_registered`, `cancel_booking` (refuses a registered
sale; records the refund), `transfer_booking` (keeps `transferred_from`), `write_schedule`.
A view never writes a Booking, a Demand or a receipt directly.

**⚠ A REGISTERED SALE CANNOT BE CANCELLED HERE.** The deed is registered; undoing it is a legal act
outside this system. A cancelled booking refuses further demands and receipts.

### `SALES-SCREENS` — `sales/views.py`
**Who may do what:** `sales.view` (Admin, Project manager, Accountant) reads everything, every PDF
and every Excel; `sales.edit` (Admin, Project manager) creates and edits units, enquiries and
bookings, cancels and transfers; `sales.collect` (Admin, Accountant) raises demands and records
receipts. The Collections and Receipts registers are READ by `sales.view`; the POSTs on them are
`sales.collect`. Buttons a role cannot use are hidden with `{{ user|can:… }}` and the view refuses
them anyway.

**⚠ THE DEMAND LETTER PDF** follows `po_pdf` exactly: WeasyPrint imported inside the view, tables not
flexbox, "Rs" not `₹`, and the test injects a fake module into `sys.modules`.

**⚠ RAW IDS ARE `.isdigit()`-GUARDED**, project-scoped objects are fetched scoped to the project
(`PaymentMilestone … booking=booking`, `TaskHeader … project=project`), and Booked on an enquiry is
set only by booking a unit — never from the stage dropdown — so the funnel cannot say Booked with
no booking behind it.
