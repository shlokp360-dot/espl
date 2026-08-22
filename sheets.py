"""
The master data Excel round trip: download a sheet, correct it, upload it back.

WHAT THIS FILE IS FOR
    material_workbook() / vendor_workbook()   build the file
    read_materials()    / read_vendors()      read it back and apply it

WHY BOTH HALVES ARE ONE SLICE
    Somebody maintaining 705 materials fixes three by hand and two hundred by
    spreadsheet. Building either half alone means coming back to the same code
    twice, so they were always going to ship together.

⚠⚠ THE PROPERTY THIS IS BUILT TO, AND IT IS A TEST:
    Download the file, change nothing, upload it → 0 created, N skipped,
    0 errors. If one record is altered by a round trip through Excel, that is a
    bug, not a quirk. Everything below serves that.

⚠ NO DATABASE IDs, ANYWHERE, EVER. Saahil's rule and he is right: "if we
  straight up download an SQL query type file, the user will be confused." The
  CODE is the key. Code filled in means update that record; code blank means it
  is new and a code is generated on import. So one file serves download,
  correction and fresh additions.

⚠ EACH LOOKUP USES THE IDENTIFIER THAT MODEL ALREADY LIVES BY, not its name and
  not a made-up one:
      material group  -> code          (CEM), which is already inside every material code
      activity        -> abbreviation  (RCC), likewise
      vendor group    -> name          (unique, and it has no code by design)

⚠ EXCEL DOES NOT ENFORCE VALIDATION ON PASTE. The dropdowns help people get it
  right; they do not guarantee it. Server-side validation stays the real gate,
  and every refusal is reported with its row number rather than silently
  skipped.
"""
from decimal import Decimal, InvalidOperation

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill, Protection
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from .imports import ImportReport
from .models import (Activity, DocumentType, Material, MaterialGroup, UnitOfMeasure, Vendor,
                     VendorGroup)

NAVY = "1F3864"
LOCKED = "EDEFF3"
REFERENCE = "Reference"

MATERIAL_COLUMNS = [
    ("Code", 16, "Leave BLANK for a new material — a code is generated on import"),
    ("Name", 32, ""),
    ("Specification", 26, "Brand or grade"),
    ("Group", 10, "Pick from the list"),
    ("Home activity", 14, "Required. Pick from the list"),
    ("Also used in", 14, "Optional second trade. Blank for almost everything"),
    ("UOM", 12, "Pick from the list"),
    # ⚠ NOT "the BOQ". The BOQ is built from ACTIVITY rates, ₹ per sqft of
    #   built-up area. This rate is what a BOM line PLANS at when nobody has
    #   typed a project rate, and it is the benchmark purchase variance is
    #   measured against. Saahil caught the old wording on the downloaded sheet.
    ("Estimation rate", 15, "The BOM's planning value — not a vendor price"),
    ("GST %", 9, ""),
    ("HSN", 12, ""),
    ("Common", 10, "Yes if every trade buys it"),
    ("Active", 9, "No takes it out of every picker without deleting it"),
    ("Reorder level", 14, ""),
    ("Current stock", 14, ""),
    ("Search aliases", 28, "Site vocabulary — saria, chips"),
]

VENDOR_COLUMNS = [
    ("Code", 12, "Leave BLANK for a new vendor"),
    ("Name", 30, ""),
    ("Contact person", 22, ""),
    ("Phone", 16, "The identity. Never two vendors with the same number"),
    ("WhatsApp", 16, "Blank fills itself from the phone number"),
    ("GSTIN", 18, "A purchase order cannot be approved without one"),
    ("Unregistered", 13, "Yes means no GSTIN expected and 0% GST"),
    ("Group", 30, "What this vendor is. Pick from the list"),
    ("Activity 1", 14, "Which trade they serve. Optional"),
    ("Activity 2", 14, "A second trade. Optional"),
    ("Document type", 15, "PO for a supplier, WO for a contractor"),
    ("Payment terms", 24, ""),
    ("Address", 34, ""),
    ("Active", 9, ""),
]

# ⚠ `state` IS NOT A COLUMN, deliberately. It is derived from the GSTIN's first
#   two digits, and letting anyone type it only creates a second answer that
#   disagrees with the first.


