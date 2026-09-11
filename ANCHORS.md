# ANCHORS — where to look when something needs changing

Search the codebase for `ANCHOR:` and you will land on every point where change
is expected. Each anchor comment says what else it affects, so you can judge the
blast radius before touching it.

**If a number on screen looks wrong, start here.** Find the anchor for that
number, read what it says it affects, and check those places too.

---

## How to use this

```
Something wrong with...              Search for
-----------------------------------  -------------------------------------
what the system suggests ordering    ANCHOR: BOM-CALC-TO-ORDER
budget vs planned, percentages       ANCHOR: BOM-CALC-GST-BASIS
an activity's budget                 ANCHOR: BOM-CALC-RESERVE
the Vend Rate cell, its grey         ANCHOR: VENDOR-RATE-CAPTURE
  suggestion, or Var % reading 0.0%
which materials appear in a dropdown ANCHOR: BOM-MATERIAL-FILTER
a number shown on the BOM SCREEN     ANCHOR: BOM-CALC-* (never the template)
a screen that has got slow           ANCHOR: BOM-CALC-BULK
a material's code                    ANCHOR: CODE-GEN
what sits behind the Master data     ANCHOR: MASTER-TABS
  tile, and its tabs
an activity's ₹/sqft, GST % or       ANCHOR: ACTIVITY-MASTER
  abbreviation
a rename that is refused, or a       ANCHOR: ACTIVITY-RENAME-BLOCKED
  budget that went to zero
an Excel import rejecting rows       ANCHOR: IMPORT-VALIDATE
a download containing the wrong      ANCHOR: MASTER-EXPORT-FOLLOWS-FILTERS
  rows, or too many
filtering purchase orders by status  ANCHOR: PO-STATUS-FILTER
a tab appearing that then 403s       ANCHOR: PO-DOORWAY
who may type in a BOM cell           ANCHOR: BOM-STOCK-ONLY
draft quantities not adding up       ANCHOR: PO-INVARIANT
GST number prompts                   ANCHOR: GSTIN-CAPTURE
received quantities                  ANCHOR: TASK-MODULE
who may open a screen or press a     ANCHOR: PERMS-MATRIX
  button
ADDING A ROLE, or changing what      ANCHOR: PERMS-ADD-A-ROLE
  an existing one may do
the Users screen and its safeguards  ANCHOR: USERS-SCREEN
what happened to an account          ANCHOR: USER-HISTORY
an empty launchpad on a brand-new    ANCHOR: BOOTSTRAP-ADMIN
  database, every tile refusing you
which tiles somebody sees            ANCHOR: HUB-TILES
a planned date, a duration or        ANCHOR: TASK-MODEL
  "days late"
the work board and its three adds    ANCHOR: TASK-BOARD
who may tick a subtask done          ANCHOR: TASK-MINE
delay reasons, and counting them     ANCHOR: TASK-DELAYS
deleting a task or a milestone       ANCHOR: TASK-DELETE
a KPI card that will not move as     ANCHOR: BOQ-LIVE-KPIS
  you type, or its grey sub-text
filtering the Analytics Work tab     ANCHOR: ANALYTICS-WORK-FILTERS
a bar in the wrong place on the      ANCHOR: TASK-SCHEDULE
  Gantt, or the month scale
a Gantt squeezed into the page, or   ANCHOR: TASK-SCHEDULE-SCALE
  how wide a day is
a milestone's dotted line, or two    ANCHOR: MILESTONE-LINE
  labels sitting on top of each other
a date that was moved, and what      ANCHOR: TASK-BASELINE
  it was before
a milestone saved a year from its    ANCHOR: TASK-WINDOW-WARNING
  own tasks
the wording inside an ⓘ panel, or    ANCHOR: INFO-PANELS
  a screen that has no ⓘ
a yellow box that should not be      the .note rule in base.html
  there, or should be shorter
what "spend" is allowed to mean      ANCHOR: ANALYTICS-MONEY
what is paid and what is owed        ANCHOR: ANALYTICS-SETTLEMENT
budget vs plan vs actual, and the    ANCHOR: ANALYTICS-BUDGET
  word "budget" instead of "reserve"
PTD, CPD and the fiscal year         ANCHOR: ANALYTICS-PERIOD
a chart drawn wrong                  ANCHOR: ANALYTICS-CHARTS
a compliance document, or who can    ANCHOR: COMPLIANCE-SCREENS
  download one
a checklist line one project does    ANCHOR: COMPLIANCE-PRUNING
  not need
whether something is Expired or      ANCHOR: COMPLIANCE-STATUS
  Missing
adding a checklist title or item     ANCHOR: COMPLIANCE-MASTER
a suggested expiry date              ANCHOR: COMPLIANCE-MASTER
the gross-to-net ladder on screen    ANCHOR: ANALYTICS-G2N
a due date, or 30-day default terms  ANCHOR: ANALYTICS-MONEY
```

⚠ `TASK-MODULE` HAS NOTHING TO DO WITH TASK MANAGEMENT. It is the goods-receipt
route in `projects/receipts.py` and it was named years — well, weeks — before
there was a `tasks` app. The two to search for when somebody asks about site
work are `TASK-MODEL` and `TASK-BOARD`.

---

## Every anchor, and where it lives

**⚠ THIS LIST DRIFTED ONCE AND IT MATTERS.** Slices 6, 7 and 8 added anchors to
the code without adding them here, so thirty-one of them were invisible to
anybody reading this file — which is the one file written to be read first. If
you add an `ANCHOR:` to the code, add its row here in the same commit.

To check for drift: search the code for `ANCHOR:`, compare against this table.

```
ANCHOR                     Lives in                        What it governs
-------------------------  ------------------------------  ------------------------------
BOM-CALC-GST-BASIS         projects/models.py              every BOM figure is ex-GST
BOM-CALC-RESERVE           projects/models.py, bom_calc.py  an activity's budget, live-linked
BOM-CALC-TO-ORDER          projects/bom_calc.py            typed quantity or zero
BOM-CALC-BULK              projects/bom_calc.py            queries must not grow per row
BOM-CALC-COMMITTED         projects/bom_calc.py            money already promised to vendors
BOM-CALC-DISCARD-PREVIEW   projects/bom_calc.py            what discarding a draft gives back
BOM-MATERIAL-FILTER        masters/models.py, views.py     which materials a dropdown offers
PLANNING-RATE              bom_calc.py, bom_models.py      planned rate, else the master rate
VENDOR-RATE-CAPTURE        po_service.py, bom_calc.py      what a vendor last charged, and reusing it
STOCK-ECHO                 projects/bom_calc.py            the same material holding stock twice
DRAFT-CONFLICT             bom_calc.py, views.py, bom.html  plan and draft disagreeing
PO-INVARIANT               projects/bom_calc.py            no stored copy of approved/in-draft
PO-PREVIEW                 projects/po_service.py          Post POs creates nothing
PO-TOTALS                  projects/bom_models.py          the gross-to-net ladder, ONE copy
PO-LINE-REFERENCE          projects/bom_models.py          what a PO line points back at
DISCONTINUED-BLOCK         po_service.py, views.py         a dead material stops the batch
DOCUMENT-TYPE              masters/models.py, po_service.py  PO or WO, from the vendor
DOC-TERMS                  masters/models.py, po_service.py  terms copied, then frozen
GSTIN-CAPTURE              masters/models.py, po_service.py  approval hard-blocks without one
LUMPSUM                    projects/views.py               value + rate → derived quantity
PO-PDF                     projects/views.py               approved onwards only
PO-SCREEN                  projects/views.py               vendors → documents → the document
PO-REGISTER                projects/views.py               every document, every project
PO-STATUS-FILTER           projects/views.py               status per project, and "not paid yet"
PO-DOORWAY                 views.py, _nav.html             which tabs a document offers, and to whom
BOM-STOCK-ONLY             projects/views.py               the site engineer writes stock, and only stock
BOQ-SCREEN                 bom_calc.py, views.py           the estimate screen
BOQ-LOCK                   models.py, admin.py             locked at Won, admin included
BOQ-REMOVE                 projects/views.py               taking a trade off an estimate
PROJECT-SCREEN             projects/views.py               creating and editing a project
PROJECT-STATUS             projects/views.py               Draft → Quoted → Won
PROJECT-ADDRESSES          projects/models.py              site and billing addresses
RATE-DEFAULTS              — retired —                     ₹/sqft moved to ACTIVITY-MASTER
CODE-GEN                   masters/codes.py, models.py     ACTIVITY-GROUP-SERIAL, assigned once
MATERIAL-ACTIVITY          masters/models.py               home activity and also-used-in
VENDOR-GROUP               masters/models.py               what a vendor IS, for searching
VENDOR-CLASSIFICATION      masters/models.py               group vs activity, kept apart
UOM-MASTER                 masters/models.py               the unit vocabulary, text not FK
MATERIAL-SCREEN            projects/master_views.py        the material list and form
VENDOR-SCREEN              projects/master_views.py        the vendor list and form
MASTER-EXCEL               projects/master_views.py        the round trip, both masters
MASTER-EXPORT-FOLLOWS-FILTERS  master_views.py, sheets.py  the download IS what is on screen
IMPORT-VALIDATE            masters/imports.py              reject exact, warn near
LAUNCHPAD                  projects/views.py               the home screen
INFO-PANELS                help_panels.py, _infopanel.html  the ⓘ panels, as data
                           panel_gujarati.py               the Gujarati FIRST DRAFT, to be corrected
                           seed_panel_translations.py      loading it without overwriting a person
HUB-TILES                  projects/hub.py                 tiles as DATA, filtered by permission
HUB-MASTERS                projects/hub.py                 what sits behind Master data
MASTER-TABS                projects/master_tabs.py         five entries, tabs, no Django Admin
ACTIVITY-MASTER            projects/master_tabs.py         the activity master, and its ₹/sqft
ACTIVITY-RENAME-BLOCKED    masters/models.py               a rename that would zero a budget
TASK-MODULE                bom_models.py, receipts.py      the only route to a received qty
PERMS-MATRIX               accounts/perms.py               who may do what — one dictionary
PERMS-ADD-A-ROLE           accounts/perms.py               how to add or change a role
USERS-SCREEN               accounts/views.py               adding people, resets, safeguards
BOOTSTRAP-ADMIN            accounts/models.py, middleware  the first Admin on a new database
USER-HISTORY               accounts/models.py              what happened to an account
SECURITY-NOTICE            projects/tests.py               the standing notes and the ⓘ panel
TASK-MODEL                 tasks/models.py                 milestones (header tasks), tasks, dates
TASK-BOARD                 tasks/views.py                  one project's plan, and adding to it
TASK-MINE                  tasks/views.py                  one person's rows, and who may tick
TASK-DELAYS                tasks/views.py                  what held the work up, counted
TASK-SCHEDULE              tasks/schedule.py               the Gantt, as arithmetic
TASK-WINDOW-WARNING        tasks/views.py                  work nowhere near its own milestone
TASK-DELETE                tasks/views.py                  the only thing here that destroys a record
BOQ-LIVE-KPIS              models.py, boq.html             cards that move as percentages are typed
ANALYTICS-WORK-FILTERS     analytics/views.py              milestone and activity, on that tab only
TASK-SCHEDULE-SCALE        tasks/schedule.py               fixed px per day, and the frozen names
BOQ-PDF                    views.py, boq_pdf.html          the estimate as a PDF, Quoted onwards
IMPORT-REPORT              masters/imports.py              created vs updated vs unchanged
NO-DJANGO-ADMIN            config/urls.py, middleware.py   Admin is not mounted, and must not return
MILESTONE-LINE             schedule.py, schedule.html      the window band, the dotted line, staggered labels
TASK-BASELINE              tasks/models.py                 the first promise, kept
TASK-RESCHEDULE            tasks/views.py                  editing, and moving dates in bulk
ANALYTICS-MONEY            analytics/money.py              committed vs received vs PAID
ANALYTICS-SETTLEMENT       analytics/money.py, views.py    paid, owed now, and coming
ANALYTICS-BUDGET           analytics/budget.py             quoted vs planned vs committed
ANALYTICS-G2N              analytics/views.py              the ladder, and every step's drill
ANALYTICS-WATERFALL        analytics/charts.py             bar geometry, tested as numbers
ANALYTICS-PERIOD           analytics/periods.py            April-March, PTD and CPD
ANALYTICS-CHARTS           analytics/charts.py             SVG by hand, no library
ANALYTICS-OVERVIEW         analytics/views.py              the six boxes, and why six
COMPLIANCE-MODEL           compliance/models.py            type → title → item → documents
COMPLIANCE-PRUNING         models.py, views.py             a line one project does not need
COMPLIANCE-STATUS          compliance/status.py            Missing/Held/Valid/Expiring/Expired
COMPLIANCE-SCREENS         compliance/views.py             who reads, who uploads, how files serve
COMPLIANCE-MASTER          compliance/views.py             the template, and the blast radius
DUMMY-GSTINS               seed_dummy_gstins.py            fake tax numbers, and how they stay fake
PO-LINE-SHARES             bom_models.py, views.py         document money split across the lines, exactly
HOME-SCREEN                projects/home.py, launchpad.html  the Dashboard: KPI cards, chart, ring, your work, activity, upcoming
BOM-COLUMNS                bom.html, base.html             ten columns by default, the rest behind one switch
PO-REGISTER-STEP           projects/views.py, po_register.html  one next step per register row, through po_advance
ANCHOR                     Lives in                        What it governs
SALES-MODEL                sales/models.py                 the chain Unit→Booking→Customer, derived statuses
SALES-ONE-BOOKING          sales/models.py, services.py    one live booking per unit, three ways
SALES-SCHEDULE             calc.py, models.py, services.py  percents total 100; header-linked demands
SALES-CALC                 sales/calc.py                   every sales figure, Decimal, one place
SALES-CALC-BULK            sales/calc.py                   list screens: two queries, not two per row
SALES-SERVICES             sales/services.py               every write to a booking, atomic, with a history row
SALES-SCREENS              sales/views.py                  who may read, edit, collect
ANCHOR                     Lives in                        What it governs
WO-TERMS                   bom_models.py, po_service.py,   the advance term on a WO; retention and DLP
                                                           kept as fields, SWITCHED OFF 11 Sep 2026
RA-BILL-OWNS-THE-WO        projects/po_service.py          a billed WO is completed and paid by finance
FIN-MODEL                  finance/models.py               bills store quantities and frozen rates, no money
FIN-CALC                   finance/calc.py                 the RA bill ladder, ONE copy, half-up per rung
FIN-CALC-BULK              finance/calc.py                 registers: fixed queries, not per row
FIN-CUMULATIVE             finance/services.py             certified to date may not exceed the order
FIN-SERVICES               finance/services.py             every finance write, atomic, user-facing refusals
FIN-SCREENS                finance/views.py                who may read, certify, approve, pay
DRAWINGS-MODEL               drawings/models.py              five tables; the number is the architect's
DRAWINGS-STATUS              drawings/status.py              Required/Received/Approved, from the newest revision
DRAWINGS-NO-DELETE           drawings/models.py              a drawing with history is deactivated, never deleted
DRAWINGS-APPROVE-ONCE        drawings/models.py              who and when, recorded once
DRAWINGS-LABEL-UNIQUE        drawings/views.py               R1 twice on one drawing is refused
DRAWINGS-TRANSMITTAL-ATOMIC  drawings/models.py              header and lines together; empty is refused before a number
DRAWINGS-SCREENS             drawings/views.py               who reads, who uploads, how files serve
```

