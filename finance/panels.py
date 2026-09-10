"""
The finance ⓘ panels, in the shape projects/help_panels.py enforces.

>>> ANCHOR: INFO-PANELS <<< (a reference to the existing anchor, not a new one)
Index label 1–2 words · 20–30 words a step · [[…]] only for a button or field ·
`perm=` on any step whose action needs a permission the reader might not hold.
"""
from projects.panel_format import step

PANELS = {

    "finance_home": {
        "title": "Finance overview",
        "steps": [
            step("Payable", "Read what is owed today",
                 "[[Payable now]] adds approved RA bills not yet paid and the open balance on "
                 "every vendor invoice. It is a question about today, not about a month."),
            step("Retention", "Watch the retention",
                 "[[Retention held]] is the balance held across work orders. [[Retention due]] "
                 "is the part whose defect liability period has ended and may be released."),
            step("Work orders", "Open a work order from the table",
                 "Each row is a work order with an open bill or retention held. Press its "
                 "number to see its lines, bills, retention and payments together."),
            step("DLP", "Plan the releases",
                 "The second table lists defect liability periods ending in the next ninety "
                 "days, so a release can be planned before the contractor asks for it."),
        ],
    },

    "finance_ra_bills": {
        "title": "RA bills",
        "steps": [
            step("Filter", "Narrow the register",
                 "Pick a project, a contractor or a status and press [[Filter]]. Every figure in "
                 "the table comes from the bill's own ladder, the one printed on its PDF."),
            step("Open", "Open a bill or its work order",
                 "Press the RA bill number to open the bill, or the work order number to see "
                 "every bill on that contract with its retention and advance position."),
            step("Excel", "Export what is on screen",
                 "[[Excel]] downloads exactly the filtered rows: one sheet per bill with the "
                 "full ladder, and a second sheet with one row per certified line."),
        ],
    },

    "finance_wo": {
        "title": "A work order's bills",
        "steps": [
            step("Lines", "Check what is left to certify",
                 "Every contract line shows the order quantity, what earlier approved bills "
                 "certified, and what remains. Nothing here can be certified past the order."),
            step("New bill", "Raise the contractor's claim",
                 "Type the claimed quantity on each line the contractor billed, set the date "
                 "and their invoice number, tick final on the closing bill, press [[New RA bill]].",
                 perm="finance.certify"),
            step("Ledgers", "Read retention, advance and payments",
                 "Retention is held on every approved bill and released here after the DLP. "
                 "The advance shows agreed, paid and recovered side by side, so a gap is visible."),
            step("Release", "Release retention after the DLP",
                 "Once the defect liability period has ended, type the amount and reference and "
                 "press [[Release retention]]. Before that date only an override with a note works.",
                 perm="finance.approve"),
        ],
    },

    "finance_ra_bill": {
        "title": "An RA bill",
        "steps": [
            step("Certify", "Type the certified quantities",
                 "Write what our engineer measured in [[Certified]] on every line, zero if nothing "
                 "was done, and press [[Certify]]. The money follows the certified figure.",
                 perm="finance.certify"),
            step("Ladder", "Read the ladder",
                 "Retention comes off the basic value, the deduction off the amount after GST, "
                 "the advance pro rata to work done, and TDS off the basic value at the end."),
            step("Approve", "Approve and lock",
                 "[[Approve & lock]] records the certified quantities as received on the BOM and "
                 "locks the bill. On a final bill it also marks the work order completed.",
                 perm="finance.approve"),
            step("Pay", "Record the payment",
                 "[[Record payment]] takes what left the bank and the TDS withheld. Part payments "
                 "are fine; the bill turns Paid when the payments reach its net payable.",
                 perm="finance.pay"),
            step("PDF", "Download the certificate",
                 "The [[PDF]] button appears once the bill is approved. An open bill is a claim "
                 "still under discussion and never prints as a document.", perm="finance.view"),
        ],
    },

    "finance_ra_bill_pay": {
        "title": "Paying an RA bill",
        "steps": [
            step("Amount", "Type what left the bank",
                 "[[Amount paid]] is the money transferred, already net of TDS. It is filled with "
                 "what is left to pay; type less for a part payment, never more."),
            step("TDS", "Record the TDS withheld",
                 "[[TDS withheld]] is filled from the bill's ladder. Change it only if the "
                 "accountant deducted a different figure; it is what goes to the department."),
            step("Reference", "Add the bank reference",
                 "Pick the [[Mode]] and type the UTR or cheque number in [[Reference]], then press "
                 "[[Record payment]]. This row is what the Tally export carries."),
        ],
    },

    "finance_ra_bill_discard": {
        "title": "Discarding a bill",
        "steps": [
            step("Check", "Make sure it is the right bill",
                 "Only a draft or certified bill can be discarded. An approved bill is locked, "
                 "has receipts on the BOM, and stays on the register forever."),
            step("Discard", "Throw the claim away",
                 "[[Discard]] deletes the claim and its certified quantities. Nothing was recorded "
                 "against the BOM, so nothing needs undoing. The number is not reused."),
            step("Keep", "Or go back",
                 "[[Keep it]] returns to the bill unchanged. Discarding is for a claim raised in "
                 "error; a wrong quantity is corrected on the bill itself."),
        ],
    },

    "finance_retention": {
        "title": "Retention",
        "steps": [
            step("Held", "Read what is held",
                 "Retention is held at the work order's percentage on the basic value of every "
                 "approved RA bill. The balance is what is held less what has been released."),
            step("DLP", "Watch the defect liability period",
                 "The DLP runs from the final bill's approval for the months agreed on the work "
                 "order. [[Eligible]] means it has ended and a balance is still held."),
            step("Release", "Release from the work order",
                 "Press the work order number and use [[Release retention]] on that screen. This "
                 "register only reads; the release is recorded where the ledger lives."),
        ],
    },

    "finance_invoices": {
        "title": "Vendor invoices",
        "steps": [
            step("Filter", "Narrow the register",
                 "Pick a project, a vendor or a status and press [[Filter]]. Open means nothing "
                 "applied yet, part-paid something, settled the whole total including TDS."),
            step("Open", "Open the purchase order",
                 "Press the purchase order number to see the order's value against what was "
                 "invoiced and paid, and to record another invoice or a payment."),
            step("Figures", "Read whose figures these are",
                 "Taxable, GST and total are what the vendor's paper says, typed in. Whether they "
                 "match our order is shown on the purchase order's settlement screen."),
        ],
    },

    "finance_po": {
        "title": "A purchase order's settlement",
        "steps": [
            step("Order", "Read the order's own figures",
                 "Order value, TDS and net payable come from the purchase order's ladder, the one "
                 "printed on its PDF. Balance to pay is net payable less everything paid."),
            step("Invoice", "Record the vendor's invoice",
                 "[[Record invoice]] takes the vendor's invoice number, date and their three "
                 "figures. The total must equal taxable plus GST to the paisa.",
                 perm="finance.pay"),
            step("Pay", "Record money out",
                 "[[Record payment]] applies money to an invoice; [[Record advance]] records money "
                 "before any invoice. Once delivered and fully paid, the order turns Paid.",
                 perm="finance.pay"),
            step("Flag", "Watch the red pill",
                 "[[Invoiced more than ordered]] appears when the invoices total more than the "
                 "order value. Nothing is refused; somebody has to look at it."),
        ],
    },

    "finance_invoice_new": {
        "title": "Recording an invoice",
        "steps": [
            step("Number", "Copy the vendor's number",
                 "[[Vendor's invoice number]] is theirs, exactly as printed, and it is checked "
                 "against earlier invoices from the same vendor so nothing is recorded twice."),
            step("Figures", "Type their three figures",
                 "[[Taxable]], [[GST]] and [[Total]] are the vendor's own figures. The total must "
                 "equal taxable plus GST to the paisa, or the invoice is refused."),
            step("Save", "Record it",
                 "Press [[Record invoice]]. Our reference VB-number is given automatically and "
                 "the invoice appears as open until a payment is applied to it."),
        ],
    },

    "finance_po_pay": {
        "title": "Paying a purchase order",
        "steps": [
            step("Kind", "Choose what this money is",
                 "[[Kind]] is against an invoice, which then needs the [[Invoice]] picked, or an "
                 "advance paid before any invoice arrived. Both reach the payments register."),
            step("Amount", "Type what left the bank",
                 "[[Amount paid]] is the transfer itself and [[TDS withheld]] what was deducted. "
                 "Together they may not exceed what is left on the chosen invoice."),
            step("Reference", "Add the bank reference",
                 "Pick the [[Mode]], type the UTR or cheque number in [[Reference]] and press "
                 "[[Record payment]]. The order turns Paid once delivered and fully paid."),
        ],
    },

    "finance_payments": {
        "title": "Payments register",
        "steps": [
            step("Range", "Pick the dates",
                 "The register opens on the current month. Change the two dates, a project, a "
                 "vendor or a kind and press [[Filter]]. Totals follow the selection."),
            step("Read", "Read a row",
                 "Amount is what left the bank; TDS is what was withheld. Document names the RA "
                 "bill, the vendor invoice or the order the money was applied to."),
            step("Tally", "Export for Tally",
                 "[[Excel for Tally]] downloads exactly the rows on screen with date, PV number, "
                 "vendor, GSTIN, project, document, kind, amount, TDS, mode and reference."),
        ],
    },
}