def _yes_no(value):
    return "Yes" if value else "No"


def _is_yes(text):
    return str(text).strip().lower() in {"yes", "y", "true", "1"}


def _decimal(text, field, row_number, report, default=None):
    """Read a number, or report why it could not be read. NEVER silently zero."""
    raw = str(text or "").strip().replace(",", "")
    if not raw:
        return default
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        report.error(row_number, f"{field}: “{text}” is not a number. Row left alone.")
        return None


def _style(sheet, columns, row_count):
    """Headings, widths, notes, a frozen header and a locked code column."""
    for index, (title, width, _note) in enumerate(columns, start=1):
        cell = sheet.cell(row=1, column=index, value=title)
        cell.font = Font(name="Arial", bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=NAVY)
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        sheet.column_dimensions[get_column_letter(index)].width = width
    # Row 2 explains each column in words, and is skipped on the way back in.
    for index, (_title, _width, note) in enumerate(columns, start=1):
        cell = sheet.cell(row=2, column=index, value=note)
        cell.font = Font(name="Arial", size=9, italic=True, color="6B7280")
        cell.alignment = Alignment(vertical="top", wrap_text=True)
    sheet.freeze_panes = "B3"

    # ⚠ THE CODE COLUMN IS LOCKED, and every other cell is not. A changed code is
    #   not an edit, it is a different record — and the one thing a round trip
    #   must never do is silently move a material's identity.
    sheet.protection.sheet = True
    sheet.protection.password = ""
    for row in sheet.iter_rows(min_row=3):
        for cell in row:
            cell.protection = Protection(locked=(cell.column == 1))
    for row in sheet.iter_rows(min_row=3, min_col=1, max_col=1):
        for cell in row:
            cell.fill = PatternFill("solid", fgColor=LOCKED)


def _reference_sheet(book, lists):
    """
    The sheet the dropdowns point at — and a lookup table for the reader.

    ⚠ VISIBLE, NOT HIDDEN, AND IT USED TO BE THE OTHER WAY ROUND. Saahil, on
      seeing the file: "there should also be another sheet where
      activity/groups are visible to allow users to see what the abbrevation
      stands for." He is right — a dropdown offering HDW and COM is no use to
      somebody who does not already know that HDW is Hardware & Fasteners. The
      sheet existed the whole time; it was hidden and carried only the codes.

    ⚠ THE VALIDATION STILL POINTS AT THE CODE COLUMN ONLY. The name sits in the
      column beside it, for reading. Putting "CEM — Cement & Binders" in the
      dropdown itself would mean that whole string had to be parsed back out on
      import, which is a class of bug this project has spent two days removing.

    `lists` maps a heading to either a list of codes, or a list of
    (code, meaning) pairs. Returns {heading: (column_letter, count)} so the
    validation knows where its values ended up.
    """
    sheet = book.create_sheet(REFERENCE)
    columns, index = {}, 1
    for title, values in lists.items():
        paired = bool(values) and isinstance(values[0], tuple)
        letter = get_column_letter(index)
        columns[title] = (letter, len(values))

        head = sheet.cell(row=1, column=index, value=title)
        head.font = Font(name="Arial", bold=True, color="FFFFFF")
        head.fill = PatternFill("solid", fgColor=NAVY)
        if paired:
            meaning = sheet.cell(row=1, column=index + 1, value="what it means")
            meaning.font = Font(name="Arial", bold=True, color="FFFFFF")
            meaning.fill = PatternFill("solid", fgColor=NAVY)

        for offset, value in enumerate(values, start=2):
            if paired:
                sheet.cell(row=offset, column=index, value=value[0]).font = Font(name="Arial")
                sheet.cell(row=offset, column=index + 1, value=value[1]).font = Font(name="Arial")
            else:
                sheet.cell(row=offset, column=index, value=value).font = Font(name="Arial")

        sheet.column_dimensions[letter].width = 16 if paired else 22
        if paired:
            sheet.column_dimensions[get_column_letter(index + 1)].width = 40
        index += 2 if paired else 1

    sheet.freeze_panes = "A2"
    sheet.sheet_state = "visible"
    return columns


