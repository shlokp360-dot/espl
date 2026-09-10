"""
The ⓘ panels for the sales screens, as data — the same shape as
`projects.help_panels.PANELS`, to be merged there by whoever owns that file.

>>> ANCHOR: INFO-PANELS <<<
Rules (tested by projects/test_info_panels.py once merged): an index label of
one or two words; 20–30 words a step; `[[…]]` only around a button or a field;
three or more steps; `perm=` on any step whose action needs a permission.
"""
from projects.panel_format import step

PANELS = {

    "sales_home": {
        "title": "The sales dashboard",
        "steps": [
            step("Read", "Start with the eight figures",
                 "Units available, booked and registered come from the bookings, never typed. "
                 "Collected is money received; outstanding is total payable less that; overdue is past due."),
            step("Projects", "Open a project from its row",
                 "Each row is one site. Click its code to reach the [[Units]] grid for that project, "
                 "with every unit, its status and who holds it."),
            step("Funnel", "Watch the funnel move",
                 "Enquiries by stage, newest to lost. Click a stage to list those enquiries. "
                 "Booked is set only by booking a unit, never by hand."),
            step("Enquiry", "Add an enquiry as it happens",
                 "Press [[Add enquiry]] the moment somebody asks. A name and a phone are enough; "
                 "the rest can be filled after the site visit.", perm="sales.edit"),
        ],
    },

    "sales_units": {
        "title": "The unit grid",
        "steps": [
            step("Pick", "Choose the project",
                 "The dropdown lists every Won project. The grid below groups its units by block and "
                 "floor, and the counts above it change with the project."),
            step("Status", "Read the status pill",
                 "Available means nobody holds it. Booked and Registered follow the live booking. "
                 "Cancelled means it was sold once and is for sale again."),
            step("Book", "Book an available unit",
                 "Press [[Book]] on an available or cancelled unit. The booking form opens with "
                 "the base price filled in and the default schedule ready.", perm="sales.edit"),
            step("Add", "Add units one at a time or in bulk",
                 "Press [[Add unit]] for one, or [[Add units in bulk]] to generate a whole block "
                 "from floors and units per floor.", perm="sales.edit"),
        ],
    },

    "sales_unit_form": {
        "title": "One unit",
        "steps": [
            step("Number", "Type the number as the brochure prints it",
                 "The [[Unit number]] is unique within the project — A-101 once and only once. "
                 "Block and floor are what the grid groups by."),
            step("Areas", "Fill both areas",
                 "[[Carpet sqft]] is what the customer walks on; [[Saleable sqft]] is what the "
                 "price is quoted on. Both print on the agreement later."),
            step("Price", "Base price is the whole unit, before GST",
                 "Type the price of the unit, not a rate per square foot. GST is added on every "
                 "demand at the booking's own percentage.", perm="sales.edit"),
            step("Withdraw", "Withdraw a unit rather than delete it",
                 "Set [[Active]] to No for a unit taken off the market. It stays on record "
                 "with its history and cannot be booked.", perm="sales.edit"),
        ],
    },

    "sales_units_bulk": {
        "title": "Adding a block of units",
        "steps": [
            step("Shape", "Describe the block",
                 "Type the [[Block]] letter, the [[First floor]], the [[Last floor]] and "
                 "[[Units per floor]]. Floors one to seven with four each makes twenty-eight units."),
            step("Numbers", "Numbers follow block-floor-position",
                 "A-101 is block A, floor one, first unit. The second unit on floor seven is A-702. "
                 "Leave the block blank for plain floor-position numbers."),
            step("Defaults", "Fill the areas and price once",
                 "Every generated unit gets the same type, areas and base price. Open any unit "
                 "afterwards to correct the ones that differ.", perm="sales.edit"),
            step("Repeat", "Running it twice is safe",
                 "A number that already exists is skipped, not overwritten, and the message says "
                 "how many were added and how many were left alone.", perm="sales.edit"),
        ],
    },

    "sales_enquiries": {
        "title": "Enquiries",
        "steps": [
            step("Filter", "Narrow the list",
                 "Choose a project, a stage or a person, or type part of a name, phone or broker "
                 "into the search box. Press [[Apply]] to filter."),
            step("Stages", "Read the stage pill",
                 "New has not visited yet. Visited and Negotiating are live. Booked has a booking "
                 "behind it. Lost carries the reason it was lost."),
            step("Open", "Open an enquiry to work on it",
                 "Click the name to add a site visit, change the stage, reassign it, or book "
                 "a unit straight from the enquiry.", perm="sales.edit"),
            step("Add", "Add a new enquiry",
                 "Press [[Add enquiry]]. A name and a phone are required; the source tells you "
                 "later which channels actually bring buyers.", perm="sales.edit"),
        ],
    },

    "sales_enquiry_form": {
        "title": "One enquiry",
        "steps": [
            step("Details", "Record who asked and what for",
                 "Type the [[Name]] and [[Phone]], choose the [[Source]] and what they are "
                 "interested in. The budget is ex-GST and optional.", perm="sales.edit"),
            step("Visit", "Add every site visit",
                 "Press [[Add site visit]] with the date. A New enquiry becomes Visited on the "
                 "first visit; later visits are counted on the list.", perm="sales.edit"),
            step("Stage", "Move the stage by hand when it changes",
                 "Choose the stage and press [[Change stage]]. Lost needs a reason. Booked cannot "
                 "be chosen here — booking a unit sets it.", perm="sales.edit"),
            step("Book", "Book a unit from here",
                 "The unit buttons open the booking form with this enquiry's name and phone "
                 "already filled in, and mark it Booked on saving.", perm="sales.edit"),
        ],
    },

    "sales_booking_new": {
        "title": "Booking a unit",
        "steps": [
            step("Customer", "Find the customer by phone",
                 "Type the [[Phone]] first. An existing customer is used as they are; a new "
                 "phone with a [[Name]] creates one. Names are never matched.", perm="sales.edit"),
            step("Value", "Agree the value before GST",
                 "[[Agreement value]] starts from the base price and can be negotiated. [[GST %]] "
                 "is five for ordinary flats and one for affordable housing.", perm="sales.edit"),
            step("Schedule", "Check the schedule adds to 100",
                 "Edit the milestone rows freely — names, percents, due dates. The total must be "
                 "exactly 100 or the booking is refused with the actual total.", perm="sales.edit"),
            step("Link", "Link milestones to header tasks",
                 "Choose a [[Linked header task]] for a slab milestone. When every subtask under "
                 "it is done, one press raises that demand on every booking.", perm="sales.edit"),
        ],
    },

    "sales_bookings": {
        "title": "The booking register",
        "steps": [
            step("Filter", "Narrow by project, status or text",
                 "Live hides cancelled bookings. Choose Everything to see them, or one status. "
                 "The search matches booking number, customer, phone or unit."),
            step("Money", "Read the five money columns",
                 "Agreement is ex-GST. Total adds GST. Collected is received including TDS. "
                 "Outstanding is total less collected. Overdue is unpaid past its due date."),
            step("Open", "Open a booking for the full picture",
                 "Click the booking number for the schedule, demand letters, receipts, the "
                 "customer's ledger and everything that has happened to it."),
        ],
    },

    "sales_booking": {
        "title": "One booking",
        "steps": [
            step("Ladder", "Read the value ladder",
                 "Agreement plus GST is the total payable. Demanded is what letters have asked for, "
                 "collected what came in, outstanding what remains overall."),
            step("Schedule", "Keep the schedule at 100",
                 "Edit names, percents, dates and linked headers, then press [[Save schedule]]. "
                 "A milestone with a demand letter keeps its name and percent.", perm="sales.edit"),
            step("Demand", "Raise a demand when a stage is reached",
                 "Press [[Raise demand]], choose the milestone and the due date. The amount and "
                 "GST are frozen on the letter from that moment.", perm="sales.collect"),
            step("Receipt", "Record every rupee received",
                 "Press [[Record receipt]]. Choose the demand it pays, or leave it on account. "
                 "Type the TDS the buyer deposited so the credit is complete.", perm="sales.collect"),
            step("Progress", "Mark the agreement and the registration",
                 "Press [[Mark agreement]] when the agreement is signed, [[Mark registered]] "
                 "when the deed is registered. A registered sale cannot be cancelled.", perm="sales.edit"),
            step("Cancel", "Cancel or transfer with care",
                 "[[Cancel booking]] shows the refund before asking you to confirm. [[Transfer]] "
                 "moves the sale to another customer and keeps the old one on record.", perm="sales.edit"),
        ],
    },

    "sales_booking_cancel": {
        "title": "Cancelling a booking",
        "steps": [
            step("Refund", "See the refund before confirming",
                 "Collected so far, less the deduction, is what goes back. Change the "
                 "[[Deduction %]] and press [[Recalculate refund]] to see the effect."),
            step("Reason", "Type the reason",
                 "The [[Reason]] is required and is kept on the booking's history. It is the "
                 "one thing anybody asks about a cancellation later.", perm="sales.edit"),
            step("Confirm", "Confirm, and the unit is for sale again",
                 "Press [[Confirm cancellation]]. The unit returns to the grid as Cancelled and "
                 "can be booked again. The refund is recorded, not paid.", perm="sales.edit"),
        ],
    },

    "sales_booking_transfer": {
        "title": "Transferring a booking",
        "steps": [
            step("Who", "Find the new customer by phone",
                 "Type the [[Phone]]. An existing customer is used; a new phone with a [[Name]] "
                 "creates one. The old customer stays on the booking's record."),
            step("Money", "Nothing on the money moves",
                 "Every demand letter and receipt stays on the booking. Only the name it is in "
                 "changes, and the ledger continues from the same balance."),
            step("Transfer", "Press Transfer",
                 "Press [[Transfer]]. The history row records who it came from, who it went to, "
                 "and the note you typed.", perm="sales.edit"),
        ],
    },

    "sales_customer_form": {
        "title": "One customer",
        "steps": [
            step("Phone", "The phone is the customer's identity",
                 "Two customers can never share a [[Phone]]. Correct a wrong number here; "
                 "every booking in their name follows automatically."),
            step("PAN", "Type the PAN before the agreement",
                 "[[PAN]] is ten characters, five letters, four digits, one letter. It prints on "
                 "the agreement and is needed for TDS.", perm="sales.edit"),
            step("Save", "Save and go back",
                 "Press [[Save customer]]. You return to the booking you came from, with the "
                 "corrected details already showing on the customer card.", perm="sales.edit"),
        ],
    },

    "sales_demand_new": {
        "title": "Raising a demand letter",
        "steps": [
            step("Milestone", "Choose the milestone that has been reached",
                 "The list shows only milestones with no letter yet, each with its amount. "
                 "The amount is the milestone's percent of the agreement value."),
            step("Ad hoc", "Or type an ad hoc amount",
                 "Choose the ad hoc option and type an [[Ad hoc amount]] ex-GST for something "
                 "outside the schedule. GST is added at the booking's rate.", perm="sales.collect"),
            step("Dates", "Set the dates",
                 "[[Raised on]] is the letter's date, [[Due on]] when payment is expected. "
                 "Ageing on the collections screen runs from the due date.", perm="sales.collect"),
            step("Raise", "Raise it, then download the PDF",
                 "Press [[Raise demand]]. The letter appears on the booking with a [[PDF]] "
                 "button. Its amount and GST never change after this.", perm="sales.collect"),
        ],
    },

    "sales_receipt_new": {
        "title": "Recording a receipt",
        "steps": [
            step("Against", "Choose what it pays",
                 "Pick the demand letter it settles, or leave it on account. An on-account "
                 "receipt is applied to the oldest open demand first."),
            step("Amount", "Type what reached the bank",
                 "[[Amount received]] is what arrived. If the buyer deposited TDS, type it in "
                 "[[TDS deposited by buyer]]; the customer is credited for both.", perm="sales.collect"),
            step("Reference", "Keep the reference",
                 "Choose the [[Mode]] and type the cheque number, UTR or UPI reference. "
                 "It is what the bank statement is matched against.", perm="sales.collect"),
            step("Record", "Record it",
                 "Press [[Record receipt]]. The demand's status, the ledger and every register "
                 "update from this one row; nothing is typed twice.", perm="sales.collect"),
        ],
    },

    "sales_collections": {
        "title": "Collections",
        "steps": [
            step("Ageing", "Read the ageing buckets",
                 "Not due is before the due date. The other four count days past it. The two "
                 "oldest buckets turn red when they hold money."),
            step("Filter", "Filter by project",
                 "Choose a project to see its open letters alone. The totals in the footer and "
                 "the buckets above follow the filter."),
            step("Stage", "Raise demands for a finished stage",
                 "With a project chosen, pick the finished header task and press "
                 "[[Raise linked demands]]. Bookings that already hold that letter are skipped.",
                 perm="sales.collect"),
            step("Excel", "Take it to Excel",
                 "Press [[Excel]] for the same rows with every money column summable, filtered "
                 "exactly as the screen is filtered at that moment."),
        ],
    },

    "sales_receipts": {
        "title": "The receipt register",
        "steps": [
            step("Range", "Set the date range",
                 "Type [[From]] and [[To]] dates and press [[Apply]]. Leave either blank for an "
                 "open end. Add a project or a mode to narrow further."),
            step("Columns", "Read the three money columns",
                 "Amount is what reached the bank. TDS is what the buyer deposited. Credited is "
                 "both together, the figure the customer's ledger carries."),
            step("Excel", "Download for the accountant",
                 "Press [[Excel]] for the filtered rows, one per receipt, every money column "
                 "summable and ready for the bank reconciliation."),
        ],
    },
}
