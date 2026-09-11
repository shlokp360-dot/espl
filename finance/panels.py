"""
The finance ⓘ panels, in the shape projects/help_panels.py enforces.

>>> ANCHOR: INFO-PANELS <<< (a reference to the existing anchor, not a new one)
Index label 1–2 words · 20–30 words a step · [[…]] only for a button or field ·
`perm=` on any step whose action needs a permission the reader might not hold.
"""
from projects.panel_format import step

PANELS = {

    "finance_home": {
        "title": "Finance & Accounting overview",
        "steps": [
            step("Payable", "Read what is owed today",
                 "[[Bills payable now]] adds the open balance on every vendor invoice and every "
                 "approved RA bill. [[Overdue]] is the part whose due date has already passed."),
            step("Due date", "Know where a due date comes from",
                 "A bill falls due its vendor's credit days after the bill date, read from the "
                 "vendor's payment terms. A vendor with no number there is given thirty days."),
            step("Ageing", "Read the two tables",
                 "Ageing groups open bills by how old they are. Cash out groups them by when "
                 "they fall due, so the bank account can be planned thirty days ahead."),
            step("Vendors", "Follow a vendor",
                 "The last table ranks vendors by open balance. [[ledger]] opens the running "
                 "account the accountant reconciles with Tally; [[bills]] lists the open ones."),
            step("Project", "Narrow to one project",
                 "Pick a project and press [[Filter]]. Every figure follows it, and the tabs "
                 "Bills and RA bills open on the same project until you clear it."),
        ],
    },

    "finance_ra_bills": {
        "title": "RA bills",
        "steps": [
            step("Project", "Start from the project",
                 "The first control lists every Won project. Pick one and press [[Filter]]; the "
                 "tab strip remembers it, so Bills and Overview open on the same project."),
            step("Narrow", "Add a contractor or a status",
                 "A contractor or a status narrows the list further. Every figure in the table "
                 "comes from the bill's own ladder, the one printed on its PDF."),
            step("Subtotal", "Read the project line",
                 "With a project chosen the last row adds its approved and paid bills: certified "
                 "to date, billed, paid and the balance still to pay on this project."),
            step("Open", "Open a bill or its work order",
                 "Press the RA bill number to open the bill, or the work order number to see "
                 "every bill on that contract with its advance position and payments."),
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
            step("Advance", "Read the advance position",
                 "The advance card shows agreed, paid and recovered side by side, so a gap is "
                 "visible. Recovery follows the agreed term on each bill, never the payments."),
            step("Payments", "Read the payments table",
                 "Every payment on this contract is listed with its bill, reference and TDS. "
                 "Paid to date is their sum; a payment is recorded from the bill itself."),
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
                 "The deduction comes off the amount after GST, the advance pro rata to the "
                 "work done, and TDS off the basic value at the end. Retention is not held."),
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



    "finance_bills": {
        "title": "Bills",
        "steps": [
            step("Rows", "Read what a row is",
                 "One row per vendor bill against a document: a VB- invoice on a purchase order "
                 "or an RA- bill on a work order, once approved. Drafts are not bills yet."),
            step("Filter", "Narrow the register",
                 "Pick a project, a vendor, PO or WO, a status or a date range and press "
                 "[[Filter]]. Open means nothing applied, part-paid something, settled the whole."),
            step("Figures", "Read the money columns",
                 "Amount is the bill as the vendor wrote it. TDS on an RA bill is the bill's own, "
                 "on an invoice what the payments withheld. Balance is still to pay."),
            step("Record", "Record a vendor's bill",
                 "Press [[Record a bill]], pick the purchase order it is against, then type the "
                 "vendor's number, date and three figures. RA bills are raised from the work order.",
                 perm="finance.pay"),
            step("Excel", "Export what is on screen",
                 "[[Excel]] downloads exactly the filtered rows with the document, vendor, GSTIN, "
                 "dates, status and every money column, ready to filter and add up."),
        ],
    },

    "finance_bill_pick": {
        "title": "Record a bill",
        "steps": [
            step("Pick", "Find the purchase order",
                 "Every approved purchase order is listed by project with what has been invoiced "
                 "and paid on it. Narrow by project with [[Filter]] if the list is long."),
            step("Go", "Open the form",
                 "Press [[Record bill on]] beside the order. The next screen takes the vendor's "
                 "invoice number, date, taxable, GST and total, and checks the arithmetic."),
            step("Work orders", "Know what is not here",
                 "A work order is billed through RA bills, raised from the work order's own "
                 "screen and certified before approval, so it does not appear in this list."),
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

    "finance_vendor_ledger": {
        "title": "Vendor ledger",
        "steps": [
            step("Pick", "Choose the vendor",
                 "Pick a vendor and press [[Open ledger]]. Two dates narrow it; everything before "
                 "the first date is folded into the opening balance line at the top."),
            step("Rows", "Read the three kinds of row",
                 "An order row shows the order value and moves nothing. A bill row adds what we "
                 "owe. A payment row takes off the amount paid and the TDS withheld."),
            step("Balance", "Read the running balance",
                 "Balance is bills less payments and TDS, running down the page. A negative "
                 "figure means an advance not yet recovered by bills. Zero means fully settled."),
            step("Tally", "Reconcile with Tally",
                 "[[Excel for Tally]] downloads the ledger with opening and closing lines. Compare "
                 "the closing balance with the vendor's account in Tally; a difference is a missing entry."),
        ],
    },

    "finance_tds": {
        "title": "TDS report",
        "steps": [
            step("Quarter", "Pick the quarter",
                 "Quarters run April to March, as the CA files. Pick one and press [[Show quarter]]; "
                 "every payment dated inside it is counted, whichever bill it settled."),
            step("Rows", "Read a row",
                 "One row per vendor and section, grouped by section with a subtotal. Rate is the "
                 "order's TDS rate; TDS is what the payments withheld; Paid is what left the bank."),
            step("Base", "Read the taxable base",
                 "The base is the bill's basic value in the proportion this payment settled. An "
                 "advance with no bill is its own base. Paid plus TDS is the gross credited."),
            step("Excel", "Export for 26Q",
                 "[[Excel for 26Q]] downloads the rows with section, vendor, GSTIN, rate, base, "
                 "gross, TDS and paid. The CA fills the return from it; nothing is filed from here."),
        ],
    },
}