---

## The register

### `BOM-CALC-GST-BASIS` — `projects/models.py`
**Every BOM figure is ex-GST. GST appears only on a purchase order.**

The BOQ adds GST once, at the very end, to the whole estimate. So a trade's
amount (`rate × BUA`) is a pre-GST number, and that same number becomes the
activity's budget reserve. Planned, used and variance must therefore also
exclude GST, or you are comparing a price against a price-plus-tax.

*This was got wrong once.* It reported RCC at 99.3% of budget when the true
figure was 84.2% — the difference between "at the ceiling" and "₹25 lakh spare".
Affects: the BOM screen, the Excel export, every KPI.

### `BOM-CALC-RESERVE` — `projects/models.py`, `EstimateLine`
An activity's reserve is `rate × BUA` from its estimate line, and it is a **live
link, not a copy**. Editing the estimate moves the reserve on any BOM already
generated. This is the single documented exception to copy-don't-link; BOM and
PO line prices still take frozen copies.
Affects: BOM KPIs, the warning shown when editing a saved BOQ.

### `BOQ-LIVE-KPIS` — `projects/models.py`, `templates/projects/boq.html`
**The KPI strip moves as the percentages are typed.** Until now the cards were
rendered server-side, and the contingency, design fee and GST inputs sit BELOW
them — so the change was both invisible and off-screen until Save was pressed.
Saahil: the inputs *"do not move the KPI cards"*.

**⚠⚠ THE ARITHMETIC STILL LIVES IN PYTHON, AND THIS IS THE ONE PLACE THE RULE IS
BENT.** What the browser does is a PREVIEW of three formulas, applied to a base
cost the server worked out. **It cannot save anything**: `boq_save` recomputes
every figure from the model, so the worst a wrong line of JavaScript can do is
show a number that corrects itself on Save. That property is the entire
justification — remove it and the script has to go.

**⚠ IF THE LADDER IN `models.py` CHANGES, THE SCRIPT CHANGES TOO.** Contingency,
then design fee, then GST on the lot. The duplication is deliberate, bounded and
marked at both ends; it is still duplication.

**⚠ `toLocaleString('en-IN')` DOES THE INDIAN GROUPING** and needs no network. No
static files, no CDN — that is unchanged. With JavaScript off the cards behave
exactly as before: right on load, right after Save.

**⚠ POINT 9 IS THE SAME ANCHOR.** The grey sub-text under three of these cards
restated the percentage typed in the box below it — *"5% of base"* under a field
containing 5 — which earns no space, and earns less now the two move together.
They carry the share of the **grand total** instead: an 8% contingency is 6.4% of
what the client is billed, because the percentages compound and GST sits on top
of all of it. That is the figure people argue about, and nobody had it.
`contingency_share`, `design_fee_share` and `gst_share` are properties on
`Estimate` — **against the grand total, never the base**, or they would just be
the typed numbers again.

### `CODE-GEN` — `projects/models.py`, `Activity.abbreviation`
A material's code is `ACTIVITY-GROUP-SERIAL`, e.g. `PLM-PL3-014`. The first
segment is this abbreviation.

**A code is assigned once and never regenerated.** Reclassify a material and it
keeps its original code, so an old code may name an abbreviation that has since
changed. That is deliberate — a code printed on a purchase order must never stop
resolving. **Nothing parses a code to work out its activity**; that is what the
foreign key is for.
Affects: material creation, the Excel import, anything displaying a code.

### `BOM-MATERIAL-FILTER` — `projects/models.py`, `MaterialActivity`
**This table, never the code, decides which materials a BOM dropdown offers.**
A material has one *home* activity (the one in its code) but can be linked to
many. Cement is used in RCC, Masonry and Plaster.
Filtering, never restricting — the dropdown shows this activity's materials
first, with a switch to search everything.
Affects: the material search, the add-material dropdown.

---

### `BOM-CALC-TO-ORDER` — `projects/bom_calc.py`
**⚠ NOTHING IS ORDERED UNLESS SOMEBODY TYPED IT.** `order_qty` is the typed
quantity, or zero. Blank orders nothing.

*This superseded the original rule on 9 Aug 2026*, where blank meant "use the
suggestion". Saahil's call, and the reason is the scale: sixteen activities of
three to four hundred materials means that button would have ordered the entire
project in one press.

`suggested_order_qty` is still `max(0, planned − approved − in draft − stock)`
and still shows on every row as "still to buy". It is advice now, not an
instruction — which is the correct relationship between a computer and a
purchase order.
Drafts are subtracted deliberately: without that, a quantity already sitting on
an unapproved order still looks un-ordered and gets ordered twice.
Affects: the BOM screen, the Excel export, PO generation.
*Known gap:* stock is per material per site but is subtracted on every line, so
a material under two activities under-orders. Undecided.

### `BOM-CALC-BULK` — `projects/bom_calc.py`
**The number of database questions must not grow with the number of rows.**
A real project is sixteen activities of three to four hundred materials — about
6,400 lines. Asking three questions per line meant 618 queries to draw one
screen and over 8,000, nine seconds, to press Post POs.

`bulk_quantities()` fetches approved / in-draft / received for MANY lines in
three queries; `figures_for()` is what everything should call instead of looping
over `line_figures`. **Not a second copy of anything** — the totals are still
summed from the purchase orders every time, handed around inside one calculation
and thrown away. No formula changed.

Guarded by tests that measure the SHAPE of the work: 40 extra rows must add
fewer than 10 queries, and the bulk figures must equal the per-line ones exactly.
Affects: the BOM screen, PO generation, the discontinued check, the Excel export.
`bulk_vendor_rates()` was added under the same rule — see below.

### `VENDOR-RATE-CAPTURE` — `projects/po_service.py`, `projects/bom_calc.py`, `masters/models.py`

**What a vendor last actually charged for a material, written down when an order
is approved and offered back the next time somebody buys it.**

**⚠⚠ THE MODEL DESCRIBED THIS FROM THE BEGINNING AND NOTHING IMPLEMENTED IT.**
`VendorRate`'s docstring said a rate is "written back here on approval" for
months. It never was. The table sat empty on a live database holding approved,
delivered and paid orders, while the screen said rates "appear as purchase orders
are raised" — a promise the code did not keep. Saahil found it by opening the
screen: *"There were a few approved POs, yet I saw this as empty."* **A docstring
is not a feature, and this is the one to remember that by.**

**⚠ THE RATE CAPTURED IS NET OF THE LINE DISCOUNT** — `taxable ÷ quantity`, not
the typed `rate`. "₹340 with 5% off" and "₹323 flat" are the same purchase and
must compare as the same number.

**⚠ ONE ROW PER VENDOR AND MATERIAL, REPLACED EACH TIME.** His call, and he named
the precedent: *"we should do like SAP, if the vendor/material combination exist,
we replace it."* So this answers *what is the rate with this vendor today*, never
*what has it been*. Nothing is lost — the trail is on the purchase order lines,
which is the honest source for any question about history. **A consequence worth
knowing: the vendor-rate scatter cannot be drawn from this table over time.**

**⚠ `source_po_line` IS WHAT MAKES THE REPLACE LEGIBLE.** Without it a replaced
rate is a figure that changed on its own. `SET_NULL`, so losing the order does
not delete the rate.

**⚠⚠ THE FALLBACK LADDER MOVED, AND THAT IS THE PART THAT CHANGES MONEY.**
`effective_vendor_rate` was *typed → planning rate* and is now
**typed → captured → planning rate**. A line naming a vendor with no typed rate
used to be compared against the planning rate and therefore always reported
**0.0% variance — the plan measured against itself**, which is what Saahil was
looking at on a screen full of zeroes.

**⚠ WHY THE ARITHMETIC MOVED AND NOT JUST THE PLACEHOLDER.** The grey number in
the Vend Rate cell is not a hint: it states what a BLANK cell will actually use.
A grey ₹340 over a cell that computes with ₹20 is a screen contradicting its own
numbers — **bug 24's shape**, in a cell that drives PO value. Either both move or
neither does. He chose both, knowing it moves `po_value` and `Var %` on every
line with a vendor and a blank rate.

**⚠ THE BENCHMARK IS STILL THE PLANNING RATE.** Only the actual side changed.
`Var %` still answers "did I buy at the rate I planned for this job?"

**⚠ NOTHING ON THE BOM SAYS SO IN WORDS.** Saahil: *"I dont wish to add extra
text on the BOM Line, we can keep it as grey text as we do for other key
fields."* The provenance is on the Vendor rates screen and in a hover, nowhere
else.

**⚠ `bulk_vendor_rates()` EXISTS BECAUSE OF `BOM-CALC-BULK`.** The fallback is
consulted for every row; a lookup inside it would be a query per row. One
grouped query for the screen, handed down as `captured`, and a test pins the
count at 1 for three lines and for thirty.

**⚠ `_UNSET` IS NOT `None`.** None means "looked, and this vendor has never been
paid for this material". `_UNSET` means "nobody has looked yet". Collapsing them
would make every bulk caller silently skip the new step.

**⚠ APPROVAL ONLY — never a draft**, which may never be sent. Work orders capture
too. `backfill_vendor_rates` reads existing approved-and-later orders **oldest
first**, so the newest wins.

### `PO-PREVIEW` — `projects/po_service.py`, `preview_purchase_orders()`
**Post POs creates nothing.** It saves what was typed, then shows every order
that WOULD be raised — vendor by vendor, with quantities, GST and totals — and
writes not one row. You tick the vendors you want and confirm.

This is SAP's Check button. Saahil asked for it once the real size was clear:
sixteen activities of three to four hundred materials, where a button that
silently creates a dozen documents is not a button anyone should trust.

Lines with a quantity but **no vendor raise nothing** — a blank vendor means
nobody has chosen a supplier yet, and the system never picks one. They are
listed on the preview so they cannot go unnoticed.
Affects: the Post POs button, `generate_purchase_orders(vendor_ids=…)`.

### `PO-INVARIANT` — `projects/bom_calc.py`
**The BOM stores no copy of approved, in-draft or received.** Each is summed
from the purchase orders, so the two can never disagree. Delete a draft and the
quantity is simply no longer there to add up — nothing has to remember to give
it back. This removed a whole category of bug rather than guarding against it.

### `IMPORT-VALIDATE` — `masters/imports.py`
Exact duplicates rejected, near-duplicates only warned. The second half matters:
`MTA`/`FTA`, `UPVC`/`CPVC`/`PVC`, `RE TEE`/`TEE` are genuinely different parts,
and an earlier pass over this data produced eighteen confident, wrong merges.
The same `normalise()` must be used for search, or duplicates appear that the
search box cannot find.