def _validate(sheet, column_letter, reference, rows, message):
    """`reference` is the (column_letter, count) pair _reference_sheet returned."""
    letter, count = reference
    if not count:
        return
    rule = DataValidation(
        type="list",
        formula1=f"={REFERENCE}!${letter}$2:${letter}${count + 1}",
        allow_blank=True, showDropDown=False)
    rule.error = message
    rule.errorTitle = "Not on the list"
    sheet.add_data_validation(rule)
    rule.add(f"{column_letter}3:{column_letter}{rows + 3}")


# ============================================================== materials


def material_workbook(spare_rows=40, blank=False, rows=None):
    """
    Every material, as a sheet somebody can correct and hand back.

    ⚠ `blank=True` gives the SAME sheet with no rows in it — headings, notes,
      dropdowns and all. Saahil's point, and an obvious one once said: "I dont
      feel a need to download all materials as well, there should be one more
      button for download template for them to add." Downloading 705 rows to add
      three is the wrong shape, and scrolling to the bottom of somebody else's
      data to type is how mistakes get made.

    ⚠ THERE IS NO EXAMPLE ROW, DELIBERATELY. A template with a sample row in it
      is a template with a junk material in it the moment somebody forgets to
      delete it. The note row under each heading carries the format instead,
      where it cannot be imported.
    """
    book = Workbook()
    sheet = book.active
    sheet.title = "Materials"

    # Code AND meaning, so the reference sheet can be read by somebody who does
    # not already know that HDW is Hardware & Fasteners.
    #
    # ⚠ ACTIVE GROUPS ONLY, for the same reason as the units two lines down: this
    #   is the dropdown somebody outside the company fills in, and offering a
    #   retired group would invite rows that then have to be rejected. Vendor
    #   groups below already filter this way; material groups could not until
    #   they gained the field.
    groups = list(MaterialGroup.objects.filter(is_active=True)
                  .order_by("code").values_list("code", "name"))
    activities = list(Activity.objects.filter(is_active=True)
                      .order_by("sort_order").values_list("abbreviation", "name"))
    # ⚠ ACTIVE UNITS ONLY. This is the dropdown somebody else fills in, and it
    #   is the whole reason UOM stopped being a hardcoded list — a unit missing
    #   from here means their row is rejected and they can do nothing about it.
    uoms = list(UnitOfMeasure.objects.filter(is_active=True)
                .order_by("sort_order", "code").values_list("code", flat=True))

    # ⚠ `rows` IS WHAT THE SCREEN WAS SHOWING, NOT ALWAYS EVERY MATERIAL.
    #   Saahil: "when I wanted to download, it was only giving me an option to
    #   download all of them. Can we not select a few and then download those?"
    #   The four filters on the list are already the selection, so the export
    #   follows them rather than growing a second way to choose. None means the
    #   whole master, which is what the management commands and the tests pass.
    if blank:
        materials = []
    elif rows is None:
        materials = list(Material.objects
                         .select_related("group", "home_activity", "also_used_in")
                         .order_by("code"))
    else:
        materials = list(rows)

    for material in materials:
        sheet.append([
            material.code,
            material.name,
            material.specification,
            material.group.code if material.group else "",
            material.home_activity.abbreviation if material.home_activity else "",
            material.also_used_in.abbreviation if material.also_used_in else "",
            material.uom,
            float(material.estimation_rate),
            float(material.gst_percent),
            material.hsn_code,
            _yes_no(material.is_common),
            _yes_no(material.is_active),
            float(material.reorder_level) if material.reorder_level is not None else None,
            float(material.current_stock),
            material.search_aliases,
        ])
    # ⚠ The rows written above land at 2 onwards; shift them down for the notes
    #   row. Done by rebuilding rather than inserting, which openpyxl does badly.
    # ⚠ TWO rows, not one. Row 1 is the heading and row 2 is the plain-English
    #   note under it, so the data has to start at row 3 — which is also where
    #   every reader below starts. Shifting by one put the first material under
    #   the notes and silently lost it.
    sheet.insert_rows(1, amount=2)

    _style(sheet, MATERIAL_COLUMNS, len(materials))
    where = _reference_sheet(book, {"Group": groups, "Activity": activities, "UOM": uoms,
                                    "Yes/No": ["Yes", "No"]})

    total = len(materials) + spare_rows
    _validate(sheet, "D", where["Group"], total, "Pick a material group code from the list.")
    _validate(sheet, "E", where["Activity"], total, "Pick an activity abbreviation.")
    _validate(sheet, "F", where["Activity"], total, "Pick an activity abbreviation.")
    _validate(sheet, "G", where["UOM"], total, "Pick a unit from the list.")
    for column in ("K", "L"):
        _validate(sheet, column, where["Yes/No"], total, "Yes or No.")

    for row in sheet.iter_rows(min_row=3, min_col=8, max_col=9):
        for cell in row:
            cell.number_format = "#,##,##0.00"
    for row in sheet.iter_rows(min_row=3, min_col=13, max_col=14):
        for cell in row:
            cell.number_format = "#,##,##0.00"
    return book


