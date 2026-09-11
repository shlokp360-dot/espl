# What Farvision's Financials and P2P do that this module does not — and whether it matters here

*Written 11 Sep 2026, after the Finance & Accounting rework (bills register, vendor ledger, TDS
report, retention switched off). Read against `farvision-developer-contractor.md`.*

Farvision's Financials module is a full general ledger: every module posts to one set of books,
and the P2P chain runs indent, RFQ, PO, GRN, three-way match, AP and payment. This module is
deliberately narrower. It records what was ordered, what was billed against it, what was paid and
what was withheld, and hands the accountant the two files she actually keys into Tally — the
payments register and the vendor ledger. Everything below is a gap between the two, described one
at a time with a view on whether a builder of this size — one office, a handful of live sites, an
outside CA, Tally already in place — gets anything for the work.

**Three-way match with GRN quantities.** Farvision matches the PO quantity, the received quantity
and the invoiced quantity line by line and holds the bill until they agree. Here the match is at
amount level only: `po_settlement` flags an order invoiced for more than its value, and a vendor
invoice carries no quantities. The quantity side already exists on the receiving end — `Receipt`
rows are written per line, and an RA bill is certified per line — so the missing piece is an
invoice that lists lines. That is a real change to `VendorInvoice` and to the recording form, and
it is worth doing only once somebody is actually being over-billed on quantity rather than on
price. For steel, cement and sand it will happen; for a finishing contractor's WO it cannot,
because the RA bill is the match. Worth building, second-stage, and only for POs.

**Debit notes and credit notes.** A vendor who over-invoiced, delivered short, or was charged for
breakages needs an adjustment that is not a payment and not a new bill. Today the only way to
correct an invoice is to leave it part-paid forever, which is honest but reads as an open
liability on every register and in the ageing. A `VendorNote` of two kinds, applied against a bill
in the same way a payment is, would close the gap in one model and one form. Small, and it will
be asked for within the first quarter of real use. Worth building early.

**Advances adjusted against bills.** On the work-order side this is done: the mobilisation
advance is recovered pro rata on each RA bill by the agreed term, and the vendor ledger shows the
advance as a negative balance until the bills clear it. On the PO side an advance is recorded but
never applied — the invoice stays open and the ledger nets it only in the running balance. A
one-line "apply this advance to this invoice" that writes an allocation row would make the bills
register agree with the ledger. Cheap; worth doing with the debit-note work since it is the same
shape of write.

**GST input credit register.** Farvision produces GSTR-2 style data: for every purchase invoice,
the GSTIN, the invoice number and date, the taxable value, CGST/SGST/IGST and whether the credit
is eligible. Every field is already stored here except the tax split and the eligibility flag — a
vendor invoice holds one GST figure, and interstate is derived from the two GSTINs rather than
recorded. Adding the split at recording time and an export in the CA's column order is a day's
work. The value depends entirely on whether the CA reconciles input credit from Tally or from
this system; today it is Tally, which already has the vouchers keyed from the payments export.
Worth building only if the CA asks for it, and then as an export, never as a filing.

**Bank reconciliation.** Matching bank statement lines to payment vouchers by UTR and amount. The
`VendorPayment` row carries reference, mode and date, so a statement import that ticks off
matches is feasible. But Tally does bank reconciliation, the accountant already does it there, and
a second reconciliation is a second thing to disagree. Not worth building for a business of this
size; the payments export is the deliverable.

**E-invoicing and IRN.** This applies to the sales side — the invoices this business issues, not
the ones it receives — and to a turnover threshold that a builder of this size may or may not
cross. On the purchase side the only obligation is to record the vendor's IRN when their invoice
carries one, which is a text field on `VendorInvoice`. Add the field when a vendor's invoice
first shows one; do not build the IRN generation, which belongs with the sales module if it is
ever needed, and more likely with the CA's software.

**General ledger posting to Tally via export.** Farvision is its own ledger and posts every
transaction. This module will never be the ledger; the decision that Tally is the book of account
was made before it was written. What Tally needs is vouchers it can import: a purchase voucher
per bill (vendor credit, expense and GST debits, project as cost centre) and a payment voucher per
payment (vendor debit, bank credit, TDS payable credit). The payments register is already that
second voucher in spreadsheet form, and the new vendor ledger proves the running balance ties.
The next step is a Tally XML export of both voucher types, so the accountant imports instead of
keys. This is the single highest-value item on this list, because it removes the double entry
that produces every reconciliation difference. Worth building first.

**Customer-side receivables merged with sales.** Farvision runs AR beside AP so the project P&L
and the cash forecast see both sides. Here the sales module already holds demands, receipts and
customer ledgers, computed by its own `sales.calc`, and the two modules do not share a screen. A
merged cash view — money due in from customers against money due out to vendors over the next
30/60/90 days — is a reporting page over two existing calc modules, not a new model. Useful to
the owner, cheap to build once both sides have a few months of data, and it should live in
analytics, not here.

**The order.** Tally voucher export first, because it removes work the accountant does every
week. Debit and credit notes with advance application second, because the first real correction
will need them and the shape is small. Quantity three-way match third, once a supplier's
over-billing is a real event rather than a feared one. The GST input register when the CA asks.
The cash view across sales and finance when both modules have history. Bank reconciliation and
IRN generation not at all — Tally and the CA's tools already do them, and doing them twice is how
two numbers stop agreeing.