### `GSTIN-CAPTURE` — `projects/po_service.py`, `masters/models.py`
Approval hard-blocks without a GSTIN and writes it back to the **vendor master**
— captured once, never asked again. It also writes `state`, derived from the
first two digits, which decides CGST+SGST versus IGST on the PO. None of the 173
vendors has a GSTIN, so this fires on the first PO to every single vendor.

**Exception: `Vendor.is_unregistered`.** The hardware shop down the road has no
GST number and never will. Tick it and approval stops asking, and their PO lines
are raised at 0% GST — an unregistered supplier cannot charge it. `VEN-LOCAL`
("LOCAL PURCHASE") ships with the system for cash and street buys, so that spend
reaches the budget instead of staying off the books.

### `TASK-MODULE` — `projects/receipts.py`
`record_receipt()` is the ONLY way a received quantity ever changes. Today the
manual "mark delivered" calls it; later the task management module calls the
same function. Nothing may write `Receipt` rows by another route.

---

## Who may do what

### `PERMS-MATRIX` — `accounts/perms.py`
**One dictionary decides every permission in the system.** Permission key → the
roles that hold it, transcribed from the table agreed with the customer screen by
screen. Views carry `@requires("po.approve")`; templates ask `{{ user|can:… }}`;
the launchpad and the Master data page filter themselves from the same lines, so
**a tile can never lead to a screen that refuses you**.

**It costs nothing at runtime.** The dictionary is built once when the process
starts, a check is a dict lookup and a set test, and the role arrives on the
profile already joined onto the user — **zero extra queries on any screen**.
There is one copy of every screen, shared by all six roles.

**⚠ A permission is only real if the role can reach the screen the button is
on.** Four rules were caught that way while the matrix was being agreed: an
Accountant ticked for "post purchase orders" who could not open the BOM the
button lives on; a Site engineer ticked for "mark delivered" who could not open a
purchase order.

**⚠ Approve, Delivered and Paid are THREE permissions**, mapped once in
`TRANSITION_PERMS` (`projects/views.py`) and read by both the document screen and
the register's bulk box — so the bulk box can only offer what that role could do
one document at a time.
Affects: every view, the launchpad, Master data, the PO buttons, the bulk box.

### `PERMS-ADD-A-ROLE` — `accounts/perms.py`
**Adding a role is three files and about fifteen minutes**: one line in `Role`,
the roles it holds in `MATRIX`, and the same rows in `accounts/test_matrix.py`,
which then proves it reaches what was agreed and nothing else. Changing what an
existing role may do is one word in each of two files.

The two-places rule is deliberate: `perms.py` is the implementation and
`test_matrix.py` is the specification, so a behaviour change has to be made twice
by somebody who noticed they were doing it.

**Letting the admin invent roles from a screen** — a Role table, a permission
tick-grid and a seeded migration — is roughly a day and was offered and turned
down. This file can be read against the agreed table in one sitting; a mis-ticked
box on a screen is silent where a code change is reviewed.

### `USERS-SCREEN` — `accounts/views.py`
Under Master data, beside Materials and Vendors. Add a person, set a role, reset
a password, deactivate. **Four safeguards, none of them recoverable from inside
the app if they were missing:** no deactivating yourself · no changing your own
role **unless you have no role at all** (see `BOOTSTRAP-ADMIN`) · **the last
active Admin cannot be demoted or switched off** · **no delete, ever**. A reset
shows a password that can be read down a phone (`accounts/passwords.py`)
**once**, and forces a change at the next sign-in.

### `BOOTSTRAP-ADMIN` — `accounts/models.py`, `accounts/middleware.py`
**The first Admin on a brand-new database, and nobody after that.**
`createsuperuser` makes a `User` and no `UserProfile`, the matrix reads
`UserProfile.role`, and there is no Django Admin to repair it from — so a fresh
installation opened on a launchpad where every tile refused you. Hit for real on
16 Aug 2026 during the PostgreSQL rehearsal.

**⚠⚠ THE CONDITION IS "THIS SYSTEM HAS NO ACTIVE ADMIN", NOT "THIS USER IS A
SUPERUSER"** — and that distinction is the whole design. Granting Admin to every
superuser was the easier rule and it would have reversed `PERMS-MATRIX`, which
says deliberately that `is_superuser` must not satisfy a business rule. Superuser
is granted by whoever administers the server; Admin is a business role. **The
door closes behind itself:** once one active Admin exists this never fires again.

Same predicate as the last-Admin safeguard (`role=ADMIN, user__is_active=True`)
so the two rules cannot disagree. **Recorded in `UserEvent` with `by=None`**, and
announced on screen — a privilege that appears with nothing behind it is
indistinguishable from one somebody granted themselves.

### `USER-HISTORY` — `accounts/models.py`, `UserEvent`
Created · role changed · user ID changed · password reset · deactivated ·
reactivated, each with who and when. **The event, never the secret** — passwords
are one-way hashes and cannot be shown to anybody, including an admin. What
changed is computed *before* the write, or the old values are already gone.

---

## Site work

### `TASK-MODEL` — `tasks/models.py`
**Two levels and no more.** A header task is a package of work with an owner —
Earthing; the subtasks under it are what one person does. Three levels is a
project plan and nobody maintains a project plan.

**⚠⚠ A MILESTONE *IS* A HEADER TASK. The separate `Milestone` model is deleted**
(migration `tasks/0003`). The two were one concept built twice, and the copy that
went carried a date somebody TYPED beside a header whose finish is COMPUTED from
the work under it — the only place in this module where a date was declared
rather than captured, and the two could disagree with nothing to find out.
**On screen a header task reads "Milestone" and a subtask reads "Task".** Model
names, field names, URL names and CSS classes are deliberately unchanged: a
rename that reaches the database is a migration and a merge conflict for a word
nobody outside the screens ever sees. So `TaskHeader` in the code is "Milestone"
to the customer, and that mapping is the one thing to hold in your head here.

**Tasks are descriptions, not materials.** Nothing here points at a BOM line, a
material or a purchase order. Quantities and money stay where they already are.

**Every header names an activity, BY ID.** The BOQ reserve matches activities by
NAME and that is a known landmine; this is the same relationship done properly,
so renaming an activity cannot orphan anything.

**Dates are a start and a duration in days. The finish is computed, never
typed** — and it is inclusive of day one, so three days from Monday finishes
Wednesday. Both levels carry both: the header's is the commitment made before
the detail existed, the subtasks' is the working plan, and the gap between them
is an early warning that arrives *before* anything is late.
⚠ This reversed an earlier decision that a parent's dates derive from its
children. It is the later decision and it stands.

**Planned dates are never rewritten when something slips.** What happened is
recorded beside what was planned. `days_late` is arithmetic; the *reason* is
typed by the person, from a fixed list — free text says more about one delay,
a list can be counted across a year.

### `TASK-BOARD` — `tasks/views.py`, `templates/tasks/board.html`
**One project at a time, and the picker is the first control on the screen.**
Won and Completed projects only. A subtask's header is looked up *within the
chosen project* — `get_object_or_404(TaskHeader, pk=…)` would accept a header
belonging to another site, which is exactly what the prototype did and what
Saahil caught by reading the dropdown.

**Every add button is at the top.** "If the list is long, how much will the user
scroll."

**Reading is `tasks.view` and everybody holds it; changing is `tasks.manage` and
an Admin or a Project manager holds it.** `tasks.mine` is the third — ticking
your own row — and *whose* row it is, is checked in the view, never in the
matrix.

**The notification seam is marked and deliberately empty** in `subtask_new()`:
one call to `notify(person, event)`, in-app first and WhatsApp behind the same
seam once the Meta business account exists.

### `TASK-MINE` — `tasks/views.py`, `templates/tasks/my_work.html`
**The tick belongs to the person the work is assigned to, and to nobody else** —
*"the engineer's tick is final"*. `tasks.manage` does **not** open this door; an
Admin holding every key in the matrix is still refused, because the matrix
answers *may this role tick at all* and cannot answer *whose row is this*. That
second check is `_theirs()`, in the view.

**The finish date is today, captured, never typed.** Letting somebody type when
they finished is letting them decide whether they were late.

**A late tick cannot be saved without a reason; an on-time one is never asked
for one.** A log full of "no reason given" answers nothing, and a form that asks
anyway teaches people to pick the first option in the list.

**Blocking does not move the date.** It stays where it was and keeps counting
overdue, because that is the truth: the work has not happened.

**Reopen is the only way a tick comes back, and it is `tasks.manage`.** Nobody
overrules the engineer's tick and nobody quietly takes it back either —
correcting a record is a different act from making one.

### `TASK-DELAYS` — `tasks/views.py`, `templates/tasks/delay_log.html`
**A repository of its own, not marks on the chart** — *"the delay messages
should not be visible on the chart, it should have a different log repository"*.
The bar carries the difference; the words live here.

**It is a counting screen before it is a reading screen.** The summary — days
lost per reason, worst first — is the answer to *which of these actually holds
our sites up*, and it is the whole reason the reason is a fixed list.

**"Late" is finished-after-its-date, and SQL cannot express it** — the planned
end is `start + days`, computed in Python. Candidates are narrowed in the query
(anything finished at all) and the arithmetic runs once per row through the same
property the screens use. One truth, not two.

⚠ **Manager-only, and that is the reversible answer** to an open design
question. Nobody is kept from their own record: their late rows are on My work.

### `TASK-BASELINE` / `TASK-RESCHEDULE` — `tasks/models.py`, `tasks/views.py`
**Moving a date is a different act from missing one, and both are recorded.**
Saahil's decision when editing was added: *"keep the first promise"*. The first
`start`/`days` are copied into `original_start`/`original_days` **the first time
the dates move and never again** — a plan pushed out three times is three days
of drift each time and one promise.

**The team works to the new date; lateness is still readable against the old
one.** `promised_end` is the first finish, `days_shifted` is how far past it the
plan now sits. Rescheduling therefore cannot make a late job look on time, which
is the only way an editable plan stays honest.

**The manager gives the reason, not the engineer** — the person who moved the
plan is the one who knows why. **Only an outward move is asked for one**;
pulling work forward is not a delay and `capture_promise()` returns zero.

**Replanned days are counted in the delay log beside late ones.** A job replanned
twice and delivered on the new date is not late by any test, and still arrived a
fortnight after it was promised. Counting only lateness reports that as zero.

⚠ **`scope` — "Scope or design changed" — is a SEVENTH reason added to the six
agreed with the customer.** Without a word for it people pick "Decision needed"
and the count stops meaning anything. One line in `DelayReason` to remove.

**Bulk shift and bulk reassign are the agreed substitute for dependencies.** A
dependency graph is the feature everybody asks for and nobody maintains; ticking
rows and moving them together does the same job with a person deciding.

### `TASK-DELETE` — `tasks/views.py`, `templates/tasks/board.html`
**⚠⚠ THE ONLY THING IN THIS MODULE THAT DESTROYS A RECORD.** Everything else here
keeps what happened beside what was planned — a tick is captured, a reopen is
visible, a moved date keeps its first promise. Deletion keeps nothing, and Saahil
chose that knowingly: option B, *"Admin and project manager may delete ANY task,
history included; it is their judgement."*

**⚠ WHY NOT DEACTIVATE, WHICH IS THE RULE EVERYWHERE ELSE.** A vendor or a
material is referenced by documents that must stay readable years later, so
deactivating is the only honest answer there. **A task references nothing** — no
money, no document, no material. A typo'd row is noise on a board somebody reads
every morning, and noise nobody can remove is how a board stops being read. Same
rule, different situation.

**⚠ `tasks.manage`, AND NOT `tasks.mine`.** Those two keys answer opposite
questions: may this person record what happened to their own work, versus may
this person say it never happened. The site engineer holds the first and is
refused here **even on a task assigned to them**.

**⚠ ANY TASK, INCLUDING A FINISHED ONE.** He was asked and said any: a completed
row filed against the wrong milestone is exactly the one somebody needs to remove.

**⚠ THE DELAY LOG LOSES ITS ROW WITH IT.** Days lost per reason is counted from
the subtasks themselves — there is no separate log table — so deleting a late
task takes its days out of the count. **The confirmation says so**, rather than
leaving it to be discovered when a number moves.

**⚠ A MILESTONE HOLDING TASKS IS REFUSED, WITH THE COUNT.** No cascade: deleting
a fortnight of somebody's work from a button labelled with a phase name is not a
decision anybody made. Empty it first, one row at a time. The button is not drawn
in that case either, but the server refuses regardless.

**The chart re-fits by itself** — the span is derived from what is left, not
cached. Tested rather than assumed, because a cached span is exactly what would
get this wrong.

### `TASK-WINDOW-WARNING` — `tasks/views.py`
**⚠⚠ IT WARNS AND SAVES. IT MUST NEVER REFUSE.** A milestone whose work has grown
past the window it was given is a REAL state — it is the whole point of the amber
bar, and it arrives before anything is late. A hard block would outlaw it. What
cannot be a plan is work that never touches its milestone's window at all: that
is a typo, not a schedule.

