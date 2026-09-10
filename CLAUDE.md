# Elegance Skyz — construction automation

Django 5.2 · SQLite in dev, PostgreSQL in production · no static files, all CSS inline.

## Commands

```
.venv\Scripts\activate
python manage.py test            # expect 892, then OK. Run ALONE, never chained.
python manage.py migrate
python manage.py runserver       # http://127.0.0.1:8000/  · login: schokshi
python manage.py seed_showcase   # demo data · --remove takes it away
python manage.py check_integrity # read-only, safe any time
python manage.py import_masters  # ⚠ THE ONLY way to seed a fresh database
python manage.py seed_dummy_gstins  # fake GSTINs so POs can be approved · DEBUG only · --remove
```

## Delegate the reading, keep the judgement

- **Use a subagent for anything that reads many files** — "which screens touch X",
  "find every place that does Y". It runs in its own context and reports back, so the
  file contents never land in this conversation. `Explore` for a sweep,
  `general-purpose` when it must also run commands.
- **Do NOT delegate**: the locked calculation spec, anything touching money, or a
  judgement about what Saahil meant. A subagent starts cold and will confidently
  report a deliberate decision as a bug.
- **Give a subagent this file and `ANCHORS.md` by path**, or it will not know the rules.
- **⚠ CLAUDE CANNOT PRESS SUBMIT BUTTONS** in this app through browser automation.
  Typing into a text field and pressing Enter submits that form; a form of only
  checkboxes and a button cannot be driven at all. Ask Saahil to press those.

## Rules that are not negotiable

- **NEVER run git.** Saahil commits and pushes himself. Ask him for a summary and a
  description; reading `.git/HEAD` and `.git/refs` is fine.
- **Never build without an explicit "go".** He asks for the plan first and reads it.
- **ANCHORS.md ships in the same commit as the code.** Run the drift check every time:
  compare `grep -rhoE "ANCHOR: [A-Z0-9-]+"` against its table. Currently 87.
  ⚠ Exclude `.venv`, `.git` **and `__pycache__`** or the grep runs for minutes,
  times out, and counts compiled copies of the same anchor twice.
  ⚠ `BOM-CALC-` appears in the output and is NOT an anchor — it is the wildcard
  in "a number shown on the BOM SCREEN → `ANCHOR: BOM-CALC-*`". Expect one
  unmatched entry and let it be.
- **There is NO Django Admin.** `/admin/` is a 404 and must stay one — see
  `ANCHOR: NO-DJANGO-ADMIN`. Everything goes through the app's own screens.
- **Arithmetic lives in Python, never in a template.** One bounded exception, the BOQ
  preview script, and it says so at both ends.
- **The yellow-box rule:** a `.note` earns its place only if it stops a mistake at the
  moment of acting, and then it is one line.

## Vocabulary — do not drift

"construction activity" (never "activity" or "trade") · "Basic / GST / Amount" (their
vendors' words, on screen and on the printed order) · a milestone **is** a header task ·
AMC = Ahmedabad Municipal Corporation.

## Traps that have already bitten

- **SQLite integer-divides `10 / 100` to ZERO. PostgreSQL does not.**
- **A percent sign followed by `}` reads as a leaked Django tag** — the raw-syntax test
  fires on CSS too. Keep the semicolon.
- **Read the model, do not recall it:** `Project.bua_sqft` · `BomLine.order_qty_override` ·
  `Role.PROJECT_MANAGER` · `Vendor.gst_number` · `Vendor.payment_terms` ·
  `UserProfile.role` (not on User).
- **`test_matrix.ACTIONS`/`SCREENS` are hand-written.** A new permission key is not caught
  automatically — add the view to that table in the same commit.
- **Test fixtures collide on unique fields.** Use `ZQ*` prefixes.

## Where to read more

`ANCHORS.md` is the map and the single most useful file — read it before changing a rule.
`OPEN-BEFORE-GO-LIVE.md` is the deployment checklist. Outputs holds `RETRACE-LIST.md`
(live bug list) and `PROJECT-CONTEXT.md` (decision log).
