"""
Imports the master-data spreadsheets into the database.

HOW TO RUN IT
    python manage.py import_masters --materials "C:\\path\\MATERIAL_MASTER.xlsx" ^
                                    --vendors   "C:\\path\\VENDOR_MASTER.xlsx"

    Add --dry-run to see exactly what WOULD happen without writing anything.
    Always worth doing first.

IT IS SAFE TO RUN TWICE
    Rows already in the database come back as SKIPPED, not as errors. So the
    normal way to fix a problem is: correct the spreadsheet, run the whole file
    again. You never have to extract just the failed rows.

WHAT IT IMPORTS
    Groups      GROUP NAME sheet     -> MaterialGroup
    Materials   MATERIAL MASTER      -> Material, plus its activity link
    Vendors     VENDOR LIST          -> Vendor, plus their categories

WHAT IT DELIBERATELY DOES NOT IMPORT
    VENDOR RATES. That sheet's "goods / service" column is free text — entries
    like "RERA registration" and "Structure Design" are services, not materials
    in the master. Linking them would mean fuzzy-matching text to material
    codes, which is precisely the thing that must never happen automatically:
    an earlier pass over this data produced eighteen confident and wrong matches.
    Import them by hand, or give the sheet a material_code column.
"""
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from masters.imports import ImportReport, digits_only, normalise, read_sheet, similarity, to_decimal
from masters.models import Material, MaterialGroup, Vendor, VendorGroup, resolve_uom