**The test is NO OVERLAP AT ALL, deliberately narrow.** Starting early, finishing
late, or both, all overlap — and the chart already colours them. A rule any
broader fires on the ordinary way of working, and **a screen that warns about
everything warns about nothing** (his yellow-box rule, applied to messages).

**⚠ IT RUNS FROM BOTH ENDS, and the second one is the one that matters.** Saahil's
mistyped year was on the MILESTONE — `Site Work`, 14 August 2025 — whose only task
started 15 August 2026. A check that only ran when a task was saved would have
said nothing at all. `_warn_if_the_window_left_its_work` fires when a header's
dates move away from **every** task under it. One task outside is an overrun; all
of them outside means the window is in the wrong place.

**⚠ IT SAYS HOW MANY DAYS**, because "360 days after it finishes" is what makes a
wrong year obvious. "Outside its window" would not.

The system had in fact noticed his row — it was amber. But amber says *the plan no
longer fits*, which is not the same sentence as *check the year*, and the chart
obediently drew thirteen months to hold three weeks of work.

### `TASK-SCHEDULE` — `tasks/schedule.py`
**All of the Gantt's geometry is here and none of it is in the template.** The
same rule that put every BOM figure in `bom_calc.py`: a percentage worked out
inside a `<div>` cannot be tested and gets copied. The template receives `left`
and `width` as strings and draws them.

**The scale is derived from the data**, padded out to whole months at both ends
so the labels line up with the bars. A fixed twelve-month window is empty on a
three-week job and useless on a two-year one.

**⚠ TWO OVERRUNS, DRAWN DIFFERENTLY, AND THEY MUST NOT BE MERGED.** Red on a
subtask = LATE (finished after its date, or open and today has passed). Amber on
a header = its subtasks no longer fit the window that was committed to — nothing
has slipped yet. Reading them as one number is how a project convinces itself it
is on time until the week it is not.

**The bar carries the difference and no words.** Why anything ran over is the
delay log's job.

**Every measurement is formatted as a string.** A float goes through locale
formatting, and a decimal comma inside `left:12,5px` draws every bar at zero.
**A minimum width is CSS (`min-width:3px`), never a floor in the arithmetic** —
inflating one bar moves every bar after it, and on a chart that scrolls the
error accumulates the whole way along the row.

### `TASK-SCHEDULE-SCALE` — `tasks/schedule.py`, `templates/tasks/schedule.html`
**⚠⚠ FIXED PIXELS PER DAY, NOT A PERCENTAGE OF THE SPAN.** `PX_PER_DAY = 3.2`.
Saahil, looking at a real project: *"normally a project goes on for two years,
but when I saw the Gantt chart it was very confusing — the data is compressed at
the end."* He was describing the arithmetic. Every bar was a percentage of the
whole span, so a two-year job squeezed twenty-four months into the page width, at
about 37px a month. A month is now the same width whether the job runs three
weeks or three years, and **the chart scrolls sideways instead of shrinking**.

**The names column is frozen and does not scroll with it.** A chart you can
scroll but whose rows you can no longer identify is not an improvement.

**`MIN_MONTH_PX = 88` is the second half of the same decision** — a month at this
scale is roughly 97px, which fits "Apr 2026" without crowding. The two are named
so they are changed together and stay in step.

**`_pct()` survives for the today marker and nothing else.** How far along the
whole span today is really is a proportion; a bar's position is not.

### `IMPORT-REPORT` — `masters/imports.py`
**An import reports three things separately: created, updated, unchanged.** `ImportReport` had
no `updated` bucket, so `read_materials` and `read_vendors` filed updates under `created` with a
detail string reading *"updated: rate"*. The per-row line was honest and **the summary above it
contradicted it** — a round trip that edited one vendor announced *"1 created, 0 skipped"*.

**⚠⚠ IT MATTERS MOST ON THE DAY IT MATTERS MOST.** Seeding the live server imports 705 materials
and 174 vendors. *"705 created"* on a run that actually updated 705 existing rows is the
difference between "it worked" and "I have just overwritten the master".

**⚠ `touched` IS FOR THE SCREENS** — created then updated, in the order somebody reads them —
so a caller listing what changed does not have to concatenate two lists and get the order wrong.

**⚠ "skipped" IS NOW PRINTED AS "unchanged"**, because that is what it means: the row is in the
sheet and the database already agrees with it. On a re-run that is the expected answer, not a
problem, and the wording said otherwise.

**⚠ ONE OLD TEST WAS ASSERTING THE BUG** — `TheExcelRoundTrip` checked `len(report.created) == 1`
after editing an existing material. It now asserts 0 created and 1 updated.

**⚠ KNOWN, NOT FIXED: a blank WhatsApp column reports a phantom change.** The importer sets the
field to `""` and `Vendor.save()` immediately re-derives it from the phone, so `changed` sees a
difference that does not survive the save. A downloaded sheet always carries the derived number,
so the normal round trip never hits it; a blank template does.

### `NO-DJANGO-ADMIN` — `config/urls.py`, `accounts/middleware.py`
**Django Admin is not mounted. `/admin/` is a 404, and it must stay that way.** Saahil, after
seeing a raw Django screen during a walkthrough: *"I don't want the admin or any other user to
ever access the Django screens. Everything has to be interfaced with the UI that we have
decided."*

**⚠⚠ THE REASON IS NOT TIDINESS.** Admin walks past every rule this application exists to
enforce — the activity rename that would silently zero a budget, the BOQ that locks at Won, the
delete refused while something references it, the permission matrix, the vendor rate that may
only be captured from an approved order. A screen that edits any table directly makes all of
those advisory.

**⚠ NOTHING WAS LOST, AND THAT WAS CHECKED RATHER THAN ASSUMED.** Every model registered in an
`admin.py` has its own screen. The old `urls.py` comment claiming Admin was *"still the only
place some master tables are edited"* was true once and stopped being true when the master data
screens were built; the last gap closed when Material groups got its name field back (B2).

**⚠ TWO LINKS POINTED AT IT AND BOTH ARE GONE** — the header item for a superuser, and an
"Open in Admin" link on the empty-BOM screen telling people to build their estimate there. That
one now points at the BOQ screen, which is where an estimate was always meant to be built.

**⚠⚠ THE MIDDLEWARE EXEMPTION WENT WITH IT, AND IT WAS QUIETLY A HOLE.** The
must-change-password guard skipped anything under `/admin/`, so somebody who had not yet chosen
their own password — whose password is by definition known to whoever set the account up —
could reach every table in the database through it.

**⚠ THE REAL EMERGENCY EXIT IS `manage.py shell` ON THE SERVER**, which needs server access
rather than a browser and a superuser flag. That is the right shape for break-glass.

**⚠ FOUR TESTS USED TO DRIVE ADMIN'S ESTIMATE FORM** to prove the reserve warning. They were
rewritten against `boq_save` — strictly better, because the warning is now proven on the path
people actually use. `accounts/test_no_django_admin.py` is the guard against re-adding the URL,
which would be a one-line change that looks harmless in a diff.

### `BOQ-PDF` — `projects/views.py`, `templates/projects/boq_pdf.html`
**The estimate as a PDF, for sending to a client or a portal.** Saahil's requirement, in his
words: *"once they quote it, they download it, and then they upload it onto a portal."*

**⚠⚠ QUOTED ONWARDS ONLY, AND THAT IS THE POINT.** A Draft is refused with a reason and the
button is not drawn at all — the same rule, and the same reasoning, as the purchase order PDF.
A draft estimate is a number still being argued about; on paper, in somebody else's inbox, it
is indistinguishable from an offer, and nothing in the document would say otherwise.
The hidden button is the courtesy; the refusal in the view is the rule.

**⚠ NOT ONE FIGURE IS WORKED OUT IN THE VIEW OR THE TEMPLATE.** Rows come from
`bom_calc.boq_rows`, totals are properties on `Estimate` — the same ones the screen reads. That
is the whole reason this was safe to add: there is no second implementation of the arithmetic
to drift. A test asserts every rung of the ladder appears on the rendered page.

**⚠ THE PRINT CONVENTIONS ARE COPIED FROM `po_pdf.html` AND ARE NOT PREFERENCES** — tables not
flexbox (WeasyPrint's CSS support varies by version), no `₹` glyph (missing from many server
fonts, prints as a hollow box; "Rs" is written out), and the footer as a running element so it
never pushes content onto a second page.

**⚠ WEASYPRINT IS IMPORTED INSIDE THE VIEW** and CI does not install it, so the tests inject a
fake module into `sys.modules` rather than patching a library that cannot be imported.

### `MILESTONE-LINE` — `tasks/schedule.py`, `templates/tasks/schedule.html`
**A milestone draws BOTH a band on its own row and a vertical dotted line through
every row beneath it — two different facts, not one drawn twice.** The band is
`header.start` → `header.planned_end`, what was actually typed, present the
moment a milestone exists, whether or not it has subtasks yet. The line is the
phase's JUDGED finish, which only moves once work under it proves the window
wrong. Amber marks the band's own overrun tail and the line together.

**⚠⚠ THE BAND WAS REMOVED ONCE, THEN BROUGHT BACK.** It was dropped when
milestones first moved to a dotted line, but the CSS (`.gbar.hdr`, `.gbar.hdrover`)
and the legend describing it were left behind — so the screen kept promising a
band it never drew. Nobody noticed on a two-year job where every milestone had
subtasks under it soon enough. Saahil found it on an ordinary sixteen-month
project with two milestones and nothing under them yet: the row showed nothing
at all. Restored on request — "the months... filled properly as per the user's
input" — reusing the CSS and legend that were already there.

**⚠⚠ THE DATE IS THE PHASE'S FINISH, AND IT IS COMPUTED, NEVER TYPED.** It is the
LATER of the promise and the work actually done — `max(planned_end, work_end)` —
so when a task slips past the date, the line moves with it. That is the rule the
rest of the module already follows, and it is why the `Milestone` model had to go.

**⚠ LABELS STAGGER; LINES NEVER MOVE.** A label that would collide with the one
before it drops to the next of `LABEL_LANES = 3`. Moving a *line* to make a label
fit would be drawing a lie. The lane is chosen against the last label placed in
each lane, not against the previous line — otherwise three phases inside a
fortnight all land in lane 1 the moment the second one leaves lane 0.

**⚠⚠ `LABEL_CLEARANCE = 90.0` IS IN PIXELS BECAUSE THE GEOMETRY IS IN PIXELS.**
It was a percentage of the span while the chart scaled to the page, and switching
to fixed pixels per day made `6.0` mean six PIXELS — about two days — so nothing
staggered again. The chart still rendered perfectly and the labels sat on top of
each other. **A unit change is not a cosmetic change.** If you retune the scale,
retune this with it.

**The labels are now TAGS in ONE strip along the top edge**, not three stacked
"MILESTONES" rows. A tag hangs off its line at `left`, sits `tag_top` down the
strip (`lane × TAG_LANE_PX`), and is clipped to `TAG_MAX_PX`, which is narrower
than `LABEL_CLEARANCE` — so two tags in one lane can never touch. The strip is
`tag_strip_px` deep, one lane per lane in use. The "Today" tag lives in the same
strip on a solid navy line. **The milestone's name is also printed inside its
band**, white on navy, clipped with an ellipsis; the tag is there for the line,
which runs down every row and would otherwise be unnamed. All of it is
arithmetic in `schedule.py` and tested there; the template reads strings.

---

## Analytics

### `ANALYTICS-MONEY` — `analytics/money.py`
**⚠⚠ "SPEND" MEANS MONEY PAID. NOTHING ELSE MAY BE CALLED SPEND.** Three stages,
three dates, three numbers people confuse daily:

| stage | counts on | figure |
|---|---|---|
| committed | `approved_at` | ex-GST `taxable` |
| received | `delivered_at` | — |
| paid | `paid_at` | `net_payable`, after TDS |

**A paid document is still committed.** Otherwise a month's commitments would
shrink as invoices were settled. **A draft is counted nowhere.**

**Document money comes from `PurchaseOrder.totals()`, never re-derived** — that
is the method the printed PDF uses, and the document wins every argument.
**Summed in Python over prefetched lines**, because percentage arithmetic in SQL
is not portable: SQLite integer-divides 10/100 to zero and PostgreSQL does not,
so money computed in the database would differ between laptop and server.

**Payables count from DELIVERY, not approval.** Approving commits the money;
taking delivery is what makes it owed.

⚠ **`Vendor.payment_terms` is free text.** A number in it is the credit period;
anything without one gets **no invented due date** and is left out of the ageing
buckets, with the count shown on screen. An assumed thirty days puts a real
invoice in the wrong bucket and somebody gets paid late.

### `ANALYTICS-SETTLEMENT` — `analytics/money.py`, `analytics/views.py`
**How much has been paid, and how much is still to pay** — Saahil's request, in
the words of the people who read the books.

