# ANCHORS — finance

Rows to add to `ANCHORS.md`, in its style. Each `>>> ANCHOR: NAME <<<` below
appears as a comment in the code at the place named.

## Rows for "How to use this"

```
Something wrong with...              Search for
-----------------------------------  -------------------------------------
retention %, DLP months or the       ANCHOR: WO-TERMS
  advance on a work order
"Mark completed" / "Mark paid"       ANCHOR: RA-BILL-OWNS-THE-WO
  refused on a work order
what an RA bill stores, and what     ANCHOR: FIN-MODEL
  it never stores
any rupee figure on an RA bill,      ANCHOR: FIN-CALC
  its PDF, the registers or a KPI
a finance list screen that has       ANCHOR: FIN-CALC-BULK
  got slow
"over the order" when certifying     ANCHOR: FIN-CUMULATIVE
raising, certifying, approving,      ANCHOR: FIN-SERVICES
  paying a bill; releasing retention;
  recording an invoice or a payment
who may open which finance screen    ANCHOR: FIN-SCREENS
```

## Rows for "Every anchor, and where it lives"

```
ANCHOR                     Lives in                        What it governs
-------------------------  ------------------------------  ------------------------------
WO-TERMS                   bom_models.py, po_service.py,   retention, DLP and advance terms on a WO,
                           views.py, po_detail.html         draft-only, never in the PO ladder
RA-BILL-OWNS-THE-WO        projects/po_service.py          a billed WO is completed and paid by finance
FIN-MODEL                  finance/models.py               bills store quantities and frozen rates, no money
FIN-CALC                   finance/calc.py                 the RA bill ladder, ONE copy, half-up per rung
FIN-CALC-BULK              finance/calc.py                 registers: fixed queries, not per row
FIN-CUMULATIVE             finance/services.py             certified to date may not exceed the order
FIN-SERVICES               finance/services.py             every finance write, atomic, user-facing refusals
FIN-SCREENS                finance/views.py                who may read, certify, approve, pay
```

## The long-form entries

### `WO-TERMS` — `projects/bom_models.py`, `projects/po_service.py`, `projects/views.py`, `templates/projects/po_detail.html`
**Three terms on a work order — retention %, defect liability months, mobilisation advance —
read by every RA bill on it and by NOTHING in `PurchaseOrder.totals()`.** A purchase order for
cement carries no retention, and the order value printed on the PO must not move because a
field was added for contractors. The inputs sit under the ladder on the document screen, WO
only, draft only, in the same markup as the deduction and TDS inputs; approval freezes them, so
an approved bill's figures can never change because a term was edited afterwards.

**⚠ THESE HAVE DEFAULTS, UNLIKE THE DEDUCTION AND TDS.** The customer's rule: 10% retention on
every contractor bill, 12 months DLP, no advance unless agreed. Bounds are in
`update_draft_document`: retention 0–50, DLP 0–60, advance ≥ 0 and ≤ the order's taxable —
an advance larger than the work could never be recovered from the bills.

### `RA-BILL-OWNS-THE-WO` — `projects/po_service.py`
**Once a work order has an RA bill, its Completed and Paid steps belong to the finance module.**
`mark_delivered` and `mark_paid` refuse and name the RA bills screen. Approving the FINAL bill
sets `status=DELIVERED`, `delivered_at`, `delivered_by` — the same fields `mark_delivered` sets —
**without calling `record_full_delivery`**: the receipts are the CERTIFIED quantities, written
bill by bill, and a full-quantity receipt on top of them would double what the BOM shows. The
last payment sets PAID with `paid_at`/`paid_by`, the same fields `mark_paid` sets.

**⚠ THE IMPORT IS INSIDE THE FUNCTION.** finance imports projects; projects must not import
finance at module level or the two become a cycle.

### `FIN-MODEL` — `finance/models.py`
**An RA bill stores what a person typed — claimed and certified quantities — and frozen copies of
the rate, GST % and discount % from the work order line. It stores NO money.** Every rupee is
computed by `finance.calc` from those quantities and the order's terms, the way
`PurchaseOrder.totals()` computes the order. Cumulative certified, retention held, advance
recovered, paid to date are sums over rows, never a stored figure kept in step.

**⚠ TWO DOCUMENT FAMILIES, KEPT APART.** A WO is billed by RA bills, a PO by vendor invoices;
services refuse the cross. They share ONE `VendorPayment` register because the accountant keys
one register into Tally. `VendorInvoice` figures are the vendor's own, typed from paper; the
only rule is total = taxable + GST to the paisa. Its status (open / part-paid / settled) is
derived from payments, with TDS withheld counting towards settlement.

**⚠ `certified_qty` NULL ≠ 0.** Null is "not looked at"; the ladder uses the claim until then
and approval refuses a null. `sequence` is computed at creation and never renumbered — the
printed bill says "RA Bill No. 3".

### `FIN-CALC` — `finance/calc.py`
**The RA bill ladder, one implementation, `_money` half-up at every rung, in printed order:**

```
  gross            Σ qty × rate            certified qty once certified, the claim until then
- discount         Σ gross_line × disc%
= taxable          work done this bill, ex-GST
+ gst              Σ taxable_line × gst%   CGST/SGST halves by subtraction, as PO-TOTALS
= invoice_value    the contractor's invoice
- deduction        invoice_value × deduction%    POST-TAX — the same base as the order
- retention        taxable × retention%          ON THE WORK VALUE, EX-GST
- advance_recovery min(outstanding, taxable × advance ÷ order taxable); final bill: outstanding
± round_off        to the rupee, computed never stored
= payable          what we owe on this bill
- tds              taxable × tds%                 on the TAXABLE value, never on GST
= net_payable      what leaves the bank
```

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
final bill exists. Retention release refuses more than the balance and refuses before the DLP
unless `override=True` WITH a note; it writes a `RetentionRelease` AND a `VendorPayment` of kind
`retention_release`, because the money left the bank and the register goes to Tally. A PO turns
PAID when Σ payments ≥ its net payable and it is DELIVERED. Numbers `RA-` / `VB-` / `PV-` come
from `NumberSeries`, never from max().

### `FIN-SCREENS` — `finance/views.py`
**finance.view** reads everything; **finance.certify** raises bills, types certified quantities,
discards drafts; **finance.approve** approves bills and releases retention; **finance.pay**
records invoices and payments.

**⚠ TWO SCREENS OPEN TO view OR certify — `finance_wo` and `finance_ra_bill` — via
`requires_any`.** The site engineer holds certify and not view; the bill they certify must be a
screen they can open, and "a permission is only real if the role can reach the screen the
button is on" (PERMS-MATRIX). Used on those two READS only; every write behind them carries its
own single key, and tests prove Site is refused every register, the PDF and the PO screens.
The nav strip is hidden without finance.view so no tab leads to a 403.

**RA bill PDF is approved onwards only** (the PO-PDF rule). The Excel exports follow the
screen's filters; widths and formats are keyed off `headings`, never counted by hand.
