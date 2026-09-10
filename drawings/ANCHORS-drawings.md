# ANCHORS — drawings

Rows to append to `ANCHORS.md`, in its three places: the "Something wrong
with…" lookup, the register table, and the long-form section. Seven anchors.

## The lookup

```
Something wrong with...              Search for
-----------------------------------  -------------------------------------
a drawing's Required/Received/       ANCHOR: DRAWINGS-STATUS
  Approved pill
a drawing that will not delete       ANCHOR: DRAWINGS-NO-DELETE
approving a revision, or a second    ANCHOR: DRAWINGS-APPROVE-ONCE
  approval being refused
"already has a revision R1"          ANCHOR: DRAWINGS-LABEL-UNIQUE
a transmittal with no lines, or a    ANCHOR: DRAWINGS-TRANSMITTAL-ATOMIC
  burnt TR number
who may read, upload or issue        ANCHOR: DRAWINGS-SCREENS
  drawings, and how files are served
```

## The register

```
DRAWINGS-MODEL               drawings/models.py              five tables; the number is the architect's
DRAWINGS-STATUS              drawings/status.py              Required/Received/Approved, from the newest revision
DRAWINGS-NO-DELETE           drawings/models.py              a drawing with history is deactivated, never deleted
DRAWINGS-APPROVE-ONCE        drawings/models.py              who and when, recorded once
DRAWINGS-LABEL-UNIQUE        drawings/views.py               R1 twice on one drawing is refused
DRAWINGS-TRANSMITTAL-ATOMIC  drawings/models.py              header and lines together; empty is refused before a number
DRAWINGS-SCREENS             drawings/views.py               who reads, who uploads, how files serve
```

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