```
  settled           paid
+ payable_now       delivered, not paid — the bill on the desk
+ not_yet_payable   approved, not delivered — coming, not owed
= obligation        everything approved onward
```

**⚠ ALL FOUR ARE `net_payable`, AND A TEST ASSERTS THEY ADD UP.** Committed is
normally quoted ex-GST and paid net of TDS — both right, and putting those two
side by side under one heading produces a gap that is pure arithmetic and looks
like missing money. **What vendors invoice (`order_value`) is shown too, with
the TDS between them named**, or the page invites "why does this not match the
ledger".

**It ignores the month filter on purpose.** What is owed is a question about
today; a period filter hides the oldest debts.

**Ageing runs from the due date**, and a vendor whose terms cannot be read gets
its own bucket rather than an invented date.

**`by_activity()` is ex-GST and cannot honestly be anything else** — a
document's deduction, round-off and TDS belong to the document, not to a trade,
so there is no non-arbitrary split. The screen says so.

### `ANALYTICS-BUDGET` — `analytics/budget.py`
**Three columns, because there are two gaps and two different people.**
`BUDGET` (BOQ rate × area, what was quoted) · `PLAN` (BOM quantities × rate,
what we intend to buy) · `ACTUAL` (committed → received). Budget minus plan is an
**estimating** gap; plan minus committed is a **buying** gap. One "variance"
column would hide which of the two happened.

**⚠ THE WORD ON SCREEN IS "BUDGET". `reserve` stays in the code and on the BOM
screen**, where the site team has used it since July. Saahil's call: one number,
two audiences, and the label follows the reader.

**Rows are projects until a project is chosen, then they are trades.** The filter
is the drill-down; a separate detail page would be the same table twice.

**Everything is ex-GST** and money paid is deliberately absent — it is on
Payments. **Figures come from `bom_calc.figures_for`, in bulk, one project at a
time**: the cost is per project and not per trade, and a test asserts it.

**A trade quoted and not yet planned still appears**, or the total would not add
up.

### `ANALYTICS-G2N` / `ANALYTICS-WATERFALL` — `analytics/views.py`, `charts.py`
**The ladder was in the model and on every printed PDF and on no screen.** Now a
waterfall and the same table in printed order, side by side, for a chosen stage.

`G2N_STEPS` is **one list read by the chart, the table and the drill links**, so
a step cannot exist in one and not the others.

**⚠ THE TWO STEPS THAT GET MISREAD, LABELLED IN WORDS ON SCREEN:** `deduction` is
**post-tax and is not a discount** — the GST above sits on the undiscounted
taxable value, so the vendor's own invoice shows a different taxable figure.
`tds` is withheld **from the payment**, computed on the **taxable** value, never
on GST, and does not reduce what the vendor bills.

**The waterfall geometry is tested as arithmetic** (`waterfall_steps`) and the
SVG only draws the numbers. A chart one step out looks entirely plausible.
**A `total` row restates the running balance and is never added to it** — the
classic way to get a waterfall wrong.

**Every step drills to `/analytics/documents/`**, which exists for that reason: a
figure nobody can open is a figure nobody trusts, and its footer adds up the rows
on screen so a mismatch is visible.

### `ANALYTICS-PERIOD` — `analytics/periods.py`
**April to March, everywhere**, because every figure is eventually read beside
something their CA produced. **PTD** = 1 April to today; **CPD** = one month.
No free date range on purpose — two people comparing "the last quarter" pick
different quarters and neither notices. Only months that have begun are offered.

### `ANALYTICS-CHARTS` — `analytics/charts.py`
**Hand-drawn SVG, no chart library.** The app has no static files and the
client's server may never reach a CDN; a chart that works on a laptop and shows
an empty box in the site office is worse than a table. **Bar scales always start
at zero.** Labels are escaped — one vendor called "Shah & Co" is enough to blank
an entire SVG.

### `ANALYTICS-OVERVIEW` — `analytics/views.py`
**The Admin, and nobody else** — the one permission in the matrix held by a
single role. **No single headline number**: committed, owed and paid are three
questions, and a business reading one of them is guessing at the other two.
**Reserve is compared with an ex-GST figure**, because the BOQ adds GST once at
the very end; mixing them once reported an activity at 99.3% of budget when the
truth was 84.2%.

### `ANALYTICS-WORK-FILTERS` — `analytics/views.py`, `templates/analytics/_filters.html`
**Milestone and construction activity, on the Work tab only.** Analytics carried
month, project and document type, and the one tab that is entirely about site
work had nothing for the two things it is actually about.

**⚠ THIS POINT NEARLY GOT LOST.** It was marked Decided in the review and then
never assigned to a slice, so it sat unbuilt while four commits went past. There
is nothing clever in it; it is written up because it was forgotten.

**⚠⚠ THE TWO SELECTS LIVE INSIDE THE SHARED FILTER FORM.** A second form beside
it would post `milestone` on its own, and the project would fall back to the
first Won site — quietly showing somebody another building's numbers. They render
only where the view supplies the choices, which keeps the promise at the top of
`_filters.html`: one include, not five copies.

**⚠ THE CHOICES COME FROM THIS PROJECT'S HEADERS, NOT THE MASTER.** Offering
eighteen activities on a site that uses four is **bug 14 in a different hat** —
the prototype dropdown that listed every project's header tasks.

**⚠ THE CHART IGNORES THEM, DELIBERATELY.** It is the same drawing the site team
reads every morning, from the same module, and a Gantt showing one phase out of
six is a different picture from the one they discuss. **The screen says so** when
a filter is on, rather than leaving it to be noticed.

*Out of scope, noted in the review:* the task board filters by project only. Left
alone unless he asks.

### The four later tabs — `analytics/budget.py`, `rates.py`, `vendors.py`, `velocity.py`
**Each one reads a calculator that already exists and re-derives nothing.**

| tab | url name | the rule it reuses |
|---|---|---|
| Cost to complete | `analytics_cost_to_complete` | `budget.by_trade/by_project`; forecast = committed + max(plan − committed, 0), **per row** — the floor is per row, so the footer adds rows rather than re-deriving from totals |
| Rates | `analytics_rates` | `PurchaseOrderLine.taxable / quantity` — the frozen line rate after discount; approved onward only; top 15 by committed |
| Vendors | `analytics_vendors` | `PurchaseOrder.totals()` via `money`, `money.days_to_pay`, `bom_calc.planning_rate`; late = local `delivered_at` − `required_by`, and a document with no `required_by` is **counted, never given a date** |
| Sales velocity | `analytics_sales` | `sales.calc` — `demand_total`, `receipt_credit`, `bulk_unit_status`; `requires_any("analytics.view", "sales.view")`, the one analytics page open to the sales desk, and the tab strip shows it alone to them |

**The assumption on Cost to complete is in the screen title and nowhere else.**
Every list is bulk-fetched and a 3-vs-23-row query-shape test guards each.

**⚠ `.legend` AND `.hint` ARE GONE FROM THE ANALYTICS TEMPLATES.** A series key is
drawn inside the SVG (`charts._key`); a donut or stacked bar prints its key as
`.keys/.key` rows from base.html — name truncating with a `title`, figure
right-aligned in tabular numerals. Bar SVGs are `width:100%;height:auto` so they
fill the card at any width; the two-card rows are `.grid2` (auto-fit, `min-width:0`).

---

## Compliance

### `COMPLIANCE-MODEL` — `compliance/models.py`
**AMC is the Ahmedabad Municipal Corporation**, not annual maintenance. That
question was asked before a line was designed and changed every checklist item
while leaving the structure identical.

**Type → title → item → documents.** The checklist is STANDARD and the documents
are per project: adding an item makes it Missing everywhere at once, which is
correct for a new municipal requirement and is why the item dialog says so
before saving. `applies_to_every_project` is what separates AMC from RERA, and
being a field rather than a rule is what lets a lender's covenant pack arrive
without a code change.

**⚠ NOTHING IS OVERWRITTEN AND NOTHING IS DELETED.** A new upload is a new
version and the old one stays downloadable — *"the superseded one is often the
one an inspector asks about"*. Versioned by existence, not by a flag: the newest
row is current, so there is no `is_current` to fall out of step.

**⚠ EXPIRY IS TYPED, NOT READ FROM THE PDF.** It could be; it should not be.
Municipal documents vary wildly, many are scans, it adds two dependencies to a
project that installs three, and **a silently wrong expiry is worse than a blank
one**.

**`FileField`, not `ImageField`** — no Pillow. The objection that killed task
photos does not apply here and was not carried over by habit.

### `COMPLIANCE-PRUNING` — `compliance/models.py`, `compliance/views.py`

**One project dropping a checklist line it does not need.** Before this there
were exactly two states — an item belonged to every project, or to exactly one —
so "not applicable to THIS site" could only be said by deactivating the line in
the master, which removed it from every project at once. Saahil hit precisely
that: *"I removed something and it disappeared from every project."*

**⚠⚠ THE TYPE-LEVEL TICK IS NOT TOUCHED AND MUST NOT BE.** `ProjectCompliance`
and `applies_to()` are unchanged. He was explicit — *"I like that option of RERA
applicable or any other compliance of applicable, and then based on that
checkbox, it loads at the bottom. So please keep that."* Ticking a regime still
loads every one of its items. **This works one level below that, on lines.**

**⚠⚠ IT RECORDS WHAT WAS REMOVED, NOT WHAT WAS SELECTED.** He described the shape
as the BOQ's "add ticked trades", which is a selection — but every behaviour he
asked for is the opposite of one:

```
"the project starts full and is pruned"   ->  no rows means everything applies
"a new master line lands on every          ->  nothing to write; absence already
 existing project"                             means included
"removing a line removes it from that      ->  one row, on one project
 project only"
```

A selection table would need every project × every line written on migration and
a fan-out write to every live site whenever the master gains a line — **the exact
operation that can silently miss a project.** This one cannot: to be missed, a
row would have to be created by mistake.

**⚠⚠ THE FILTER LIVES IN `_items_for()` AND NOWHERE ELSE.** Every screen's item
list funnels through that one function — the project screen, the Overview and the
Expiry timeline — so a removed line leaves the rows, the "needs attention" counts
and the timeline in the same instant. Filtering on the screen instead would leave
the Overview counting a line the project no longer shows: everything renders, and
one of them is lying.

**⚠ `removed_item_ids()` IS FETCHED ONCE PER PROJECT, outside the regime loop.**
The Overview walks every Won project against every regime; a lookup inside would
multiply by the number of types. Bugs 3 and 9's shape.

**⚠ REMOVAL IS REFUSED WHILE THE LINE HOLDS DOCUMENTS**, and the message says how
many. Removal is for lines that were never applicable to the site — a lake NOC on
a plot with no lake. It must never orphan filed paper. The button is not drawn in
that case either, because a button that always refuses is not a button; the
server refuses regardless.

**⚠ NOTHING IS GREYED OUT.** Claude proposed keeping a removed line visible and
marked "not applicable", reasoning from vendors being deactivated rather than
deleted. He rejected it — *"if we just make it not applicable, then it may fill
up a lot of space as well"* — and was right: a project showing 21 AMC lines of
which 8 are noise is worse than one showing the 13 that matter. Removed lines
live in their own block at the foot of the screen, **and that block does not
exist when nothing has been removed.**

**⚠ `compliance.master`, NOT `compliance.upload`.** Pruning changes what the
project is judged against — it moves the denominator on the Overview — so it sits
with the people who own the checklist rather than everyone who can file a
certificate. One line in the matrix to widen if that proves too narrow in use.

### `COMPLIANCE-STATUS` — `compliance/status.py`
**Derived, never typed.** Missing · Held · Valid · Expiring (inside 60 days) ·
Expired · Due again (a quarterly filing over 92 days old). Nobody maintains a
status field, so nothing can quietly disagree with reality.

**A one-time document is Held and never expires** — giving it an expiry it does
not have puts a permanent approval on a renewal list forever. **Only compulsory
items count towards "needs attention"**, or people learn to ignore the number.

### `COMPLIANCE-SCREENS` — `compliance/views.py`
**⚠⚠ DOCUMENTS ARE SERVED THROUGH A PERMISSION-CHECKED VIEW AND NEVER FROM A
URL.** There is a `MEDIA_ROOT` and deliberately no `MEDIA_URL`. A signed
municipal approval readable by anybody holding the link would be the worst
mistake this module could make. A missing file is a 404, not a crash — a restore
that brought back rows without the media folder must not take every screen down.

**Read: Admin · Compliance · Project manager · Site engineer · Accountant.
Upload: Admin and Compliance.** This supersedes the original matrix row —
*"a site engineer in front of an inspector needs the labour licence on their
phone"*, and that is a read.

**"View" is the same door as "Download".** `view_inline` (`…/document/<id>/view/`)
runs the same lookup, the same permission and the same 404, and differs only in
the header: inline, with the content type for pdf/png/jpg so the browser opens it
in a tab. Anything else falls back to an attachment. Both rows are in
`test_matrix.SCREENS`.

