"""
The ⓘ panels for the drawing screens, as data.

>>> ANCHOR: INFO-PANELS <<<
Same shape and same rules as `projects/help_panels.py`: a 1–2 word index
label, 20–30 words a step, `[[…]]` for a button or a field and nothing else,
`perm=` on any step whose action needs a permission. To be merged into
`projects.help_panels.PANELS` — see WIRING.md.
"""
from projects.panel_format import step

PANELS = {

    "drawings_home": {
        "title": "Drawings — overview",
        "steps": [
            step("Read", "See where every site stands",
                 "Each row is one Won project. [[Required]] counts drawings no revision has "
                 "arrived for, [[Received]] those waiting for approval, [[Approved]] those cleared."),
            step("Open", "Go to one project's register",
                 "Press the project name to open its register, grouped by section. The "
                 "[[Last transmittal]] date opens that project's transmittal register instead."),
            step("Watch", "Chase what is still required",
                 "A Required count that does not fall is a drawing the site is waiting for. "
                 "Open the register, filter by Required, and ask the architect."),
        ],
    },

    "drawings_register": {
        "title": "Drawing register",
        "steps": [
            step("Pick", "Choose the project",
                 "The picker at the top switches sites. Every drawing below belongs to the "
                 "chosen project alone, grouped by section — Architectural, Structural, MEP and so on."),
            step("Filter", "Narrow the list",
                 "Choose a group or a status and press [[Filter]]. Tick [[show deactivated]] "
                 "to see drawings taken off the register; their revisions are still on file."),
            step("Status", "Read the pill",
                 "Required means nothing has arrived. Received means the newest revision is "
                 "not approved yet. Approved means the newest one is cleared for use."),
            step("Register", "Add a drawing the site needs",
                 "Press [[Register a drawing]] for one, or [[Add several]] to paste a list of "
                 "number and title lines under one group. The number is the architect's.",
                 perm="drawings.edit"),
            step("Upload", "File a revision",
                 "Press [[Upload revision]] on the row to open the drawing and attach the "
                 "file with its label. A new revision never replaces the earlier one.",
                 perm="drawings.edit"),
        ],
    },

    "drawings_form": {
        "title": "Register a drawing",
        "steps": [
            step("Number", "Type the architect's number",
                 "Copy [[Number]] exactly from the title block — it is how site and architect "
                 "refer to the sheet. It must be unique on this project."),
            step("Group", "Choose the section",
                 "Pick the [[Group]] the sheet belongs to and, if known, the [[Architect]] "
                 "and a [[Required by]] date so the overview can show what is waited for."),
            step("Save", "Register it",
                 "Press [[Register]]. The drawing then appears on the register as Required until "
                 "its first revision is uploaded from the drawing's own page.",
                 perm="drawings.edit"),
            step("Deactivate", "Take one off the register",
                 "A drawing is never deleted once a revision is filed. Untick [[Active]] and "
                 "press [[Save]]; its revisions and transmittals stay on record.",
                 perm="drawings.edit"),
        ],
    },

    "drawings_bulk": {
        "title": "Add several drawings",
        "steps": [
            step("Paste", "One drawing per line",
                 "Type or paste into [[Lines]] one drawing per line as number, a vertical bar, "
                 "then the title — for example A-101 | Ground floor plan."),
            step("Group", "Choose the section once",
                 "Every line lands under the [[Group]] chosen above, with the same "
                 "[[Architect]] if one is picked. Register another batch for a different group."),
            step("Save", "Register them all",
                 "Press [[Register all]]. If any line is malformed or its number is already on "
                 "the register, nothing is saved and the message names the line.",
                 perm="drawings.edit"),
        ],
    },

    "drawings_detail": {
        "title": "One drawing",
        "steps": [
            step("History", "Read the revisions",
                 "Newest first; the top row is the current revision. Every earlier one stays "
                 "listed and downloadable, because a contractor may have built from it."),
            step("Download", "Get the file",
                 "Press [[Download]] on any revision. Files are served only through this "
                 "screen after the permission check — there is no link to pass around."),
            step("Upload", "File a new revision",
                 "Type the [[Label]] as the architect marks it, choose the [[File]] and press "
                 "[[Upload]]. A label already used on this drawing is refused.",
                 perm="drawings.edit"),
            step("Approve", "Clear a revision for use",
                 "Press [[Approve]] on the revision that was cleared. Your name and today's "
                 "date are recorded and cannot be changed or approved again.",
                 perm="drawings.edit"),
            step("Sent to", "See who holds which revision",
                 "The [[Sent to]] table lists every transmittal carrying this drawing — the "
                 "contractor, the revision they were handed, and the date."),
        ],
    },

    "drawings_transmittals": {
        "title": "Transmittals",
        "steps": [
            step("Read", "The register of what was handed over",
                 "Each row is one transmittal: the contractor, the purpose, how many drawings, "
                 "who issued it and when. Press the number to see its lines."),
            step("Record", "Record a new transmittal",
                 "Press [[Record a transmittal]], choose the contractor, tick the drawings "
                 "and say the purpose. Nothing is sent from here; this is the record.",
                 perm="drawings.transmit"),
            step("Print", "Get the paper copy",
                 "Press [[PDF]] for a printable transmittal listing every drawing number, "
                 "title, revision and date received, with a line for the contractor to sign."),
        ],
    },

    "drawings_transmittal_new": {
        "title": "Record a transmittal",
        "steps": [
            step("Contractor", "Choose who received the drawings",
                 "Contractors holding a purchase or work order on this project are listed "
                 "first under [[Contractor]]; every other active vendor follows below them."),
            step("Tick", "Choose the drawings",
                 "Tick each drawing handed over. The newest revision is what goes on the "
                 "record; a drawing with no revision yet is not offered."),
            step("Purpose", "Say what they are issued for",
                 "Choose [[Purpose]] — for construction, for approval or for information — "
                 "and the [[Issued on]] date if it was not today. Add a [[Note]] if needed."),
            step("Save", "Record it",
                 "Press [[Record transmittal]]. It is numbered, listed on the register, and "
                 "each drawing's page shows the contractor and the revision they were handed.",
                 perm="drawings.transmit"),
        ],
    },

    "drawings_transmittal": {
        "title": "One transmittal",
        "steps": [
            step("Read", "What was handed over",
                 "The contractor, the date, who issued it and the purpose sit at the top. "
                 "Every line below is one drawing at the revision handed over."),
            step("Open", "Go to a drawing",
                 "Press a drawing number to open its page and see whether a newer revision "
                 "has arrived since — if so the contractor holds a superseded sheet."),
            step("Print", "Download the PDF",
                 "Press [[Download PDF]] for the paper copy listing every drawing number, "
                 "title, revision and date received, with a signature line for the contractor."),
        ],
    },

    "drawings_architects": {
        "title": "Architects",
        "steps": [
            step("Read", "Who draws for the company",
                 "One row per architect with their firm, phone, email and how many drawings "
                 "across every project are registered against them."),
            step("Add", "Add an architect",
                 "Press [[Add an architect]], type the [[Name]] and firm, the [[Phone]] as "
                 "digits only, and press [[Save]]. They then appear in the drawing form.",
                 perm="drawings.edit"),
            step("Deactivate", "Take one off the list",
                 "Press [[Edit]] on the row and untick [[Active]]. An architect is never deleted "
                 "here — every drawing registered against them keeps their name.",
                 perm="drawings.edit"),
        ],
    },

    "drawings_groups": {
        "title": "Drawing groups",
        "steps": [
            step("Read", "The register's sections",
                 "Architectural, Structural, MEP, Landscape, Interior and Survey come "
                 "pre-loaded. [[Order]] decides the sequence on the register; [[Drawings]] counts what uses each."),
            step("Edit", "Change a row in place",
                 "Type into [[Code]], [[Name]] or [[Order]] on any row and press [[Save]]. "
                 "A code is up to four capitals and must be unique.",
                 perm="drawings.edit"),
            step("Add", "Add a group",
                 "Type into the blank row at the bottom and press [[Save]]. Leave it empty "
                 "and nothing is added — only typed rows count.",
                 perm="drawings.edit"),
            step("Retire", "Take a group off",
                 "Untick [[in use]] and press [[Save]]. A group is never deleted; drawings "
                 "already under it stay exactly where they are.",
                 perm="drawings.edit"),
        ],
    },
}
