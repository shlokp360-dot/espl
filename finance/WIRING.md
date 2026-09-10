# Wiring the finance app into the shared files

Everything below goes into files this app must not edit itself. Apply in one commit
with the app. Migrations `projects/0011_work_order_terms.py` and
`finance/0001_initial.py` are included — `python manage.py migrate` on every install.

## 1. `accounts/test_matrix.py` — `SCREENS`

The second column is what `address()` passes: `False` = no argument, `True` = id 1
(a 404 for an allowed role is fine; the test only asserts 403 vs not-403).

```python
    # ---- finance ------------------------------------------------------------
    ("finance_home",             False, {A, PM, ACC}),
    ("finance_ra_bills",         False, {A, PM, ACC}),
    # ⚠ THE TWO SCREENS OPEN TO finance.view OR finance.certify. The site
    #   engineer holds certify and not view; the bill they certify has to be a
    #   screen they can open. requires_any on these two reads only — every
    #   write behind them carries its own single key.
    ("finance_wo",               True,  {A, PM, ACC, SITE}),
    ("finance_ra_bill",          True,  {A, PM, ACC, SITE}),
    ("finance_ra_bill_pay",      True,  {A, ACC}),
    ("finance_ra_bill_pdf",      True,  {A, PM, ACC}),
    ("finance_ra_bill_discard",  True,  {A, PM, SITE}),
    ("finance_retention",        False, {A, PM, ACC}),
    ("finance_invoices",         False, {A, PM, ACC}),
    ("finance_po",               True,  {A, PM, ACC}),
    ("finance_invoice_new",      True,  {A, ACC}),
    ("finance_po_pay",           True,  {A, ACC}),
    ("finance_payments",         False, {A, PM, ACC}),
```

## 2. `accounts/test_matrix.py` — `ACTIONS` (POST-only addresses)

```python
    # ---- finance ------------------------------------------------------------
    ("finance_ra_bills_excel",     False, {A, PM, ACC}),
    ("finance_ra_bill_new",        True,  {A, PM, SITE}),
    ("finance_ra_bill_save",       True,  {A, PM, SITE}),
    ("finance_ra_bill_approve",    True,  {A, PM}),
    ("finance_retention_release",  True,  {A, PM}),
    ("finance_payments_excel",     False, {A, PM, ACC}),
```

The GET+POST forms (`finance_ra_bill_pay`, `finance_ra_bill_discard`, `finance_invoice_new`,
`finance_po_pay`) carry the same `@requires` on both methods, so their SCREENS row covers
the POST too.

## 3. `projects/help_panels.py`

```python
from finance.panels import PANELS as FINANCE_PANELS
PANELS.update(FINANCE_PANELS)
```

Twelve entries: `finance_home`, `finance_ra_bills`, `finance_wo`, `finance_ra_bill`,
`finance_ra_bill_pay`, `finance_ra_bill_discard`, `finance_retention`, `finance_invoices`,
`finance_po`, `finance_invoice_new`, `finance_po_pay`, `finance_payments`. Every finance
template already calls `{% infobutton %}` / `{% infopanel %}`; until merged they render
nothing. `finance/tests.py::FinancePanelsKeepTheFormat` keeps them inside the format rules
and asserts the keys used and the keys defined match exactly.

## 4. `templates/finance/_nav.html` — the tab list (already written)

| here        | url name            | label            | who sees it                |
|-------------|---------------------|------------------|----------------------------|
| `home`      | `finance_home`      | Overview         | everyone with finance.view |
| `ra_bills`  | `finance_ra_bills`  | RA bills         | everyone with finance.view |
| `retention` | `finance_retention` | Retention        | everyone with finance.view |
| `invoices`  | `finance_invoices`  | Vendor invoices  | everyone with finance.view |
| `payments`  | `finance_payments`  | Payments         | everyone with finance.view |

The strip is wrapped in `{% if user|can:"finance.view" %}` so a site engineer on the work
order or bill screen sees no tab that would 403. Certify / approve / pay buttons hide on
the screens themselves.

## 5. `projects/hub.py`

The `finance` tile already exists (`url_name: finance_home`, `perm: finance.view`). Nothing to add.

## 6. `templates/projects/po_detail.html` and `projects/views.py` — ALREADY EDITED

These two are not on the do-not-edit list and the brief asked for them:
- three work-order term inputs (retention %, DLP months, mobilisation advance) under the
  totals ladder, WO only, draft only — `_apply_po_edits` reads them;
- an "RA bills" link on an approved-or-later WO (finance.view or finance.certify) and a
  "Vendor invoices & payments" link on an approved-or-later PO (finance.view).

`projects/po_service.py`: `update_draft_document` takes the three terms;
`mark_delivered` / `mark_paid` refuse a WO that has any RA bill (`RA-BILL-OWNS-THE-WO`).
`projects/bom_models.py`: the three fields, and `Receipt.Source.RA_BILL`.

## 7. `ANCHORS.md`

Add the rows and long-form entries from `finance/ANCHORS-finance.md`. Eight new anchors:
`WO-TERMS`, `RA-BILL-OWNS-THE-WO`, `FIN-MODEL`, `FIN-CALC`, `FIN-CALC-BULK`,
`FIN-CUMULATIVE`, `FIN-SERVICES`, `FIN-SCREENS`. (`TASK-MODULE` and `INFO-PANELS` appear in
finance code as references to existing anchors, not new ones.) The drift count goes up by
eight.

## 8. `CLAUDE.md` — test count

`python manage.py test` gains 60 finance tests. Projects stays at 621 (the work-order
terms and the RA-bill guard are covered from the finance suite).