def read_materials(stream):
    """
    Apply an uploaded material sheet.

    ⚠ CODE FILLED IN MEANS UPDATE. CODE BLANK MEANS NEW. There is no third case
      and no delete — a spreadsheet is the wrong instrument for destroying data,
      and Active = No already takes a material out of every picker.
    """
    report = ImportReport("Materials")
    book = load_workbook(stream, data_only=True)
    sheet = book["Materials"] if "Materials" in book.sheetnames else book.active

    # ⚠ EVERY group, active or not — same rule as the units below. A retired
    #   group is not offered in the template's dropdown, but a re-imported export
    #   of the materials already in it must still be accepted.
    groups = {g.code: g for g in MaterialGroup.objects.all()}
    activities = {a.abbreviation: a for a in Activity.objects.all()}
    # ⚠ EVERY unit, not only the active ones. An inactive unit must still be
    #   ACCEPTED on the way in — 618 materials carry "Nos", and deactivating it
    #   must stop it being offered, never start rejecting the rows that have it.
    #   Active-only belongs in the dropdown; the reader has to be forgiving.
    known_uoms = set(UnitOfMeasure.objects.values_list("code", flat=True))

    for number, row in enumerate(sheet.iter_rows(min_row=3, values_only=True), start=3):
        if not row or not any(str(v).strip() for v in row if v is not None):
            continue
        cells = [("" if v is None else str(v).strip()) for v in row]
        cells += [""] * (len(MATERIAL_COLUMNS) - len(cells))
        (code, name, spec, group_code, home, second, uom, rate, gst, hsn,
         common, active, reorder, stock, aliases) = cells[:15]

        if not name:
            report.error(number, "No name. Row skipped.")
            continue
        group = groups.get(group_code)
        if not group:
            report.error(number, f"Group “{group_code}” is not a material group. Row skipped.")
            continue
        home_activity = activities.get(home)
        if not home_activity:
            report.error(number, f"Home activity “{home}” is not an activity. Row skipped.")
            continue
        also = activities.get(second) if second else None
        if second and not also:
            report.error(number, f"Also used in “{second}” is not an activity. Row skipped.")
            continue
        if also and also.id == home_activity.id:
            report.error(number, "Also used in repeats the home activity. Leave it blank.")
            continue
        if uom and uom not in known_uoms:
            report.error(number, f"UOM “{uom}” is not a unit we know. Row skipped.")
            continue

        rate_value = _decimal(rate, "Estimation rate", number, report, Decimal("0"))
        gst_value = _decimal(gst, "GST %", number, report, Decimal("18"))
        reorder_value = _decimal(reorder, "Reorder level", number, report, None)
        stock_value = _decimal(stock, "Current stock", number, report, Decimal("0"))
        if rate_value is None or gst_value is None or stock_value is None:
            continue

        material = Material.objects.filter(code=code).first() if code else None
        if code and not material:
            report.error(number, f"No material has the code {code}. Row skipped — a code is never "
                                 f"typed, so this one cannot be created.")
            continue

        fields = dict(
            name=name, specification=spec, group=group, home_activity=home_activity,
            also_used_in=also, uom=uom, estimation_rate=rate_value, gst_percent=gst_value,
            hsn_code=hsn, is_common=_is_yes(common), is_active=_is_yes(active),
            reorder_level=reorder_value, current_stock=stock_value, search_aliases=aliases,
        )

        if material:
            # ⚠ THE HEART OF THE ROUND TRIP. Compare before writing, and say
            #   "skipped" when nothing differs. An import that saved every row
            #   would report 705 updates for a file nobody touched, which would
            #   make the report worthless and the property untestable.
            #
            # ⚠ THE CHANGE LIST IS READ BACK OFF THE OBJECT AFTER THE SAVE, the
            #   same as the vendor importer below. `Material` has no derived
            #   fields TODAY, so this cannot phantom yet — but the vendor one
            #   could not either until `whatsapp_number` started filling itself
            #   in, and then the report claimed an update that never happened.
            #   Keeping both paths identical means adding a derived field here
            #   later does not quietly reintroduce it.
            before = {key: getattr(material, key) for key in fields}
            if all(before[key] == value for key, value in fields.items()):
                report.skip(code, "unchanged")
                continue

            for key, value in fields.items():
                setattr(material, key, value)
            material.save()

            changed = [key for key in fields if before[key] != getattr(material, key)]
            if not changed:
                report.skip(code, "unchanged")
                continue
            report.update(code, ", ".join(changed))
        else:
            from .codes import next_code
            material = Material(code=next_code(home_activity, group), **fields)
            material.save()
            report.create(material.code, "new")

    return report