**⚠ THE BACKUP MUST COVER THE MEDIA FOLDER.** `pg_dump` alone silently misses
every document.

### `COMPLIANCE-MASTER` — `compliance/views.py`, `templates/compliance/master.html`
**The template, not a project.** Saahil asked the question directly — *"what is
this meant for, because in the same one project I can review everything based on
project"* — and the answer is on the screen: a line typed here appears on every
project of that type. Ten sites, one typing. **Documents are never uploaded here.**

**AMC and RERA are the only constants.** Every title and line item under them is
added on screen; a new regime needs one decision — compulsory everywhere, or
ticked per project.

**⚠ THE DIALOG STATES THE BLAST RADIUS BEFORE SAVING** — *"this appears as
Missing on 2 projects straight away"*. That is the deliberate difference from the
task master: a task belongs to one site, a checklist item lands on all of them.

**An item may belong to ONE project** (`ComplianceItem.project`) for a condition
attached to one plot. Null means every project, which is the normal case, and the
screens mark the exception so it is not mistaken for a bug.

**⚠ THE SUGGESTED EXPIRY IS ARITHMETIC, NOT EXTRACTION.** Nothing on their server
can read a PDF — no model on that machine and no internet. `validity_days` on the
master gives issue date + N, shown in yellow with "check it against the
document"; touching the field clears the highlight because the answer is now the
person's. **A guess that looks like a fact is the failure to avoid.**

**Correcting is not replacing.** Two things hide under "change an approval": the
paper is superseded → **Replace**, a new version; the typing beside it is wrong →
**Correct details**, and the file is untouched. Re-uploading to fix a typo would
leave two identical files and make the version history a lie. `corrected_by` and
`corrected_at` record it.

---

### `INFO-PANELS` — `projects/help_panels.py`, `templates/_infopanel.html`

**Points 4, 5 and 6, and the last of the review.** The ⓘ was on 17 of 48 screens
and Saahil was clicking in the half that had none.

**⚠⚠ THEY CHANGED IN KIND, NOT ONLY IN WORDING.** The old panels explained *why a
screen is designed as it is* — about 4,500 words of reasoning. They now say
**what to do on it**, numbered, task first. The reasoning did not disappear: it
moved here and into the code comments, where the person changing something reads
it. **Nobody at a site office needs to know why a rule exists in order to follow
it.**

**⚠⚠ AS DATA, NOT AS THIRTY-NINE HAND-WRITTEN DIALOGS.** Same reasoning as the
launchpad's tiles and the master tab strip, and four things follow from it:

- **The format cannot drift.** Twenty templates each carrying their own markup is
  twenty chances to grow a different heading size or lose the index.
- **The index writes itself** from the step labels, so it cannot fall out of step
  with the steps. Written by hand it would be wrong the first time somebody
  inserted a step in the middle.
- **The rules are testable** — `projects/test_info_panels.py` checks every step's
  word count, every label's length and that nothing but a control is bold.
- **The Gujarati is one field per step.** Every panel gains its translation
  without a template being touched again.

**⚠ THE THREE CONVENTIONS, LOCKED**, from the sample he approved: the index is
short labels not sentences · 20–30 words a step · **bold is only ever a button or
a field name**, never emphasis.

**⚠ THAT LAST ONE IS ENFORCED BY THE SYNTAX.** `[[Order Qty]]` is the only thing
that becomes bold, and the brackets are named for what they may contain, so
emphasis cannot creep in by habit. **Escape first, then bold** — the other order
would let `[[<script>]]` through, because brackets survive escaping.

**⚠ THE SECURITY WARNING IS NOT IN A PANEL.** It stays on the page, in
`base.html`. *A risk you have to click to discover is a risk nobody discovers.*
Unchanged.

**⚠ SCREEN LABELS STAY ENGLISH; only the panel is bilingual.** Translating the
buttons would put two vocabularies in one room the first time somebody reads a
screen over somebody else's shoulder. **The toggle appears only when every step
of that panel has a translation**, and the Gujarati is written by Claude and
**must be checked by their own people before it ships** — the same rule as the
compliance checklist.

**⚠ THE GUJARATI IS WRITTEN BY THEM, ON A SCREEN — `masters.PanelTranslation`.**
Saahil's idea and better than the plan it replaced: *"what if we allow the admin
to add gujarati info on their own, so they can edit your text wherever
necessary?"* Their liaison person corrects it in the app rather than checking a
document somebody then has to paste back.

- **AN OVERLAY, NOT A COPY.** A row exists only where somebody has written a
  translation. An untouched install behaves exactly as it did before the table
  existed, and clearing a box falls back rather than going blank. The
  alternative — every panel seeded into the database — would stop the app's own
  instructions following the app: rename a button in a commit and the panel
  would still name the old one, with nothing to notice.
- **⚠⚠ GUJARATI ONLY, AND STRUCTURE IS NEVER EDITABLE.** No adding, deleting or
  reordering a step, and the English is printed rather than typed into. His
  words: *"Structure should never be editable in reality, especially by a
  user."* Reordering lets the panel drift from the screen; rewording the English
  lets it drift from the tests.
- **⚠⚠ `source_english` IS WHAT KEEPS IT HONEST OVER TIME.** A translation is
  written against a particular English instruction; when that instruction later
  changes, the Gujarati describes something that no longer exists and **nobody
  reading only Gujarati could ever find out**. The row stores what it was
  written from, and the screen flags every row where the two have parted
  company. The BOQ-reserve-matching-on-a-name failure, caught by design.
- **KEYED BY THE STEP'S LABEL, not its position** — inserting a step would
  otherwise re-attach every translation below it to the wrong instruction.
- **`help.edit`, Admin alone** — narrower than `masters.edit`, which Project
  manager, Purchase and Accountant all hold. This is what the whole company
  reads as instructions, in a language most of the office cannot check.
- **⚠ ONE QUERY PER SCREEN, AND IT WAS MEASURED FIRST.** BOM: 30 queries and
  1.2s. Launchpad: 2 and 10ms. Six rows on an indexed pair is inside the noise.
  **No cache, deliberately** — a cache is a rule somebody must remember to
  invalidate, in a company with no IT team. Two query-budget tests moved by
  exactly one and say why.
- **The sixth entry on Master data.** ⚠ That was five by his own earlier
  decision; he asked for this one.

---

## Rules that hold across the whole codebase

**All BOM arithmetic belongs in one file — `projects/bom_calc.py`.** One function
per derived field. The screen, the Excel export and PO generation all call it.
In the prototype `To Order` is already computed in three places; scattered across
Django it would become four, and a tweak would silently break three of them.

**Deactivate, never delete, once something references a record.** Nothing points
at it → allow a real delete. Something does → block it and offer deactivate,
naming what is using it. *Delete means "this was a mistake". Deactivate means
"we have stopped using this".*

**The screens calculate nothing.** `projects/views.py` may parse what a human
typed and decide what to show; it may not decide what a number means. Templates
print values from `bom_calc` and format them with the `inr` filters, which do
digit grouping and nothing else. A total added up in a template is a second
implementation of a rule that already exists.

**Passing a sum into a bom_calc function is not caching.** Several figures need
the same three quantities, so `line_figures` sums them once and hands them down
as optional arguments. Call any function on its own and it queries exactly as
before. What remains forbidden is *storing* approved / in-draft / received on
the BomLine, where a second copy could drift from the purchase orders.

**Flag speculative code rather than quietly adding it.** No fields, models or
settings that nothing currently uses.

---

### `MASTER-TABS` — `projects/master_tabs.py`, `templates/projects/simple_master.html`

**⚠⚠ FIVE ENTRIES BEHIND THE TILE, AND NOTHING OPENS DJANGO ADMIN.** Saahil, after
a tile dropped him into generic scaffolding: *"Can we not just make it one tile
and then have different sections to navigate it? So the master data when we go
inside, we do not see sixty eight tiles."*

```
Materials                → Material master · Material groups · Units of measure
Vendors                  → Vendor master · Vendor groups · Vendor rates
Construction activities  → one screen, no tabs
Company                  → profile only
Users                    → its own entry, not inside Company
```

**⚠ THE THREE CODE-AND-NAME TABLES SHARE ONE VIEW.** Material groups, vendor
groups and units of measure are the same shape — a short key, a name, a flag or
two. What differs between them is DATA, in `SIMPLE_MASTERS`. Three near-identical
views would be three places to fix the next thing.

**⚠ THE TAB STRIP IS DATA, exactly like the launchpad's tiles**, and each tab
carries the key that opens it. Same rule: a tab that leads to a 403 is worse than
no tab.

**Edited in place — one form, one Save, a blank row at the bottom to add with.**
These tables are touched a few times a year; a list plus a form plus a confirm
screen would be three screens earning their place on a table of eleven rows.

**⚠ NOTHING IS DELETED FROM HERE — Active is the only route out**, and each row
shows how many records depend on it. A group or a unit is referenced by
definition, so the app-wide delete rule always lands on "refuse and offer
Deactivate".

**⚠⚠ ALL THREE TABLES MUST CARRY `is_active`, BECAUSE THE TEMPLATE DRAWS IT FOR
ALL THREE.** `MaterialGroup` did not, so its Active column rendered unchecked on
every row — reading as "everything is deactivated" — and ticking one saved
nothing, because the view guards with `hasattr`. Nothing was ever corrupted: it
was a control that could not fail because it could not act, which is worse. Fixed
by migration `masters/0012`. **If a fourth table is ever added to
`SIMPLE_MASTERS`, it needs the field before it needs anything else.**

**⚠ A FLAG HAS TO DO SOMETHING.** Retiring a group removes it from the material
form's dropdown and from the Excel template's validation list — but **not** from
the importer, which stays forgiving so a re-imported export still reads, and
**not** from the material already in it (`_groups_for`, the same shape as
`_uoms_for`). **It cannot touch an existing material code**: the group code is
the middle segment and codes are assigned once — `ANCHOR: CODE-GEN`.

### `ACTIVITY-MASTER` — `projects/master_tabs.py`, `templates/projects/activity_master.html`

**⚠⚠ THIS ABSORBED THE "COMPANY RATES" SCREEN, and `/company/rates/` now
redirects here.** The company's default ₹/sqft was never company data — it is a
column on the activity. Saahil: *"Those rates are related to concerned activity.
Are they not? So already we are maintaining the rates in construction activity,
then why is it coming in company profile?"* One screen carries name,
abbreviation, ₹/sqft, GST %, basis and active — which is why this tile needs no
tabs.

**⚠ THE NAME IS VISIBLE AND EDITABLE, AND THE MODEL REFUSES THE RENAME** — see
below. Hiding the field was the OLD protection and it protected nothing. A
visible field that refuses, and says why, teaches the rule; an absent field
teaches nothing. A locked row shows 🔒 and the count before anybody tries.

**⚠ THE ABBREVIATION IS SHOWN AND NEVER EDITABLE.** It is the first segment of
every material code created under this activity — PLM in PLM-PL3-014 — and codes
are never regenerated.

**⚠ ONE GROUPED QUERY FOR THE LOCK COUNTS, NOT ONE PER ROW.** Asking
`estimates_using_the_name` eighteen times while drawing a table is the shape of
bugs 9 and 10.

### `ACTIVITY-RENAME-BLOCKED` — `masters/models.py`, `Activity.clean()`

**⚠⚠ THE NAME CANNOT CHANGE ONCE AN ESTIMATE HAS COPIED IT.** An estimate line
copies the activity's name when it is created, and the reserve is found again by
matching that name back — `estimate.lines.filter(name=activity.name)`. So
renaming "RCC" silently drops the reserve to ZERO on every project quoting RCC.
No error, no warning, on live jobs: the BOM simply starts reporting that a trade
with a budget has no budget.

**⚠ THIS WAS A CONVENTION, NOT A RULE, UNTIL NOW.** The Company rates screen did
not show the name field and that was the entire protection — Django Admin renamed
activities happily. Saahil believed it was already blocked; the belief and the
code had been out of step the whole time, and nobody found out because nobody
tried.

**⚠ IT LIVES IN THE MODEL, NOT A VIEW**, so Admin obeys it too — otherwise the
one route that could do the damage is the one route left unguarded. Same shape as
`UnitOfMeasure.clean()`, and for the same reason: a value copied as TEXT has
nothing that follows a rename. It is a **refusal with a named alternative** —
deactivate and add a new one. Deleting is already safe; three foreign keys point
at Activity with `on_delete=PROTECT`.

**⚠ COUNTED AGAINST THE OLD NAME, NOT THE NEW ONE.** The lines carrying the old
spelling are exactly the ones that would be orphaned.

**⚠ THE REAL FIX IS TO LINK THE RESERVE BY ID.** That is a schema change and is
on the go-live list. Until then this guard is what stands between a rename and a
silent zero.

### `MASTER-EXPORT-FOLLOWS-FILTERS` — `projects/master_views.py`, `masters/sheets.py`

**The download is whatever the screen is showing.** Saahil, reviewing the built
app: *"when I wanted to download, it was only giving me an option to download all
of them. Can we not select a few and then download those?"*

