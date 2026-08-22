"""
Reading the master-data spreadsheets into the database.

WHAT THIS FILE IS FOR
    Turning MATERIAL_MASTER.xlsx and VENDOR_MASTER.xlsx into rows, safely and
    repeatedly. Called by the `import_masters` management command.

WHAT DEPENDS ON IT
    Nothing else calls it directly. But everything downstream depends on it
    having been RIGHT, so it reports rather than assumes.

THE THREE OUTCOMES — this is the important idea
    Every row lands in exactly one bucket:
        CREATED  a new row, with the code it was given
        SKIPPED  already in the database. NOT an error
        ERROR    failed validation, with the reason

    Why three and not two: partial import is deliberate (good rows go in, bad
    rows are reported), and the intended fix is to correct the spreadsheet and
    re-upload the WHOLE file. On that second run the already-imported rows come
    back as duplicates. If those were reported as errors, three real problems
    would be buried under seven hundred false ones. A clean second pass should
    read "3 created, 718 skipped, 0 errors".

DUPLICATE DETECTION HAS TWO LEVELS — do not collapse them
    EXACT match after normalising  -> ERROR, row rejected
    NEAR match (~0.93 similarity)  -> WARNING only, never rejected

    The second one matters more than it looks. MTA and FTA are different
    fittings. UPVC, CPVC and PVC are different plastics. RE TEE and TEE are
    different parts. 1I, 1II and 2II are inch fractions, not typos. An earlier
    pass over this data produced eighteen confident and completely wrong
    duplicate recommendations. Blocking on similarity would reject real
    materials, so similarity only ever warns.
"""
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
import re

# >>> ANCHOR: IMPORT-VALIDATE <<<
# Changing anything below changes which spreadsheet rows are accepted. If an
# import starts rejecting rows it used to accept, or vice versa, start here.

NEAR_DUPLICATE_THRESHOLD = 0.93


def normalise(text):
    """
    Reduce a name to its comparable core: uppercase, letters and digits only.

        "1.0 SQ MM"  ->  "10SQMM"
        "1.0 SQMM"   ->  "10SQMM"     same material, written two ways
        "20 MM PVC BEND" -> "20MMPVCBEND"

    THE SAME FUNCTION MUST BE USED FOR SEARCH. If dedupe and search normalise
    differently, you get duplicates that the search box cannot find — which is
    the worst of both worlds. 78 of the 721 materials carry a size written
    inconsistently, so this is not hypothetical.
    """
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def similarity(a, b):
    """0.0 to 1.0. Used only to WARN about near-duplicates, never to reject."""
    return SequenceMatcher(None, normalise(a), normalise(b)).ratio()


def to_decimal(value, field, row_number, errors, default=None):
    """
    Parse a spreadsheet cell into a Decimal, recording a readable error instead
    of raising. Blank is allowed and returns `default` — 342 of the newer
    materials genuinely have no rate yet, which is expected, not a failure.
    """
    if value is None or str(value).strip() == "":
        return default
    try:
        return Decimal(str(value).strip().replace(",", ""))
    except (InvalidOperation, ValueError):
        errors.append(f"Row {row_number}: '{field}' is '{value}', which is not a number.")
        return default


def digits_only(value):
    """Phone numbers are stored as digits alone — no spaces, plus signs or dashes."""
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def read_sheet(workbook, sheet_name):
    """
    Yield (row_number, {column_header: value}) for every non-empty row.

    Row numbers are the ones you see in Excel, so an error message can say
    "Row 42" and you can go straight to it.
    """
    sheet = workbook[sheet_name]
    rows = sheet.iter_rows(values_only=True)
    headers = [str(cell).strip() if cell is not None else "" for cell in next(rows)]

    for offset, values in enumerate(rows, start=2):
        if not any(value is not None and str(value).strip() for value in values):
            continue
        record = {}
        for index, header in enumerate(headers):
            if not header:
                continue
            cell = values[index] if index < len(values) else None
            record[header] = "" if cell is None else str(cell).strip()
        yield offset, record


class ImportReport:
    """
    Collects what happened, so the command can print something honest at the end
    rather than a bare "done".
    """

    def __init__(self, label):
        self.label = label
        self.created = []
        # >>> ANCHOR: IMPORT-REPORT <<<
        # ⚠⚠ AN UPDATE IS NOT A CREATION, AND SAYING SO WAS BUG C5. There was no
        #    bucket for "changed a row that already existed", so `read_materials`
        #    and `read_vendors` filed updates under `created` with a detail
        #    string that said "updated: rate". The per-row line was therefore
        #    honest and the SUMMARY ABOVE IT CONTRADICTED IT — a round trip that
        #    edited one vendor reported "1 created, 0 skipped".
        #
        #    It matters most on the day it matters most: seeding the live server
        #    imports 705 materials and 174 vendors, and "705 created" on a run
        #    that actually updated 705 existing rows is the difference between
        #    "it worked" and "I have just duplicated the master".
        self.updated = []
        self.skipped = []
        self.errors = []
        self.warnings = []

    def create(self, identifier, detail=""):
        self.created.append((identifier, detail))

    def update(self, identifier, detail=""):
        """A row that already existed and now reads differently."""
        self.updated.append((identifier, detail))

    def skip(self, identifier, reason):
        self.skipped.append((identifier, reason))

    def error(self, row_number, message):
        self.errors.append((row_number, message))

    def warn(self, row_number, message):
        self.warnings.append((row_number, message))

    @property
    def ok(self):
        return not self.errors

    @property
    def touched(self):
        """
        Everything this import changed, created or updated.

        ⚠ THE SCREENS LIST WHAT CHANGED and do not care which kind it was. This
          keeps them from having to concatenate two lists and get the order
          wrong — created first, then updated, which is the order somebody
          reads them in.
        """
        return self.created + self.updated

    def summary(self):
        return (f"{self.label}: {len(self.created)} created, {len(self.updated)} updated, "
                f"{len(self.skipped)} unchanged, {len(self.errors)} errors, "
                f"{len(self.warnings)} warnings")
