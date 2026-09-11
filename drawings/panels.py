"""
The ⓘ panels for the drawing screens, as data.

>>> ANCHOR: INFO-PANELS <<<
Same shape and same rules as `projects/help_panels.py`: a 1–2 word index
label, 20–30 words a step, `[[…]]` for a button or a field and nothing else,
`perm=` on any step whose action needs a permission. To be merged into
`projects.help_panels.PANELS` in `projects/help_panels.py`.
"""
from projects.panel_format import step

PANELS = {

    "drawings_home": {
        "title": "Drawings repository — overview",
        "steps": [
            step("Read", "See where every project stands",
                 "Live sites sit in the first table, completed projects in the second. "
                 "[[Required]] counts drawings no revision has arrived for, [[Received]] those "
                 "awaiting approval, [[Approved]] those cleared."),
            step("Open", "Go to one project's register",
                 "Press the project name to open its register, grouped by type — Architect, "
                 "Structure, Survey, Passing and MEP. [[Latest revision]] is the date the newest file arrived."),
            step("Compliance", "Open the project's compliance file",
                 "The [[Compliance]] count is how many compliance documents that project holds. "
                 "Press it to open the project's compliance screen and file more, completed projects included."),
            step("Watch", "Chase what is still required",
                 "A Required count that does not fall is a drawing the site is waiting for. "
                 "Open the register, filter by Required, and ask the architect."),
        ],
    },

    "drawings_register": {
        "title": "Drawing register",
        "steps": [
            step("Pick", "Choose the project",
                 "The picker at the top lists live sites and completed projects. Every drawing "
                 "below belongs to the chosen project alone, grouped by type — Architect, Structure, Survey, Passing, MEP."),
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
                 "press [[Save]]; every revision stays on record and stays downloadable.",
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
                 "listed and downloadable, because the site may have built from it."),
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
            step("Read", "The five types receivable",
                 "Architect, Structure, Survey, Passing and MEP come pre-loaded — Passing is the "
                 "AMC-passed plan set. [[Order]] decides the register sequence; [[Drawings]] counts what uses each."),
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
