"""
The ⓘ panels, as data.

>>> ANCHOR: INFO-PANELS <<<
Points 4, 5 and 6 of Saahil's review, and the last of it.

⚠⚠ THEY CHANGED IN KIND, NOT ONLY IN WORDING. The old panels explained WHY a
   screen is designed the way it is — about 4,500 words of reasoning across
   seventeen screens. They now say WHAT TO DO on it, numbered, task first. His
   words: the ⓘ should be "instructions". Reasoning did not disappear; it moved
   to ANCHORS.md and to the code, where the person changing something reads it.
   Nobody standing at a site office needs to know why a rule exists in order to
   follow it.

⚠⚠ AS DATA, NOT AS THIRTY-NINE HAND-WRITTEN DIALOGS, and that is the decision
   worth defending. The same reasoning as the launchpad's tiles and the master
   tab strip:

     - The FORMAT cannot drift. Twenty-odd templates each carrying their own
       markup is twenty-odd chances for one of them to grow a different heading
       size, lose its index, or start using bold for emphasis.
     - The INDEX writes itself from the step labels, so it can never fall out of
       step with the steps below it.
     - THE RULES ARE TESTABLE. A panel with a step of sixty words, or bold used
       for emphasis, is caught by a test rather than by reading.
     - THE GUJARATI IS ONE FIELD PER STEP. Every panel gains a translation
       without a single template being touched again, which is the difference
       between a mechanical pass and thirty-nine more edits.

⚠ THE THREE CONVENTIONS, LOCKED, from the sample he approved:
     1. The index is one line of SHORT LABELS, not sentences.
     2. 20–30 words a step. Long enough to be an instruction, short enough that
        somebody standing at a desk reads it.
     3. **BOLD IS ONLY EVER A BUTTON OR A FIELD NAME** — never emphasis. Anything
        bold on a panel is something you can point at on the screen. That is why
        the markup below is `[[Order Qty]]` rather than `<b>`: the syntax is
        named for what it is allowed to mean, so it cannot be misused by habit.

⚠ SCREEN LABELS STAY ENGLISH. Only the panel is bilingual. Translating the
  buttons would mean two vocabularies in one room the first time somebody reads
  a screen over somebody else's shoulder.

⚠ THE GUJARATI IS WRITTEN BY CLAUDE AND MUST BE CHECKED BY THEIR OWN PEOPLE
  before it ships — the same rule as the compliance checklist. `gu` is empty
  until then, and the toggle only appears on a panel that has one.
"""

# A step is:
#   label — the short word for the index. One or two words, no sentence.
#   head  — the instruction as a heading. Imperative where it can be.
#   text  — 20–30 words. [[…]] marks a button or field name and nothing else.
#   gu    — the same text in Gujarati, or "" until their people have checked it.
#   perm  — the permission key the step's action needs, or None for everybody.
#
# ⚠⚠ `perm` IS THE TILE RULE, APPLIED TO INSTRUCTIONS. A tile can never lead to
#    a 403 and neither can a tab; a step telling somebody to press a button they
#    do not have is the same fault in a quieter voice. A site engineer reads the
#    board and cannot add to it, so the reading steps are theirs and the adding
#    steps are not. Caught by an existing test, which asserted "Add milestone"
#    was absent from the page for that role — it was, until the panel said it.
#
# ⚠ THE NUMBERING FOLLOWS WHAT IS SHOWN. Steps are numbered after filtering, so
#   nobody sees 1, 2, 5 and wonders what they are missing.


def step(label, head, text, gu="", perm=None):
    return {"label": label, "head": head, "text": text, "gu": gu, "perm": perm}