⚠ **THE FILTERS ARE THE SELECTION.** The material list already had four of them
and the vendor list six, so the export reads them from `_filtered_materials()` /
`_filtered_vendors()` — the same function the table is built from. Row
checkboxes were the other option and were rejected: they duplicate a control
that already exists, and they have to survive paging.

⚠ **`rows=None` STILL MEANS THE WHOLE MASTER.** That is what the management
commands and the older tests pass, so the previous behaviour is the default
rather than a special case.

⚠ **THE BUTTON STATES WHICH IT IS DOING** — "⤓ Download these 40" against
"⤓ Download all 705". A file of 40 rows when you expected 705 looks like data
loss, and the label is the whole of the safeguard.

⚠ **THE BLANK TEMPLATE IGNORES THE FILTERS ENTIRELY.** It has no rows by
definition; a filtered template would be meaningless.

⚠ **THE SEARCH BOX RETURNS A LIST, NOT A QUERYSET** — it normalises in Python.
Anything downstream may only iterate.

### `PO-DOORWAY` — `projects/views.py`, `templates/projects/_nav.html`

**Which project tabs a purchase order offers, and to whom.** Saahil, reviewing
as an Admin: *"if I'm going through a PO tile, ideally a BOM should not be
visible… they should only be able to review information about PO."*

⚠ **THE BAR HAD NO PERMISSION CHECK AT ALL** — it predates roles and was never
revisited. An accountant saw a BOQ tab that answers 403 and a site engineer saw
three. **Every tab now carries the key that opens it**, exactly as the
launchpad's tiles do. The rule was already written down for tiles; this is the
same rule one level down.

⚠ **`standalone` MEANS "YOU CAME IN FROM THE PURCHASE ORDERS TILE"**, and then
there are no project tabs at all and the crumb goes back to the register. Same
screen, different doorway.

⚠ **A QUERY PARAMETER, NOT THE REFERER.** A referer is absent on a bookmark,
stripped by some setups and trivially forged. The link that sends you here says
where you came from; nothing else does. An unrecognised value means the ordinary
door — nothing hides the tabs by accident.

### `BOM-STOCK-ONLY` — `projects/views.py`, `accounts/perms.py`

**The site engineer maintains stock, and writes nothing else.** Saahil: *"if the
site engineer can edit the site stock in the BOM table… they are not allowed to
change anything else or place an order, but they can just maintain the stock."*

⚠ **`bom.stock` IS ITS OWN KEY BECAUSE `bom.edit` IS TOO BIG.** One key covers
quantities, rates, vendors *and* the button that raises purchase orders. Handing
that to the person counting bags on site would hand them the money as well.

⚠ **`bom.view` GAINED SITE**, so they can open the screen. Nothing new is exposed
by it: they already hold `po.view` and `po.deliver`, so vendor names and document
values are on their screen today. What they gain is planned quantities on
materials nobody has ordered yet.

⚠⚠ **THE REFUSAL IS FIELD BY FIELD, ON THE SERVER.** `_apply_edits` checks every
field against the person before writing it. The grid is ONE form, so every
button posts the whole page — a hidden input is not a permission, it is a
suggestion. `bom_save` uses `requires_any("bom.edit", "bom.stock")`: the door
opening says nothing about what gets written.

⚠ **THE QUIETEST FAILURE THIS AVOIDS — AND HOW NARROW IT ACTUALLY IS.** A blank
vendor box means "no vendor" to the save path. An engineer's form has no vendor
box at all, so an ordinary browser never sends the key and `_apply_edits`
already skipped it: `if f"vendor-{line.id}" in request.POST`. **That guard was
there first and it holds the normal path.** What the field-level check adds is
the two cases it does not cover — a page rendered while somebody still held
`bom.edit` and submitted after their role changed, and a hand-crafted POST. Both
would have arrived with `vendor-N=""` present and cleared the vendor silently.
Narrow, not imaginary; there is a test named after it.

⚠ **`accounts/test_matrix.py` NO LONGER TELLS THE WHOLE STORY FOR `bom_save`.**
The table can only say the door opened. `projects/test_bom_stock.py` says nothing
else moved, and that is not an optional companion.

⚠ **STOCK IS LOAD-BEARING.** `suggested_order_qty` subtracts it, so the engineer
is moving the figure the purchase manager reads. That is the point.

### `PO-STATUS-FILTER` — `projects/views.py`, `templates/projects/_pofilters.html`

**Status on the per-project purchase-order screens.** Saahil: *"when I open the
PO, it showed a lot of drafts, approved, paid… there should be an option for the
user to filter the PO based on the status."*

⚠ **THE CROSS-PROJECT REGISTER ALREADY HAD ONE.** These two screens — the vendor
list and one vendor's documents — did not, and that is the whole of this change.
Claude wrote the point up as if the register were missing it; the register was
never the screen he was on.

⚠ **"NOT PAID YET" IS A QUESTION, NOT A STATUS** — approved or delivered, and
not settled. It is what people actually ask, and expressing it as a status would
have meant inventing a sixth state the document does not have. The constant
`UNPAID` is shared by the view and the template so the spelling cannot drift.

⚠ **ONLY STATUSES THIS PROJECT ACTUALLY HAS ARE OFFERED**, and "Not paid yet"
appears only when there is something for it to find — the same rule the
register's dropdowns follow. An empty filter option is a promise the screen
cannot keep.

**The full decision log lives in `PROJECT-CONTEXT.md`** in the Outputs folder —
every design decision, why it was made, and what it superseded.


---

### `PO-LINE-SHARES` — `projects/bom_models.py`, `projects/views.py`
**A document's own money — deduction, TDS, round-off — split across its lines so the parts add
back to the whole exactly.** Saahil, 16 Aug 2026, on what his accountant actually does with the
register export: *"they filter the values and use that Excel to put it in tally... the header
discounts have to be distributed properly across all the line items that are present on the PO
so the numbers add up properly for them, and they can simply input that full and final value
entirely for their accounting."*

**⚠⚠ WHAT IT REPLACED WAS A NAMED, DELIBERATE TRADE THAT TURNED OUT TO BE THE WRONG WAY ROUND.**
Four columns repeated the document figure on every line, and the heading said `(repeats)` to warn
that they could not be summed. A four-line order printed its TDS four times. The warning was
honest and it was not enough: this file exists to be filtered and added up, so **a column that
must not be added is a trap in a file built for adding.**

**⚠⚠ THE RESIDUAL IS THE POINT.** Three equal shares of ₹1000 are ₹333.333… each; rounded
independently they sum to ₹999.99. `apportion()` floors every share to the paisa and hands the
leftover paise to the largest fractional parts, so the total ties **by construction, not by
luck**. Ties go to the LAST line — 333.33 / 333.33 / **333.34** — which is the split Saahil
described, and matching the checker's mental model beats winning a coin flip.

**⚠⚠ THE BASES FOLLOW THE LADDER IN `PO-TOTALS`, THEY ARE NOT PICKED FOR CONVENIENCE.**
`deduction` is charged post-tax on the invoice value → apportioned on each line's **total**.
`tds` is computed on the taxable value and **never on the GST** → apportioned on each line's
**taxable**. `round_off` rides with the deduction so `order_value` still ties. One base for all
three would have been simpler and would have put TDS on the wrong money. The test fixture carries
three different GST rates precisely so the two bases give visibly different answers.

**⚠ IT READS `totals()` AND APPORTIONS WHAT IT FINDS.** Not one percentage is recomputed. A
second implementation of the ladder would be free to disagree with the printed order.

**⚠⚠ THE FIRST DRAFT OF THE EXPORT TEST COULD NOT FAIL.** The shared fixture raises orders at 0%
deduction and 0% TDS, so both columns summed to zero and the assertion passed against the old
repeating code exactly as happily as against the new one. The percentages are now set inside the
test, and it was **checked by reverting the code and watching it fail** — 90,120.84 against
45,060.42, precisely double for a two-line order.

**⚠ TWO SILENT DRIFTS FIXED IN THE SAME PLACE.** `widths` held 26 entries for 27 columns and the
number format ran 15–26 when the money starts at 16 — so UOM was being given Indian digit
grouping and the last money column got neither a width nor a format. Both are now keyed off
`headings`, like the fill above them, which is the same lesson one column later.

### `DUMMY-GSTINS` — `projects/management/commands/seed_dummy_gstins.py`
**Fake GST numbers, so a test database can approve purchase orders — and every guard that
keeps them from ever reaching a real one.** Saahil, 16 Aug: *"We will probably add the GST
number over the whole lifetime. So for the time being, you can use dummy GST numbers to put
in and approve all the POs without any hard blocks."*

**⚠⚠ THE HARD BLOCK IS NOT WEAKENED. Not one line of `approve()` changed.** `GSTIN-CAPTURE`
still refuses an order to a vendor with no GSTIN, and a test here asserts it still does. This
command fills DATA that satisfies the rule. The distinction matters: the rule is correct, and
softening it to unblock a walkthrough would have removed a legal check to save typing.

**⚠⚠ EVERY NUMBER CARRIES `ZZDMY` IN THE PAN BLOCK.** `24ZZDMY0007Z1Z5` passes `gstin_format`
and is unmistakable on screen, in an export and on the printed order. A dummy that looks real
is the dangerous kind — it survives to production and prints on a document actually sent.
The marker is also what `--remove` matches on, so removal can never take away a real number.
The four early dummies built from the help text's own example (`ABCDE1234F1Z5`) are normalised
onto it, so "which of these are fake" has exactly one answer.

**⚠⚠ OUR OWN GSTIN IS SET TOO, AND THAT IS NOT A CONVENIENCE.** `_is_interstate()` returns
False whenever the company GSTIN is blank, so until it is filled EVERY order prints CGST +
SGST regardless of where the vendor is. Filling vendor numbers alone would have produced a
database where approval works and the tax split is silently always-local — worse than being
blocked, because it looks right. Mixed state codes for the same reason: all-Gujarat would
leave the IGST branch untested, and that branch decides which tax lines a real document shows.

**⚠⚠ A HOLDBACK IS LEFT WITH NO GSTIN, ON PURPOSE.** The vendor master header counts
"N without a GSTIN" and that number ties straight to the go-live gap — 169 of 174 vendors, the
thing most likely to delay the project. Filling everything would make it read 0 and hide it.
Only vendors with NO purchase orders are ever held back, so the holdback can never be what
blocks an approval.

**⚠ THE HOLDBACK IS CHOSEN OVER A STABLE POPULATION, NOT OVER "WHATEVER IS BLANK RIGHT NOW".**
Picking from the current blanks meant the set moved between runs — remove, refill, and a
different twelve were held back, so a count nobody had touched changed by itself.

**⚠ AN UNREGISTERED VENDOR IS NEVER TOUCHED AT ALL.** Not filled — the tick means "no GST
registration, ever", and a number would contradict it and raise their lines from 0% to the
material rate. Not counted as held back either: it is already permanently blank, and letting
it occupy a slot made the holdback number a lie (ask for five, four are actually held).

**⚠ REFUSES TO RUN WHEN `DEBUG` IS FALSE.** The one guard that matters, and it covers
`--remove` as well. Everything else here is tidiness; this is the line between a convenience
and a fake GSTIN on a filed return.

**⚠⚠ IT DOES NOT TOUCH `VENDOR_MASTER.xlsx`.** That workbook is what seeds production — see
G1, the screen's export cannot — so it must stay clean. This command writes to the database
and nowhere else.

```
python manage.py seed_dummy_gstins --dry-run
python manage.py seed_dummy_gstins
python manage.py seed_dummy_gstins --remove
```

---

## Checking things

```
python manage.py test              every rule above, in seconds, throwaway database
python manage.py check_integrity   your REAL data, read-only, safe any time
python manage.py seed_demo         a demo project to click through
python manage.py seed_demo --remove
python manage.py seed_stress       awkward test data — every activity at once
python manage.py seed_stress --remove
python manage.py seed_dummy_gstins fake GSTINs so orders can be approved — DEBUG only
python manage.py seed_dummy_gstins --remove
python manage.py runserver         then open http://127.0.0.1:8000/
```

`test` proves the CODE is right using invented data. `check_integrity` checks
that YOUR DATA is sane. You need both — correct code can still be handed a
spreadsheet with two materials sharing a code.

---

## Sales (slice 10)
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

---

## Finance (slice 10) — shown to people as "Finance & Accounting"

### `WO-TERMS` — retention switched off, 11 Sep 2026
**⚠ RETENTION IS SWITCHED OFF ON THE CUSTOMER'S INSTRUCTION (11 Sep 2026).** `retention_pct`
defaults to 0 (`projects/0012_retention_switched_off`, which also clears the old 10% on every order
with no approved RA bill), the retention and DLP inputs are gone from `po_detail.html` and
`_apply_po_edits` no longer reads them, the Retention tab, `finance_retention` and
`finance_retention_release` are gone, and the RA bill screen, PDF, register and Excel print no
retention row or column when it is zero — which it now always is on a new order. **The fields, the
ladder rung, `RetentionRelease` and `services.release_retention` stay** ("unused, kept for data"):
orders billed at 10% before that date keep their figures, and
`test_ladder.TheLadderStillHandlesRetention` is the ONE test that keeps the arithmetic honest. The
mobilisation advance is the one term still typed on a draft work order.