# ================================================================ vendors


def vendor_workbook(spare_rows=40, blank=False, rows=None):
    """
    The vendors on screen, every vendor, or a blank sheet to add them on.

    `rows` follows the same rule as material_workbook: None means the whole
    master, anything else is exactly what the list was showing.
    """
    book = Workbook()
    sheet = book.active
    sheet.title = "Vendors"

    # A vendor group has no code — its name IS the key — so there is nothing to
    # explain beside it. Activities still need their meaning spelled out.
    vendor_groups = list(VendorGroup.objects.filter(is_active=True)
                         .order_by("name").values_list("name", flat=True))
    activities = list(Activity.objects.filter(is_active=True)
                      .order_by("sort_order").values_list("abbreviation", "name"))

    if blank:
        vendors = []
    elif rows is None:
        vendors = list(Vendor.objects
                       .select_related("group", "activity_1", "activity_2")
                       .order_by("code"))
    else:
        vendors = list(rows)

    for vendor in vendors:
        sheet.append([
            vendor.code, vendor.name, vendor.contact_person, vendor.phone,
            vendor.whatsapp_number, vendor.gst_number, _yes_no(vendor.is_unregistered),
            vendor.group.name if vendor.group else "",
            vendor.activity_1.abbreviation if vendor.activity_1 else "",
            vendor.activity_2.abbreviation if vendor.activity_2 else "",
            vendor.default_document_type, vendor.payment_terms, vendor.address,
            _yes_no(vendor.is_active),
        ])
    # ⚠ TWO rows, not one. Row 1 is the heading and row 2 is the plain-English
    #   note under it, so the data has to start at row 3 — which is also where
    #   every reader below starts. Shifting by one put the first material under
    #   the notes and silently lost it.
    sheet.insert_rows(1, amount=2)

    _style(sheet, VENDOR_COLUMNS, len(vendors))
    where = _reference_sheet(book, {
        "Vendor group": vendor_groups,
        "Activity": activities,
        "Document type": [("PO", "Purchase Order — a supplier"),
                          ("WO", "Work Order — a contractor")],
        "Yes/No": ["Yes", "No"],
    })

    total = len(vendors) + spare_rows
    _validate(sheet, "H", where["Vendor group"], total, "Pick a vendor group from the list.")
    _validate(sheet, "I", where["Activity"], total, "Pick an activity abbreviation.")
    _validate(sheet, "J", where["Activity"], total, "Pick an activity abbreviation.")
    _validate(sheet, "K", where["Document type"], total, "PO or WO.")
    for column in ("G", "N"):
        _validate(sheet, column, where["Yes/No"], total, "Yes or No.")
    return book