PANELS = {

    # ------------------------------------------------------------ the launchpad
    "launchpad": {
        "title": "Getting around",
        "steps": [
            step("Start", "Pick what you are doing",
                 "Every tile here opens one job. You only see the tiles your role "
                 "can open, so nothing on this screen can refuse you."),
            step("Projects", "Work on one site",
                 "Open [[Projects]], choose the site, and its own tabs appear — "
                 "estimate, materials, orders and compliance for that site alone."),
            step("Masters", "Set up the lists everything uses",
                 "[[Master data]] holds materials, vendors, construction activities "
                 "and your company details. Set these up once; every project reads them."),
            step("Trouble", "If a screen refuses you",
                 "A tile you cannot open is never shown. If you reach a refusal, your "
                 "role does not include it — ask an administrator on the [[Users]] screen."),
        ],
    },

    # ------------------------------------------------------------- master data
    "master_data": {
        "title": "Using master data",
        "steps": [
            step("Order", "Set these up before quoting",
                 "A project reads all of these. Add construction activities first, "
                 "then materials and vendors, then your company details."),
            step("Add", "Add a row at the bottom",
                 "Groups, units and rates are edited in place. The last row of each "
                 "table is blank — type in it and press [[Save]] to add one."),
            step("Retire", "Turn off what you stopped using",
                 "Nothing here is deleted, because documents refer to it. Untick "
                 "[[Active]] instead and it stops being offered on new records."),
            step("Excel", "Bulk edit in a spreadsheet",
                 "On materials and vendors, press [[⤓ Download these]] to get what is "
                 "on screen, edit it, and upload the same file back."),
        ],
    },

    # -------------------------------------------------------------------- BOM
    "bom": {
        "title": "Ordering from the bill of materials",
        "steps": [
            step("Quantity", "Type what you want to order",
                 "Type into [[Order Qty]]. It starts empty on every line and an empty "
                 "box orders nothing, so nothing is ever ordered by accident."),
            step("Suggestion", "Use the suggested figure, or do not",
                 "The grey figure under the box is what is still to buy. Press "
                 "[[use]] to copy it in. It is advice and never fills itself in."),
            step("Vendor", "Name who you are buying from",
                 "Choose a [[Vendor]] on every line you want ordered. A line with no "
                 "vendor raises no order and is listed by name on the preview."),
            step("Rate", "Check the rate before you commit",
                 "The grey figure in [[Vend Rate]] is what you last paid this vendor "
                 "for this material. Leave it blank to use it, or type over it."),
            step("Preview", "See the orders before they exist",
                 "Press [[Post POs]]. It writes nothing — it shows every order that "
                 "would be raised, vendor by vendor, with quantities and totals."),
            step("Create", "Tick the vendors you want",
                 "On the preview, tick the vendors to order from and press [[Create]]. "
                 "Only then does a purchase order exist, as a draft."),
            step("Stock", "Keep site stock up to date",
                 "[[Stock]] is what is lying on site and it is subtracted from what is "
                 "still to buy. [[Min]] flags a material when stock runs low."),
            step("Locked", "What you cannot type here",
                 "[[Approved]], [[In Draft]] and [[Received]] are added up from the "
                 "purchase orders each time this page opens, so they cannot disagree."),
        ],
    },

    # -------------------------------------------------------------------- BOQ
    "boq": {
        "title": "Building an estimate",
        "steps": [
            step("Add", "Put the construction activities on the quote",
                 "Tick the activities this job includes at the bottom of the screen "
                 "and press [[Add ticked]]. Each arrives at your company rate."),
            step("Rates", "Change a rate for this job",
                 "Type over [[Rate ₹/sqft]] on any line. This changes the quote in "
                 "front of you only; the company rate in master data is untouched."),
            step("Factors", "Add contingency, design fee and GST",
                 "Type the three percentages at the foot of the screen. The cards at "
                 "the top move as you type, before you press [[Save estimate]]."),
            step("Save", "Save before leaving",
                 "The cards update as you type but nothing is stored until you press "
                 "[[Save estimate]]. Leaving the screen loses what you typed."),
            step("Excluded", "Check what is not quoted",
                 "The list at the bottom is every activity not on this quote. Anything "
                 "bought under one of those later has no budget to measure against."),
            step("Locked", "Once the project is Won",
                 "The estimate locks when the project becomes Won, for everybody. It "
                 "is what every budget on the job is measured against from then on."),
        ],
    },

    # ------------------------------------------------------------ the task board
    "board": {
        "title": "Planning the work",
        "steps": [
            step("Milestone", "Add a milestone first",
                 "Press [[Add milestone]]. Give it a name people use on site, a "
                 "construction activity, a start date and a number of days.", perm="tasks.manage"),
            step("Tasks", "Add the work under it",
                 "Press [[Add task]], choose the milestone, and assign it to one "
                 "person. The finish date is worked out from the start and the days.", perm="tasks.manage"),
            step("Ticking", "Only the assignee marks it done",
                 "Whoever the task is assigned to ticks it on [[My work]]. Nobody "
                 "else can, and a manager cannot do it for them."),
            step("Late", "A late tick needs a reason",
                 "If the finish date has passed, the person ticking chooses a reason "
                 "from the list. On-time work is never asked for one."),
            step("Moving", "Move several dates at once",
                 "Tick the rows, type the number of days, choose a reason and press "
                 "[[Shift]]. The first promised date is kept and stays visible.", perm="tasks.manage"),
            step("Delete", "Remove a row that should not exist",
                 "Press [[Delete]] on the task. It cannot be undone, and a late task "
                 "takes its days out of the delay log with it.", perm="tasks.manage"),
        ],
    },

    # ----------------------------------------------------------------- my work
    "my_work": {
        "title": "Your own work",
        "steps": [
            step("Yours", "Everything assigned to you",
                 "Every task on every site that is yours, soonest first. The board "
                 "shows one project's whole plan; this shows only your rows."),
            step("Done", "Tick it the day it is finished",
                 "Press [[Done]]. Today's date is recorded — you cannot type a "
                 "different one, so the record cannot be tidied up afterwards."),
            step("Reason", "If it is late, say why",
                 "A task finished after its date asks for a reason from a fixed list. "
                 "The list is what lets a year of delays be counted."),
            step("Blocked", "Say when you cannot proceed",
                 "Press [[Blocked]] and say what is stopping you. The date does not "
                 "move and the task keeps counting overdue, because it is."),
        ],
    },

    # ---------------------------------------------------------------- schedule
    "schedule": {
        "title": "Reading the schedule",
        "steps": [
            step("Bars", "What a bar shows",
                 "Each bar is the span a task was planned for. A second segment in a "
                 "different colour is the time it ran past that date."),
            step("Colours", "Red and amber are different warnings",
                 "Red means a task finished late, or is open and overdue. Amber means "
                 "the plan no longer fits the window — nothing has slipped yet."),
            step("Milestones", "The dotted lines",
                 "Each dotted line is a milestone, drawn at the date its work actually "
                 "finishes. It moves when a task under it slips."),
            step("Scrolling", "Long projects scroll sideways",
                 "A month is the same width whatever the length of the job. Scroll "
                 "sideways; the task names stay fixed on the left."),
            step("Reasons", "Why something ran over",
                 "The chart carries the difference, never the words. The reason for "
                 "every delay is on the [[Delay log]] tab."),
        ],
    },

    # ----------------------------------------------------------- purchase orders
    "po_register": {
        "title": "Finding a purchase order",
        "steps": [
            step("Search", "Narrow the list",
                 "Search by number, vendor or material, and filter by status, "
                 "document type or construction activity. The filters combine."),
            step("Status", "What each status means",
                 "[[Draft]] is not yet committed and can be changed. [[Approved]] is "
                 "issued and locked. [[Delivered]] arrived; [[Paid]] left the bank."),
            step("Unpaid", "See what is still owed",
                 "The [[not paid yet]] shortcut shows everything approved or "
                 "delivered but not yet paid — what the business still owes."),
            step("Open", "Look at one document",
                 "Press [[open ▸]]. Arriving from here you see the document alone; "
                 "arriving through a project you also get that project's tabs."),
        ],
    },

    "po_detail": {
        "title": "Working with one order",
        "steps": [
            step("Draft", "Change it while it is a draft",
                 "Quantities, rates, terms and the delivery address can be edited "
                 "only while the status is [[Draft]]. Nothing else can be."),
            step("Approve", "Issue it to the vendor",
                 "Press [[Approve]]. The document locks permanently, and the rate on "
                 "each line is recorded against that vendor for next time."),
            step("GSTIN", "A GST number is required first",
                 "Approval refuses without the vendor's GSTIN. Type it once and it is "
                 "saved to the vendor master, never asked for again."),
            step("Delivery", "Record what arrived",
                 "Press [[Mark delivered]] and enter what was received. Short "
                 "deliveries are recorded as they were, not as they were ordered."),
            step("Payment", "Record the money going out",
                 "Press [[Mark paid]] once payment leaves. Only then does this order "
                 "count as spend on the analytics screens."),
            step("Print", "Send it to the vendor",
                 "Press [[Download PDF]] for the signed-off document. Only the "
                 "approval date prints — no names appear on it."),
        ],
    },

    # ---------------------------------------------------------------- compliance
    "compliance_project": {
        "title": "One project's compliance file",
        "steps": [
            step("Regimes", "Say which regimes apply",
                 "AMC applies to every site. Tick [[Turn on]] against RERA or any "
                 "other optional regime and its checklist loads underneath.", perm="compliance.upload"),
            step("Upload", "File a document against a line",
                 "Press [[Upload]] on the line and choose the file. Type the expiry "
                 "date from the paper itself — the suggestion is only a suggestion.", perm="compliance.upload"),
            step("Versions", "Nothing is ever overwritten",
                 "Press [[Replace]] and the new document becomes the current one, "
                 "while every earlier version stays underneath it, dated and still "
                 "downloadable.", perm="compliance.upload"),
            step("Correct", "Fix a typo without a new file",
                 "[[Correct details]] changes the reference or the dates typed beside "
                 "a document. Use [[Replace]] when the paper itself changed.", perm="compliance.upload"),
            step("Prune", "Drop a line this site does not need",
                 "Press [[Not needed here]]. It goes from this project only; the "
                 "master and every other project keep it. Put it back at any time.", perm="compliance.master"),
            step("Status", "What the colours mean",
                 "Status is worked out from what is held, never typed. Only "
                 "compulsory lines count towards the attention figure at the top."),
        ],
    },

    "compliance_overview": {
        "title": "Where the gaps are",
        "steps": [
            step("Read", "Every site against every regime",
                 "One row per project, worst first. The number in each column is "
                 "how many compulsory lines that site has not yet satisfied."),
            step("Attention", "What the figure counts",
                 "Only compulsory lines that are missing, expired or expiring. Good "
                 "practice documents are tracked but never counted against a site."),
            step("Open", "Go to the file itself",
                 "Press the project name to open its compliance file, where the "
                 "documents are uploaded and the individual lines are listed."),
            step("Missing", "A site showing nothing",
                 "A project with no regimes ticked shows no rows. Open it and turn "
                 "on the ones that apply — AMC is always on."),
        ],
    },

    "compliance_timeline": {
        "title": "What expires, and when",
        "steps": [
            step("Order", "Expired first, never dropped",
                 "Everything with a validity, across every site, in date order. "
                 "Expired documents stay at the top rather than falling off the list."),
            step("Current", "Only the latest version counts",
                 "A certificate replaced last month is not a problem and is not "
                 "listed. Only the current version of each line appears here."),
            step("Act", "Renew before the date",
                 "Press [[Download]] to see the paper, then upload the renewal on "
                 "that project's compliance screen. The new one becomes current."),
        ],
    },

    "compliance_master": {
        "title": "Changing the checklist",
        "steps": [
            step("Shape", "Type, title, then line",
                 "A regime holds titles, and a title holds the lines documents are "
                 "filed against. Add them in that order, top down."),
            step("Add", "Add a line to the checklist",
                 "Press [[New line item]]. It lands on every project the regime "
                 "applies to, and the dialog says how many before you save."),
            step("Reach", "Everywhere, or one site",
                 "Leave the project empty and the line applies to every site. Set "
                 "one and it exists on that site alone — a condition on one plot."),
            step("Retire", "Take a line out of use",
                 "Press [[Deactivate]] and it leaves every project. To drop it from "
                 "one site only, use [[Not needed here]] on that project instead."),
            step("Draft", "This content is not confirmed",
                 "The 21 AMC and 11 RERA lines are a first draft. They must be "
                 "checked by whoever does your liaison work before anyone relies on them."),
        ],
    },

    # ------------------------------------------------------------------ tasks
    "delay_log": {
        "title": "What held the work up",
        "steps": [
            step("Counting", "A counting screen first",
                 "Days lost per reason, worst first. That total is why the reason "
                 "is chosen from a fixed list rather than typed as free text."),
            step("Late", "Late and replanned are both here",
                 "Late is finished after its date. Replanned is a date that was "
                 "moved outwards. Both cost the same fortnight; both are counted."),
            step("Filter", "Narrow it down",
                 "Choose a project or a reason and press [[Show]]. Press [[Clear]] "
                 "to go back to everything across every site."),
            step("Fixing", "The reason lives here, not on the chart",
                 "The Gantt carries how long something ran over. Why it did is "
                 "recorded here, so a year of delays can be counted and compared."),
        ],
    },

    "people": {
        "title": "Who is carrying what",
        "steps": [
            step("Load", "How much each person holds",
                 "One row per person: open tasks, how many are overdue, and the "
                 "days lost against their name across every site."),
            step("Read", "Overdue is not the same as late",
                 "Overdue means the date has passed and it is still open. Late "
                 "means it was finished after its date, and is already history."),
            step("Move", "Hand work to somebody else",
                 "Reassigning is done on the board: tick the rows and press "
                 "[[Reassign]]. This screen is where you notice it is needed."),
            step("Detail", "Look at one person's delays",
                 "Press [[Delays]] on their row to open the delay log filtered to "
                 "them, with the reason recorded against each one."),
        ],
    },

    # --------------------------------------------------------------- projects
    "project_list": {
        "title": "Working with projects",
        "steps": [
            step("Create", "Add a site",
                 "Press [[New project]] and give it a name, the built-up area and "
                 "the site address. The code is assigned once and never changes."),
            step("Area", "The built-up area drives the quote",
                 "Every figure on the estimate is a rate multiplied by this area, "
                 "so it is worth confirming before anybody starts quoting."),
            step("Status", "Draft, Quoted, then Won",
                 "Move a project to [[Won]] when the job is yours. The estimate "
                 "locks at that moment and becomes what every budget is measured against."),
            step("Open", "Go into one site",
                 "Press the project to open its own tabs — estimate, materials, "
                 "purchase orders, tasks and compliance for that site alone."),
        ],
    },

    "project_form": {
        "title": "Setting up a project",
        "steps": [
            step("Area", "Built-up area is the important one",
                 "Every estimate figure is a rate times this number. Getting it "
                 "wrong moves the whole quote, and it is hard to notice afterwards."),
            step("Address", "Two addresses, two jobs",
                 "The site address is where material is delivered. The billing "
                 "address is what prints on a purchase order, if it differs from ours."),
            step("Status", "Leave it as Draft while quoting",
                 "Draft and Quoted are both editable. Only move to [[Won]] when the "
                 "job is confirmed, because the estimate locks at that point."),
        ],
    },

    "stock": {
        "title": "Recording site stock",
        "steps": [
            step("Count", "Type what is on site",
                 "Enter the quantity in [[Stock]] for each material, activity by "
                 "activity. This is what is physically lying at the site today."),
            step("Minimum", "Set a level worth flagging",
                 "[[Min]] is the level below which the line is flagged. Leave it at "
                 "zero on anything you do not want warnings about."),
            step("Save", "Save before you leave",
                 "Press [[Save stock]]. Nothing is stored until you do, and moving "
                 "to another activity first will lose what you typed."),
            step("Effect", "What your figure changes",
                 "Stock is subtracted from what is still to buy, so an accurate "
                 "count is what stops the office ordering material already on site."),
        ],
    },

    "po_vendors": {
        "title": "One project's orders",
        "steps": [
            step("Vendors", "Grouped by who you bought from",
                 "Each vendor with their documents underneath. The figures beside a "
                 "vendor are that vendor's orders on this project only."),
            step("Status", "Filter to what you are chasing",
                 "Filter by status to see drafts waiting for approval, or "
                 "everything approved and delivered but not yet paid."),
            step("Open", "Work on one document",
                 "Press an order to open it. Approval, delivery, payment and the "
                 "printed PDF all happen on the document itself."),
        ],
    },

    "po_preview": {
        "title": "Before the orders exist",
        "steps": [
            step("Nothing", "Nothing has been created yet",
                 "This is what would be raised if you confirmed. No purchase order "
                 "exists at this point and nothing has been sent to anybody."),
            step("Check", "Read the figures per vendor",
                 "One block per vendor with its lines, quantities, GST and total. "
                 "This is the last point at which a wrong quantity costs nothing."),
            step("Missing", "Lines with no vendor",
                 "Anything without a vendor is listed by name and raises no order. "
                 "Go back, name a vendor, and post again."),
            step("Create", "Tick and confirm",
                 "Tick the vendors you want and press [[Create]]. Each becomes a "
                 "draft purchase order, which is still editable afterwards."),
        ],
    },

    # ----------------------------------------------------------- master data
    "material_list": {
        "title": "The material master",
        "steps": [
            step("Find", "Search before adding",
                 "Search by code, name or specification and press [[Search]]. Most "
                 "materials people think are missing are spelt differently."),
            step("Add", "Add one material",
                 "Press [[New material]]. The code is generated from the activity "
                 "and the group, assigned once, and never changes afterwards."),
            step("Excel", "Change many at once",
                 "Press [[⤓ Download these]] to get exactly what is on screen, edit "
                 "in Excel, then [[Upload the corrected file]] to bring it back."),
            step("Template", "Starting from scratch",
                 "[[⤓ Blank template]] gives the columns and the dropdowns with no "
                 "rows, for building a list somewhere else and importing it."),
            step("Retire", "Stop offering something",
                 "Untick [[Active]] on the material. It stays on every document "
                 "that used it and stops appearing in the pickers."),
        ],
    },

    "material_form": {
        "title": "Adding a material",
        "steps": [
            step("Activity", "Choose the activity first",
                 "The home activity and the group together decide the code, which "
                 "is assigned once. Neither can be changed after saving."),
            step("Rate", "The estimation rate is a benchmark",
                 "It is the company-wide figure a BOM plans at. A project can type "
                 "its own rate on the line without touching this one."),
            step("Unit", "Pick the unit from the list",
                 "The unit comes from the master so that two people cannot write "
                 "Nos and NOS. Add a missing one under Materials, Units of measure."),
            step("GST", "GST is per material",
                 "It is used on purchase orders, never on the BOM — every figure on "
                 "a bill of materials excludes tax."),
        ],
    },

    "vendor_list": {
        "title": "The vendor master",
        "steps": [
            step("Find", "Search before adding",
                 "Search by name, code or phone. The phone number is what makes a "
                 "vendor unique here — two firms can share a name."),
            step("Add", "Add one vendor",
                 "Press [[New vendor]]. The group says what they are in your words; the "
                 "construction activities say which trades they actually work on."),
            step("GSTIN", "A GST number is needed to order",
                 "A purchase order cannot be approved without it. Fill it in here, "
                 "or on the first order — it is saved back either way."),
            step("Cash", "Suppliers with no GST",
                 "Tick [[unregistered]] on the vendor for a local shop that has no "
                 "registration, so their spend can still be recorded."),
            step("Excel", "Change many at once",
                 "[[⤓ Download these]] gives what is on screen. Edit it and upload "
                 "the same file back to update them in one go."),
        ],
    },

    "vendor_form": {
        "title": "Adding a vendor",
        "steps": [
            step("Phone", "The phone number is the identity",
                 "Two firms can share a name and often do. The number is what says "
                 "they are the same supplier, so it is worth getting right."),
            step("Group", "What they are, in your words",
                 "The group is how somebody would search: Cement, Fabricator, "
                 "Colour agency. It is not the same as which activity they serve."),
            step("Type", "Purchase order or work order",
                 "A supplier gets a purchase order; a contractor gets a work order. "
                 "Set it here and every document to them starts out right."),
            step("Terms", "Payment terms drive what is owed",
                 "The number of days is used to work out when a payment is due. "
                 "Left empty, thirty days is assumed and the screen says so."),
        ],
    },

    "simple_master": {
        "title": "Editing this list",
        "steps": [
            step("Edit", "Type straight into the table",
                 "Every row is editable in place. Change what you need across as "
                 "many rows as you like, then press [[Save]] once."),
            step("Add", "Use the blank row at the bottom",
                 "The last row is empty. Type into it and press [[Save]]. Leaving "
                 "it blank adds nothing, so you cannot create an empty row."),
            step("Retire", "Nothing here is deleted",
                 "Other records point at these, so untick [[Active]] instead. It "
                 "stops being offered without disturbing anything already using it."),
            step("Count", "The number beside each row",
                 "How many records depend on that row. It is the answer to "
                 "\"what breaks if I turn this off\", before you turn it off."),
        ],
    },

    "vendor_rates": {
        "title": "What each vendor charges",
        "steps": [
            step("Source", "These are captured, not typed",
                 "A rate appears here when a purchase order is [[approved]]. A "
                 "draft records nothing, because nothing has been committed to."),
            step("Latest", "One row per vendor and material",
                 "A newer order replaces the rate rather than adding a row. The "
                 "[[From]] column names the order the current figure came from."),
            step("Use", "Where it comes back",
                 "On the BOM, choosing a vendor shows that rate in grey under "
                 "[[Vend Rate]]. Leave the cell blank to use it, or type over it."),
            step("Empty", "Nothing here yet",
                 "It fills up as orders are approved. There is nothing to type on "
                 "this screen, and that is deliberate — rates come from documents."),
        ],
    },

    "activity_master": {
        "title": "Construction activities",
        "steps": [
            step("Rate", "The company rate per sqft",
                 "This is what a new estimate starts from for that activity. A "
                 "project can quote differently without changing this figure."),
            step("Naming", "A name cannot be changed later",
                 "Once an estimate has used it, the name is locked — a rename would "
                 "silently zero that budget. The screen shows a lock and refuses."),
            step("Retire", "Turn it off instead",
                 "Untick [[Active]] and it stops being offered on new estimates. Every "
                 "project already quoting it carries on exactly as before."),
            step("Code", "The abbreviation is permanent",
                 "It is the first segment of every material code created under this "
                 "activity, so it is shown here but can never be edited."),
        ],
    },

    "company_profile": {
        "title": "Your own details",
        "steps": [
            step("Prints", "This is your letterhead",
                 "The registered name and address print at the top of every "
                 "purchase order, so they should read exactly as on your paperwork."),
            step("GSTIN", "Your GST number decides the tax",
                 "Its first two digits decide whether a vendor is billed CGST plus "
                 "SGST or IGST. Until it is filled in, everyone is treated as local."),
            step("Terms", "Standard terms are copied, then frozen",
                 "They are copied onto each new order and can be edited there. "
                 "Changing them here never touches an order already raised."),
        ],
    },

    # -------------------------------------------------------------- analytics
    "analytics_overview": {
        "title": "Reading the numbers",
        "steps": [
            step("Three", "Committed, received and paid",
                 "Three different questions, deliberately not added together. "
                 "Committed is ordered, received is arrived, paid has left the bank."),
            step("Spend", "Spend means money that left",
                 "Everywhere on these screens, spend is what has actually been "
                 "paid. An approved order is committed, not spent."),
            step("Period", "Choose the window",
                 "Year to date runs from 1 April. Choosing a month narrows every "
                 "figure that is about a period; what is owed is always about today."),
            step("Drafts", "Drafts count nowhere",
                 "A draft order has not been committed to anybody, so it appears in "
                 "no figure on any analytics screen."),
        ],
    },

    "analytics_g2n": {
        "title": "Gross to net",
        "steps": [
            step("Ladder", "Read it top to bottom",
                 "Gross, less discount, gives [[Basic]]. Plus GST gives [[Amount]]. "
                 "Then the agreed deduction and rounding give the order value."),
            step("Words", "Basic, GST and Amount",
                 "These are your vendors' words for the same three rungs, so the "
                 "screen and a supplier's invoice can be read side by side."),
            step("TDS", "Tax withheld is not a discount",
                 "TDS comes off the payment, not off the order. The vendor still "
                 "bills the full order value; less money leaves the bank."),
            step("Drill", "Open any step",
                 "Press a step to see the documents behind it, so any figure here "
                 "can be traced to the orders that make it up."),
        ],
    },

    "analytics_budget": {
        "title": "Budget against actual",
        "steps": [
            step("Three", "Budget, plan and actual",
                 "Budget is what was quoted. Plan is what the bill of materials "
                 "expects. Actual is what has been committed to vendors."),
            step("Gap", "What a gap means",
                 "Plan above budget means the job as planned costs more than it was "
                 "sold for. That gap is visible long before any money moves."),
            step("Tax", "Every figure excludes GST",
                 "The estimate adds tax once at the very end, so these are compared "
                 "without it. Mixing the two once reported 99% against a true 84%."),
            step("Choose", "Narrow to one site",
                 "Choose a project at the top. Left on all projects, the figures are "
                 "every Won site added together."),
        ],
    },

    "analytics_bom": {
        "title": "Buying patterns",
        "steps": [
            step("Where", "What the money went on",
                 "Spend by construction activity and by material, so the handful of "
                 "lines that carry most of the cost are visible."),
            step("Vendors", "Who you buy from",
                 "Share of spend per vendor. A supplier carrying most of a category "
                 "is a commercial fact worth knowing before renegotiating."),
            step("Basis", "Committed, not paid",
                 "These charts are about buying decisions, so they count everything "
                 "approved onwards rather than only what has been paid."),
        ],
    },

    "analytics_payments": {
        "title": "What is owed",
        "steps": [
            step("Buckets", "Three, and they add up",
                 "Settled, payable now, and not yet payable. Together they are "
                 "everything approved onwards, which is why they must reconcile."),
            step("Due", "How a due date is worked out",
                 "The vendor's payment terms from the approval date. Where a vendor "
                 "has none, thirty days is assumed and the row is flagged."),
            step("TDS", "Tax to deposit",
                 "What has been withheld from payments and is owed to the "
                 "department. It is computed on the basic value, never on the GST."),
            step("Ageing", "How overdue, not just whether",
                 "The ageing grid buckets what is late by how late. One vendor "
                 "ninety days overdue is a different conversation from ten at thirty."),
        ],
    },

    "analytics_work": {
        "title": "Progress and delay",
        "steps": [
            step("Trades", "Where the time is going",
                 "Days lost per construction activity, worst first, with how much of each "
                 "one is finished shown beside it for context."),
            step("Filter", "Narrow to one phase",
                 "Choose a milestone or an activity to narrow the tables. The "
                 "choices offered are only the ones this project actually uses."),
            step("Chart", "The chart shows the whole plan",
                 "It deliberately ignores the filters — it is the same schedule the "
                 "site team reads every morning, and it should look the same."),
            step("Money", "No money on this screen",
                 "A task names no material and no order, so any figure claiming what "
                 "a delay cost in rupees would be invented rather than measured."),
        ],
    },

    "analytics_documents": {
        "title": "Every document behind the figures",
        "steps": [
            step("Rows", "One row per order",
                 "Number, vendor, project, the four dates and the money. This is "
                 "the detail behind every total on the other tabs."),
            step("Filter", "Narrow before exporting",
                 "The filters at the top apply here too, so a month or one project "
                 "can be isolated before anything is downloaded."),
            step("Excel", "Send it to the accountant",
                 "Download what is on screen as a spreadsheet. It is the same rows "
                 "in the same order, so the two cannot disagree."),
        ],
    },

    # ----------------------------------------------------------------- people
    "user_list": {
        "title": "Who can sign in",
        "steps": [
            step("Add", "Create a sign-in",
                 "Press [[Add user]]. The user ID is short, like a SAP ID, and "
                 "there is no email sign-in — people type the ID they were given."),
            step("Role", "The role decides everything",
                 "What somebody sees and can press comes entirely from their role. "
                 "Change the role and their screens change at once."),
            step("Reset", "When somebody is locked out",
                 "Press [[Reset password]]. They are given a temporary one and must "
                 "change it the first time they sign in."),
            step("Leaving", "Turn an account off",
                 "Untick active rather than deleting. Everything they did stays "
                 "recorded against their name, which is the point of a record."),
        ],
    },

    "panel_text": {
        "title": "Translating the instructions",
        "steps": [
            step("Pick", "Choose a screen",
                 "The dropdown lists every screen that has an ⓘ panel. Its steps "
                 "appear below, in the order the reader sees them."),
            step("Write", "Type the Gujarati beside the English",
                 "The English cannot be changed here and neither can the order of "
                 "the steps — both come from the application itself."),
            step("Toggle", "When the reader sees it",
                 "A panel offers the English and ગુજરાતી buttons only once every "
                 "step a reader can see has been translated. Partly done stays English."),
            step("Recheck", "If a row is marked red",
                 "The English changed after that Gujarati was written, so it now "
                 "describes older wording. Read both, correct it, and save."),
            step("Remove", "Take a translation out",
                 "Clear the box and press [[Save]]. That step goes back to English "
                 "only, exactly as before anybody typed anything."),
        ],
    },

    "user_form": {
        "title": "Adding somebody",
        "steps": [
            step("ID", "A short user ID, not an email",
                 "This is what they type to sign in. It cannot be changed later, so "
                 "follow whatever pattern the rest of the company uses."),
            step("Role", "Give the narrowest role that works",
                 "A role can be widened in seconds. Somebody who can approve orders "
                 "on their first day is harder to undo."),
            step("Password", "They must change it",
                 "The password you set is temporary. They are asked to replace it "
                 "before they can reach any screen."),
        ],
    },
}
