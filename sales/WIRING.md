# Wiring the sales app into the shared files

Everything below goes into files this app must not edit itself. Apply in one commit
with the app.

## 1. `accounts/test_matrix.py` — `SCREENS`

The second column is what `address()` passes: `False` = no argument, `True` = id 1
(a 404 for an allowed role is fine; the test only asserts 403 vs not-403).

```python
    # ---- sales ------------------------------------------------------------
    ("sales_home",             False, {A, PM, ACC}),
    ("sales_units",            False, {A, PM, ACC}),
    ("sales_unit_new",         False, {A, PM}),
    ("sales_unit_form",        True,  {A, PM}),
    ("sales_units_bulk",       False, {A, PM}),
    ("sales_enquiries",        False, {A, PM, ACC}),
    ("sales_enquiry_new",      False, {A, PM}),
    ("sales_enquiry_form",     True,  {A, PM}),
    ("sales_booking_new",      True,  {A, PM}),
    ("sales_bookings",         False, {A, PM, ACC}),
    ("sales_booking",          True,  {A, PM, ACC}),
    ("sales_booking_cancel",   True,  {A, PM}),
    ("sales_booking_transfer", True,  {A, PM}),
    ("sales_customer_form",    True,  {A, PM}),
    ("sales_demand_new",       True,  {A, ACC}),
    ("sales_demand_pdf",       True,  {A, PM, ACC}),
    ("sales_receipt_new",      True,  {A, ACC}),
    ("sales_collections",      False, {A, PM, ACC}),
    ("sales_collections_excel", False, {A, PM, ACC}),
    ("sales_receipts",         False, {A, PM, ACC}),
    ("sales_receipts_excel",   False, {A, PM, ACC}),
```

## 2. `accounts/test_matrix.py` — `ACTIONS` (POST-only addresses)

```python
    # ---- sales ------------------------------------------------------------
    ("sales_enquiry_visit",     True,  {A, PM}),
    ("sales_enquiry_stage",     True,  {A, PM}),
    ("sales_booking_schedule",  True,  {A, PM}),
    ("sales_booking_mark",      True,  {A, PM}),
    ("sales_demands_for_header", False, {A, ACC}),
```

The GET+POST forms above (`sales_unit_new`, `sales_unit_form`, `sales_units_bulk`,
`sales_enquiry_new`, `sales_enquiry_form`, `sales_booking_new`, `sales_booking_cancel`,
`sales_booking_transfer`, `sales_customer_form`, `sales_demand_new`, `sales_receipt_new`)
carry the same `@requires` on both methods, so their SCREENS row covers the POST too.

## 3. `projects/help_panels.py`

```python
from sales.panels import PANELS as SALES_PANELS
PANELS.update(SALES_PANELS)
```

(or paste the sixteen entries in). Every sales template already calls
`{% infobutton "<key>" %}` / `{% infopanel "<key>" %}`; until merged they render nothing.
`sales/test_panels.py` keeps the entries inside the format rules and asserts the keys
used by the templates and the keys defined match exactly.

## 4. `templates/sales/_nav.html` — the tab list (already written)

| here          | url name            | label        | who sees it        |
|---------------|---------------------|--------------|--------------------|
| `home`        | `sales_home`        | Dashboard    | everyone with sales.view |
| `units`       | `sales_units`       | Units        | everyone with sales.view |
| `enquiries`   | `sales_enquiries`   | Enquiries    | everyone with sales.view |
| `bookings`    | `sales_bookings`    | Bookings     | everyone with sales.view |
| `collections` | `sales_collections` | Collections  | everyone with sales.view |
| `receipts`    | `sales_receipts`    | Receipts     | everyone with sales.view |

No tab is hidden by role: every tab is a read and `sales.view` is the door to the
module. Edit and collect buttons hide on the screens themselves.

## 5. `projects/hub.py`

The `sales` tile already exists (`url_name: sales_home`, `perm: sales.view`). Nothing to add.

## 6. `ANCHORS.md`

Add the rows and long-form entries from `sales/ANCHORS-sales.md`. Seven new anchors:
`SALES-MODEL`, `SALES-ONE-BOOKING`, `SALES-SCHEDULE`, `SALES-CALC`, `SALES-CALC-BULK`,
`SALES-SERVICES`, `SALES-SCREENS`. (`INFO-PANELS` appears in `sales/panels.py` as a
reference to the existing anchor, not a new one.) The drift count goes from 87 to 94.

## 7. `CLAUDE.md` — commands

```
python manage.py seed_sales_showcase   # units, enquiries, bookings, demands, receipts on the showcase projects · --remove
```

⚠ `seed_showcase --remove` will now be refused (a `Unit` PROTECTs its project) while sales
showcase data exists. Run `seed_sales_showcase --remove` first. Worth a line in
`projects/management/commands/seed_showcase.py`'s docstring, or a call to the sales removal
from inside its `remove()`.

## 8. Migrations

`sales/migrations/0001_initial.py` is included. `python manage.py migrate` on every install.