class Command(BaseCommand):
    help = "Import materials, groups and vendors from the master spreadsheets."

    def add_arguments(self, parser):
        parser.add_argument("--materials", help="Path to MATERIAL_MASTER.xlsx")
        parser.add_argument("--vendors", help="Path to VENDOR_MASTER.xlsx")
        parser.add_argument("--dry-run", action="store_true",
                            help="Report what would happen, write nothing.")

    def handle(self, *args, **options):
        try:
            import openpyxl
        except ImportError:
            raise CommandError("openpyxl is not installed. Run: pip install -r requirements.txt")

        if not options["materials"] and not options["vendors"]:
            raise CommandError("Give at least one of --materials or --vendors.")

        dry_run = options["dry_run"]
        reports = []

        # Everything happens inside one transaction. If anything raises, nothing
        # is written — you are never left with half an import. A dry run rolls
        # the same transaction back deliberately at the end.
        try:
            with transaction.atomic():
                if options["materials"]:
                    path = Path(options["materials"])
                    if not path.exists():
                        raise CommandError(f"File not found: {path}")
                    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
                    reports.append(self.import_groups(workbook))
                    reports.append(self.import_materials(workbook))

                if options["vendors"]:
                    path = Path(options["vendors"])
                    if not path.exists():
                        raise CommandError(f"File not found: {path}")
                    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
                    reports.append(self.import_vendors(workbook))

                self.print_reports(reports)

                if dry_run:
                    raise _DryRun()
        except _DryRun:
            self.stdout.write(self.style.WARNING(
                "\nDRY RUN — nothing was written. Re-run without --dry-run to apply."))
            return

        if any(not report.ok for report in reports):
            self.stdout.write(self.style.WARNING(
                "\nSome rows had errors and were skipped. Fix them in the spreadsheet and "
                "run the whole file again — rows already imported will be skipped, not duplicated."))
        else:
            self.stdout.write(self.style.SUCCESS("\nImport complete."))

    # ---------------------------------------------------------------- groups
    def import_groups(self, workbook):
        report = ImportReport("Groups")
        for row_number, row in read_sheet(workbook, "GROUP NAME"):
            code = (row.get("Group") or "").strip()
            name = (row.get("Group Name") or "").strip()

            # The sheet carries a trailing note row; it has no usable code.
            if not code or code.lower().startswith("note") or code.upper() == "TOTAL":
                continue
            if not name:
                report.error(row_number, f"Group '{code}' has no name.")
                continue
            if len(code) > 4:
                report.error(row_number, f"Group code '{code}' is longer than 4 characters.")
                continue

            existing = MaterialGroup.objects.filter(code=code).first()
            if existing:
                report.skip(code, "already in the database")
                continue

            stock = (row.get("Stock item?") or "").strip().lower()
            MaterialGroup.objects.create(
                code=code, name=name,
                is_stock_item=stock not in ("no", "n", "false"),
            )
            report.create(code, name)
        return report

    # ------------------------------------------------------------- materials
    def import_materials(self, workbook):
        from masters.models import Activity

        report = ImportReport("Materials")
        groups = {g.code: g for g in MaterialGroup.objects.all()}
        activities_by_name = {a.name: a for a in Activity.objects.all()}

        # Everything already in the database, plus everything seen so far in
        # this file. Both matter: a spreadsheet can duplicate a row against
        # itself, which is the commonest way duplicates arrive.
        seen = {normalise(f"{m.name}|{m.specification}"): m.code
                for m in Material.objects.all()}
        names_for_similarity = {m.name: m.code for m in Material.objects.all()}

        for row_number, row in read_sheet(workbook, "MATERIAL MASTER"):
            code = (row.get("Material Code") or "").strip()
            name = (row.get("Material Name") or "").strip()
            specification = (row.get("Specification") or "").strip()

            if not code or not name:
                report.error(row_number, "Material Code and Material Name are both required.")
                continue

            if Material.objects.filter(code=code).exists():
                report.skip(code, "already in the database")
                continue

            # --- EXACT duplicate, after normalising. Rejected. ---------------
            fingerprint = normalise(f"{name}|{specification}")
            if fingerprint in seen:
                report.error(row_number,
                             f"'{name} / {specification or 'no spec'}' already exists as "
                             f"{seen[fingerprint]}.")
                continue

            group = groups.get((row.get("Group") or "").strip())
            if group is None:
                report.error(row_number,
                             f"Group '{row.get('Group')}' is not in the GROUP NAME sheet.")
                continue

            # resolve_uom accepts known spellings ("Hrs" -> "Hour") but never
            # guesses. An unrecognised unit is reported, not assumed.
            uom = resolve_uom(row.get("UOM"))
            if uom is None:
                report.error(row_number,
                             f"UOM '{row.get('UOM')}' is not a recognised unit. Add it to "
                             f"UOM_CHOICES, or to UOM_ALIASES if it means an existing unit.")
                continue

            activity_name = (row.get("Activity (home)") or "").strip()
            activity = activities_by_name.get(activity_name)
            if activity is None:
                report.error(row_number,
                             f"Activity '{activity_name}' is not in the Activity master. "
                             f"Add it there first — activities are never created by import.")
                continue

            errors = []
            rate = to_decimal(row.get("Estimation Rate"), "Estimation Rate", row_number, errors, default=0)
            gst = to_decimal(row.get("GST %"), "GST %", row_number, errors, default=18)
            reorder = to_decimal(row.get("Reorder Level"), "Reorder Level", row_number, errors)
            stock = to_decimal(row.get("Current Stock"), "Current Stock", row_number, errors, default=0)
            if errors:
                for message in errors:
                    report.error(row_number, message)
                continue

            # --- NEAR duplicate. Warns only, never rejects. ------------------
            for other_name, other_code in names_for_similarity.items():
                if similarity(name, other_name) >= 0.93:
                    report.warn(row_number,
                                f"'{name}' resembles '{other_name}' ({other_code}). "
                                f"Imported anyway — check they are genuinely different.")
                    break

            material = Material.objects.create(
                code=code, name=name, group=group,
                subgroup=(row.get("Old Subgroup") or "GEN").strip()[:6] or "GEN",
                specification=specification, uom=uom,
                estimation_rate=rate, gst_percent=gst,
                hsn_code=(row.get("HSN Code") or "").strip()[:10],
                reorder_level=reorder, current_stock=stock or 0,
                search_aliases=(row.get("Search Aliases") or "").strip()[:300],
                is_common=(row.get("Common?") or "").strip().lower() in ("yes", "y", "true"),
                is_active=(row.get("Active") or "yes").strip().lower() not in ("no", "n", "false"),
                # ⚠ SLICE 8: the home activity is a COLUMN and it is required.
                #   This used to be written as a MaterialActivity row afterwards,
                #   which left the material with no trade at all — the command
                #   crashed on the first row, and would have done since slice 8.
                home_activity=activity,
            )

            seen[fingerprint] = code
            names_for_similarity[name] = code
            report.create(code, name)

        return report

    # --------------------------------------------------------------- vendors
    def import_vendors(self, workbook):
        report = ImportReport("Vendors")
        seen_phones = set(Vendor.objects.values_list("phone", flat=True))

        for row_number, row in read_sheet(workbook, "VENDOR LIST"):
            code = (row.get("vendor_code") or "").strip()
            name = (row.get("vendor_name") or "").strip()
            phone = digits_only(row.get("phone"))

            if not code or not name:
                report.error(row_number, "vendor_code and vendor_name are both required.")
                continue
            if Vendor.objects.filter(code=code).exists():
                report.skip(code, "already in the database")
                continue

            # A vendor's identity is their PHONE, never their name. Three names
            # in the source data covered two different people each, so matching
            # on name would have silently merged them.
            if not phone:
                report.error(row_number,
                             f"{code} '{name}' has no phone number. The phone is the vendor's "
                             f"identity, so it cannot be imported without one.")
                continue
            if phone in seen_phones:
                report.error(row_number,
                             f"{code} '{name}' has phone {phone}, which already belongs to "
                             f"another vendor. Two vendors cannot share a number.")
                continue

            vendor = Vendor.objects.create(
                code=code, name=name,
                contact_person=(row.get("contact_person") or "").strip()[:120],
                phone=phone,
                secondary_phone=digits_only(row.get("secondary_phone")),
                email=(row.get("email") or "").strip(),
                gst_number=(row.get("gst_number") or "").strip().upper(),
                address=(row.get("address") or "").strip(),
                payment_terms=(row.get("payment_terms") or "").strip()[:60],
            )
            seen_phones.add(phone)

            # ⚠ SLICE 8: a vendor has ONE group, not a list of free-text
            #   categories. The first value in the column becomes the group and
            #   the rest are reported rather than silently dropped — a spreadsheet
            #   naming three trades is telling you something, even if only one
            #   can be kept.
            wanted = [c.strip()[:60] for c in (row.get("categories_supplied") or "").split(",")
                      if c.strip()]
            if wanted:
                group, _ = VendorGroup.objects.get_or_create(name=wanted[0])
                vendor.group = group
                vendor.save(update_fields=["group"])
                if len(wanted) > 1:
                    report.warn(row_number,
                                f"{code} listed {len(wanted)} categories; kept '{wanted[0]}' as "
                                f"its group and ignored {', '.join(wanted[1:])}.")

            report.create(code, name)

        return report

    # ---------------------------------------------------------------- output
    def print_reports(self, reports):
        for report in reports:
            self.stdout.write("")
            self.stdout.write(self.style.MIGRATE_HEADING(report.summary()))

            # >>> ANCHOR: IMPORT-REPORT <<<
            # ⚠ CREATED AND UPDATED ARE PRINTED SEPARATELY — bug C5. This is the
            #   command that seeds the live server, so the difference between
            #   "705 created" and "705 updated" is the difference between a
            #   fresh install working and somebody having just overwritten the
            #   master they meant to add to.
            for identifier, detail in report.created[:5]:
                self.stdout.write(f"   created  {identifier}  {detail}")
            if len(report.created) > 5:
                self.stdout.write(f"   created  ... and {len(report.created) - 5} more")

            for identifier, detail in report.updated[:5]:
                self.stdout.write(f"   updated  {identifier}  {detail}")
            if len(report.updated) > 5:
                self.stdout.write(f"   updated  ... and {len(report.updated) - 5} more")

            if report.skipped:
                self.stdout.write(f"   unchanged  {len(report.skipped)} already in the database "
                                  f"exactly as the sheet has them "
                                  f"(this is normal on a re-run, not an error)")

            for row_number, message in report.warnings[:10]:
                self.stdout.write(self.style.WARNING(f"   warning  row {row_number}: {message}"))
            if len(report.warnings) > 10:
                self.stdout.write(self.style.WARNING(
                    f"   warning  ... and {len(report.warnings) - 10} more"))

            for row_number, message in report.errors[:20]:
                self.stdout.write(self.style.ERROR(f"   ERROR    row {row_number}: {message}"))
            if len(report.errors) > 20:
                self.stdout.write(self.style.ERROR(
                    f"   ERROR    ... and {len(report.errors) - 20} more"))


class _DryRun(Exception):
    """Raised to roll the transaction back after a dry run. Never an error."""