### `FIN-CALC` — the ladder, and the registers built on it
**⚠ RETENTION IS ON THE WORK VALUE, NOT THE INVOICE.** Retention secures the work; the GST is
the contractor's liability to the department this month and is paid in full. The deduction
stays post-tax because it is the same agreed deduction as on the order (PO-TOTALS), and one
base for both would put one of them on the wrong money — the test fixture carries three GST
rates so the two bases give visibly different answers.

**⚠ THE ADVANCE RECOVERY FOLLOWS THE AGREED TERM, NOT THE PAYMENTS REGISTER.** Outstanding =
`mobilisation_advance` less what earlier APPROVED bills recovered. Not the sum of advance
payments made: a bill approved in March must print the same figures in June, and a payment
recorded late would otherwise move an approved bill's net payable. The work order screen shows
advance agreed / paid / recovered side by side for the case where they differ; a test proves a
late advance payment leaves an approved bill's net payable untouched.

**⚠ "TO DATE" SUMS OVER APPROVED AND PAID BILLS ONLY**, exactly as a draft PO counts nowhere in
ANALYTICS-MONEY. `dlp_end` = final bill's `approved_at` + `dlp_months`, None until then;
`retention_eligible` = DLP ended and a balance held.

**PO side:** `po_settlement` = order `net_payable` (from `totals()`), Σ invoice totals, Σ
payments, Σ TDS withheld, balance = net payable − paid; `over_invoiced` when Σ invoice totals
exceed the order value — amount level only, an invoice carries no quantities.

**THE BILLS REGISTER (`bills_register`, 11 Sep 2026)** puts a VB- invoice on a PO and an
APPROVED/PAID RA- bill on a WO in ONE shape: `amount` is the bill as the vendor wrote it (invoice
total / RA `invoice_value`); `tds` is the RA bill's own ladder TDS, or on an invoice what the
payments withheld; `paid` Σ `payment.amount`; `balance` RA `net_payable − paid`, invoice
`total − (paid + TDS)`; status open / part_paid / settled. A draft or certified RA bill is not a
bill. `ageing` buckets open balances by DAYS SINCE THE BILL DATE (0–30 / 31–60 / 61–90 / 90+);
`overdue` and `cash_out` use the due date = bill date + `analytics.money.credit_days(vendor)`,
with the 30-day default counted and shown, as ANALYTICS-MONEY insists.

**THE VENDOR LEDGER (`vendor_ledger`)** — the convention the accountant reconciles with Tally: an
ORDER row (approved onwards) shows the order value and MOVES NOTHING; a BILL row credits what we owe
(invoice total; RA bill `invoice_value − deduction + round_off`, i.e. BEFORE the advance recovery
and retention, so the advance debit is cleared by the bills rather than hidden inside them); a
PAYMENT row debits `amount + tds`. `balance = Σ bill − Σ (paid + TDS)`, running in date order; a
negative balance is an advance not yet recovered, zero is fully settled. Rows before `date_from`
fold into the opening line. `TheVendorLedger` proves the closing balance ties and that a fully
recovered advance closes at zero.

**THE TDS REPORT (`tds_report`)** — per fiscal quarter (`fiscal_quarters` on
`analytics.periods.fiscal_start`), one row per vendor × section × rate over every payment dated in
the quarter: `base` is the bill's TAXABLE in the proportion the payment settles of it (RA:
`taxable × (paid + TDS) ÷ payable`; invoice: `taxable × (paid + TDS) ÷ total`; an advance is its
own base), `gross` = paid + TDS, `tds`, `paid`. Grouped by section with subtotals; the CA files 26Q
from the Excel. Nothing is filed from here.

### `FIN-CALC-BULK` — `finance/calc.py`
**`bulk_cumulative`, `bulk_bill_figures`, `bulk_invoice_figures`, `bulk_po_settlement` fetch
every related row for a set of orders in a fixed number of queries.** `bulk_bill_figures`
fetches the WHOLE order's bills even when the caller filtered some out, because the advance
carry runs bill to bill. Tests pin the registers at fewer than ten extra queries between 3 and
23 work orders.

### `FIN-CUMULATIVE` — `finance/services.py`
**Cumulative certified — earlier approved bills plus this one — may not exceed the work order
line's quantity.** Checked on save, on certify and again on approve; refused with the line
named and the excess stated ("… which is 0.500 over the order's 10.000"). Over-delivery on a
PO is allowed (TASK-MODULE); over-certification on a WO is not, because certification is what
the contractor gets paid for.

### `FIN-SERVICES` — `finance/services.py`
**Every write, atomic, raising `FinanceError` with a message for the person.**
DRAFT → CERTIFIED → APPROVED → PAID, strictly sequential. One open bill per work order; no bill
after an approved final bill; approve needs every line certified and writes receipts through
`record_receipt` with `Source.RA_BILL` (zero lines write none); part payments allowed, PAID when
Σ amount ≥ net payable, never more than is left; the WO turns PAID when every bill is paid and a
final bill exists. `release_retention` is UNUSED, KEPT FOR DATA (retention switched off, 11 Sep
2026): it still refuses more than the balance and refuses before the DLP unless `override=True`
WITH a note, and writes a `RetentionRelease` AND a `VendorPayment` of kind `retention_release` —
but no route or screen calls it. A PO turns PAID when Σ payments ≥ its net payable and it is
DELIVERED. Numbers `RA-` / `VB-` / `PV-` come from `NumberSeries`, never from max().

### `FIN-SCREENS` — `finance/views.py`
**finance.view** reads everything — Overview, Bills, RA bills, Payments, Vendor ledger, TDS and
every Excel; **finance.certify** raises bills, types certified quantities, discards drafts;
**finance.approve** approves bills; **finance.pay** records bills (invoices) and payments, and is
the key on `finance_bill_pick`, the "Record a bill" doorway that asks for the PO first.

**⚠ THE TAB STRIP CARRIES `project` ALONG** (`templates/finance/_nav.html`), as analytics carries
its filters — only `project`, because status and type mean different things on different tabs.

**⚠ TWO SCREENS OPEN TO view OR certify — `finance_wo` and `finance_ra_bill` — via
`requires_any`.** The site engineer holds certify and not view; the bill they certify must be a
screen they can open, and "a permission is only real if the role can reach the screen the
button is on" (PERMS-MATRIX). Used on those two READS only; every write behind them carries its
own single key, and tests prove Site is refused every register, the PDF and the PO screens.
The nav strip is hidden without finance.view so no tab leads to a 403.

**RA bill PDF is approved onwards only** (the PO-PDF rule). The Excel exports follow the
screen's filters; widths and formats are keyed off `headings`, never counted by hand.

---

## Drawings (slice 10)
## Drawings

### `DRAWINGS-MODEL` — `drawings/models.py`
**Five tables, two of them masters.** `Architect` and `DrawingGroup` are
shared; `Drawing`, `DrawingRevision`, `Transmittal`/`TransmittalLine` are per
project. The register is grouped by `DrawingGroup` (ARC, STR, MEP, LND, INT,
SUR — seeded by `0002_seed_groups`).

**The drawing number is typed, not generated.** It is the architect's number
from the title block, unique per project only — two architects on two sites may
both call their first sheet A-101.

**A revision is a new row.** `DrawingRevision` is versioned by existence: the
newest row (`-uploaded_at, -id`) is current, and every earlier one stays and
stays downloadable, because the contractor who was sent R0 built from R0.

**A transmittal is a record, not a message.** Nothing is sent from the system.
`TransmittalLine` points at the REVISION, not the drawing, so R1 arriving later
cannot change what the record says a contractor was handed. Numbered
`TR-000001` from `NumberSeries("transmittal")`.

Affects: every drawings screen, the transmittal PDF, `drawings/status.py`.

### `DRAWINGS-STATUS` — `drawings/status.py`
**Derived, never typed.** Required = no revision; Received = newest revision
not approved; Approved = newest revision approved. A newer revision after an
approved one puts the drawing back to Received — the paper on site is no longer
the paper that was approved.

**`latest_by_drawing` is the bulk hand-down.** One query for the newest
revision of every drawing on a list screen; `Drawing.status` is for one drawing
and costs a query each. Tested by the query-shape tests in `drawings/tests.py`
(N rows vs N+20, fewer than 10 extra queries).

### `DRAWINGS-NO-DELETE` — `drawings/models.py`, `Drawing.delete()`
**Refused once a revision exists.** The revision FK cascades at the database,
so this guard is the only thing between a stray delete and a transmittal that
says a contractor was sent a drawing that no longer exists. Raises
`DrawingInUse`; the screens offer only the Active tick. A revision on a
transmittal is `PROTECT`ed by the line. A drawing nothing points at can still be
deleted — the same rule as everywhere else.

### `DRAWINGS-APPROVE-ONCE` — `drawings/models.py`, `DrawingRevision.approve()`
**Who and when, recorded once.** A second approval is refused with the first
approver's name and date in the message; the screen hides the button once
approved and the server refuses regardless. Re-approving would move the
signature onto somebody else.

### `DRAWINGS-LABEL-UNIQUE` — `drawings/views.py`, `upload`
**R1 twice on one drawing is refused, not replaced.** Enforced case-insensitively
in the view with a message, and by a unique constraint `(drawing, label)` at the
database. The new file gets its own label; nothing is ever overwritten.

### `DRAWINGS-TRANSMITTAL-ATOMIC` — `drawings/models.py`, `Transmittal.issue()`
**Header and lines together, or not at all — and an empty one is refused
BEFORE a number is taken.** A numbered transmittal with no lines would burn a
number and sit on the register saying nothing. Also refuses a revision from
another project. The view resolves ticked drawings to their newest revision and
offers only drawings that have one.

### `DRAWINGS-SCREENS` — `drawings/views.py`
**Who may do what**, from `accounts/perms.py` and not widened here:
`drawings.view` (A, PM, PUR, SITE) reads and downloads; `drawings.edit` (A, PM)
registers, uploads, approves, edits the masters; `drawings.transmit` (A, PM)
records a transmittal.

**⚠ Files are served through `download` and never from a URL.** No MEDIA_URL,
nothing under the static tree; a missing file is a 404, not a crash. Every
per-project object is fetched scoped to the project
(`get_object_or_404(..., project=project)` / `drawing__project=project`).

**The transmittal PDF imports WeasyPrint inside the view**, the same as
`po_pdf`, and the test stubs the module in `sys.modules`.

### `HOME-SCREEN` — `projects/home.py`, `templates/projects/launchpad.html`
**The first screen — called Dashboard — as a morning briefing rather than a menu.** Four KPI
cards (committed, paid, collected, bookings, each this month with the change against last month),
a committed-against-paid chart by fiscal month, a status ring (units on live sites, else PO
status), then three columns: **Your work** (the signed-in user's open subtasks with lateness,
enquiries assigned to them, orders awaiting their approval), **Recent activity** (approved
orders, bookings, receipts, compliance uploads) and **Upcoming** (tasks, compliance expiries,
demand letters due), a "needs your attention" list, and one card per live site with budget used,
work done and collected of booked. The chart fetches each stage ONCE for the year and buckets by
month in Python — the query-count test in `projects/test_home.py` is the guard.

**⚠ EVERY FIGURE IS BORROWED.** `analytics.money`, `analytics.budget`, `sales.calc` and the task
model already own these numbers; `home.py` only picks which to show. A wrong number here is a
wrong number there.

**⚠ FILTERED BLOCK BY BLOCK BY THE PERMISSION THAT OPENS THE MODULE** — the tile rule applied to
numbers. A site engineer sees no money band. `projects/test_home.py` renders it for every role
and pins the Admin query count.

### `BOM-COLUMNS` — `templates/projects/bom.html`, `templates/base.html`
**Ten columns a buyer touches daily; everything else behind "Show all columns".** Material (name,
code and unit stacked), Plan qty, Stock, Approved, Received, Order qty, Vendor, Rate, Value. Remark,
Min, In draft, Plan rate, Var %, GST % and the two value columns carry `class="xtra"` and are hidden by
CSS until the switch is ticked (remembered per browser in localStorage — a convenience, nothing depends
on it). **The inputs are still in the form when hidden**, so `bom_save` reads exactly what it always
did. The KPI strip shows Budget, Planned, Committed, Received; Variance, Below threshold and To order
now join the hidden set.

### `PO-REGISTER-STEP` — `projects/views.py`, `templates/projects/po_register.html`
**One row, one next step, through `po_advance`.** The register's bulk box still never approves; this
button acts on a single document whose totals are printed beside it, and the approval itself is the
same `po_service.approve` — the GSTIN block, the RA-bill guard and the permission per step
(`TRANSITION_PERMS`) all hold, and a refusal comes back as a message on the register. `back=register`
in the POST sends the person back to the register with its filters rather than to the document.