def read_vendors(stream):
    """Apply an uploaded vendor sheet. Same rules as materials."""
    report = ImportReport("Vendors")
    book = load_workbook(stream, data_only=True)
    sheet = book["Vendors"] if "Vendors" in book.sheetnames else book.active

    groups = {g.name: g for g in VendorGroup.objects.all()}
    activities = {a.abbreviation: a for a in Activity.objects.all()}

    for number, row in enumerate(sheet.iter_rows(min_row=3, values_only=True), start=3):
        if not row or not any(str(v).strip() for v in row if v is not None):
            continue
        cells = [("" if v is None else str(v).strip()) for v in row]
        cells += [""] * (len(VENDOR_COLUMNS) - len(cells))
        (code, name, contact, phone, whatsapp, gstin, unregistered, group_name,
         first, second, doc_type, terms, address, active) = cells[:14]

        if not name:
            report.error(number, "No name. Row skipped.")
            continue
        if not phone:
            report.error(number, "No phone number, and a phone number is how a vendor is "
                                 "identified. Row skipped.")
            continue
        group = groups.get(group_name) if group_name else None
        if group_name and not group:
            report.error(number, f"Group “{group_name}” is not a vendor group. Row skipped.")
            continue
        activity_1 = activities.get(first) if first else None
        activity_2 = activities.get(second) if second else None
        if first and not activity_1:
            report.error(number, f"Activity 1 “{first}” is not an activity. Row skipped.")
            continue
        if second and not activity_2:
            report.error(number, f"Activity 2 “{second}” is not an activity. Row skipped.")
            continue
        if activity_2 and activity_1 and activity_2.id == activity_1.id:
            report.error(number, "Activity 2 repeats Activity 1. Leave it blank.")
            continue
        if doc_type and doc_type not in DocumentType.values:
            report.error(number, f"Document type “{doc_type}” must be PO or WO. Row skipped.")
            continue
        if gstin and _is_yes(unregistered):
            report.error(number, "A vendor cannot be unregistered and have a GSTIN. Row skipped.")
            continue

        vendor = Vendor.objects.filter(code=code).first() if code else None
        if code and not vendor:
            report.error(number, f"No vendor has the code {code}. Row skipped.")
            continue

        fields = dict(
            name=name, contact_person=contact, phone=phone, whatsapp_number=whatsapp,
            gst_number=gstin, is_unregistered=_is_yes(unregistered), group=group,
            activity_1=activity_1, activity_2=activity_2,
            default_document_type=doc_type or DocumentType.PO,
            payment_terms=terms, address=address, is_active=_is_yes(active),
        )

        if vendor:
            # >>> ANCHOR: IMPORT-REPORT <<<
            # ⚠⚠ THE CHANGE LIST IS COMPUTED AFTER THE SAVE, NOT BEFORE, AND
            #    THAT IS THE WHOLE POINT. `Vendor.save()` DERIVES fields — a
            #    blank WhatsApp column refills itself from the phone, so the
            #    before-diff saw `917574809300` -> `""`, called it a change, and
            #    the save put the identical value straight back. The row was
            #    then reported as "updated: whatsapp_number" having not moved.
            #
            # ⚠ IT IS A CLASS, NOT A CASE. Any field the model works out for
            #   itself would do the same; asking the database what actually
            #   landed is the only answer that stays true when another derived
            #   field is added later.
            before = {key: getattr(vendor, key) for key in fields}
            if all(before[key] == value for key, value in fields.items()):
                report.skip(code, "unchanged")
                continue

            for key, value in fields.items():
                setattr(vendor, key, value)
            vendor.save()

            # ⚠ NO `refresh_from_db()` HERE, DELIBERATELY. `Vendor.save()` writes
            #   its derived values onto the instance before handing off to the
            #   database, so this object already carries exactly what landed.
            #   Re-reading would cost a query per row and a refetch of every
            #   foreign key to learn the same thing.
            changed = [key for key in fields if before[key] != getattr(vendor, key)]
            if not changed:
                # Every difference the sheet offered was undone by the model.
                # Nothing moved, so say so rather than claiming an update.
                report.skip(code, "unchanged")
                continue
            report.update(code, ", ".join(changed))
        else:
            last = Vendor.objects.order_by("-code").values_list("code", flat=True).first()
            tail = last.split("-")[-1] if last else ""
            nxt = int(tail) + 1 if tail.isdigit() else 1
            vendor = Vendor(code=f"VEN-{nxt:03d}", **fields)
            vendor.save()
            report.create(vendor.code, "new")

    return report
