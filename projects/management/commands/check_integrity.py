"""
Checks your live database for things that should never be true.

HOW TO RUN IT
    python manage.py check_integrity

    Reads only — it never changes anything. Safe to run any time, including on
    the live server while people are using it.

WHEN TO RUN IT
    Whenever a number looks wrong. It answers one question: is the DATA
    inconsistent, or is the data fine and the number merely surprising? Those
    need completely different responses, and guessing wastes hours.

    Also worth running after an import, after restoring a backup, and before
    anything important.

HOW THIS DIFFERS FROM `manage.py test`
    `test` proves the CODE is right, using invented data in a throwaway
    database. This checks that YOUR REAL DATA is sane. You need both: correct
    code can still be fed a spreadsheet with two materials sharing a code.
"""
from django.core.management.base import BaseCommand
from django.db.models import Count

from masters.models import Material, Vendor
from projects.bom_models import BomLine, PurchaseOrder
from projects.models import Activity, MaterialActivity


class Command(BaseCommand):
    help = "Check the live database for inconsistencies. Read-only."

    def add_arguments(self, parser):
        parser.add_argument("--quiet", action="store_true",
                            help="Only print problems, not the checks that passed.")

    def handle(self, *args, **options):
        self.quiet = options["quiet"]
        self.problems = 0

        self.stdout.write(self.style.MIGRATE_HEADING("\nMATERIALS"))
        self.check_every_material_has_one_home_activity()
        self.check_code_matches_its_group()
        self.check_no_duplicate_names()

        self.stdout.write(self.style.MIGRATE_HEADING("\nVENDORS"))
        self.check_every_vendor_has_a_phone()
        self.check_gstins_look_valid()

        self.stdout.write(self.style.MIGRATE_HEADING("\nACTIVITIES"))
        self.check_abbreviations()

        self.stdout.write(self.style.MIGRATE_HEADING("\nBOM AND PURCHASE ORDERS"))
        self.check_quantities_are_not_negative()
        self.check_approved_orders_have_a_gstin()
        self.check_receipts_belong_to_delivered_orders()

        self.stdout.write("")
        if self.problems:
            self.stdout.write(self.style.ERROR(
                f"{self.problems} problem{'s' if self.problems > 1 else ''} found. "
                f"Nothing has been changed — these need a human decision."))
        else:
            self.stdout.write(self.style.SUCCESS(
                "No problems found. If a number still looks wrong, the data is consistent "
                "and the calculation is worth checking instead — see ANCHORS.md."))

    # ------------------------------------------------------------------ tools
    def ok(self, message):
        if not self.quiet:
            self.stdout.write(f"  ok    {message}")

    def bad(self, message, examples=()):
        self.problems += 1
        self.stdout.write(self.style.ERROR(f"  FAIL  {message}"))
        for example in list(examples)[:10]:
            self.stdout.write(f"          {example}")
        if len(list(examples)) > 10:
            self.stdout.write(f"          ... and {len(list(examples)) - 10} more")

    # --------------------------------------------------------------- material
    def check_every_material_has_one_home_activity(self):
        """
        The home activity is what the material's code was built from, and what
        the BOM groups by. Without exactly one, the material shows in no
        activity's list and is effectively invisible.
        """
        # ⚠ SLICE 8 MADE "no home activity" IMPOSSIBLE — the column is NOT NULL,
        #   so the database refuses it rather than this command reporting it.
        #   What CAN still go wrong is a second activity that repeats the first,
        #   which is a typo rather than a second trade and would make the BOM
        #   search match the same material twice for one activity.
        missing, extra = [], []
        for material in Material.objects.select_related("home_activity", "also_used_in"):
            if material.home_activity_id is None:
                missing.append(material.code)
            elif material.also_used_in_id == material.home_activity_id:
                extra.append(f"{material.code} repeats {material.home_activity.abbreviation} "
                             f"as its second activity")
        if missing:
            self.bad(f"{len(missing)} materials have no home activity", missing)
        if extra:
            self.bad(f"{len(extra)} materials have more than one home activity", extra)
        if not missing and not extra:
            self.ok(f"all {Material.objects.count()} materials have exactly one home activity")

    def check_code_matches_its_group(self):
        """
        The middle segment of a code should be the material's group.

        A mismatch is NOT necessarily a fault — a code is frozen at creation, so
        a material reclassified afterwards keeps its old code on purpose. It is
        reported so you know it happened, not so you fix it.
        """
        odd = [f"{m.code} is now in group {m.group.code}"
               for m in Material.objects.select_related("group")
               if len(m.code.split("-")) == 3 and m.code.split("-")[1] != m.group.code]
        if odd:
            self.stdout.write(self.style.WARNING(
                f"  note  {len(odd)} codes name a group the material has since moved out of "
                f"(expected — codes are never regenerated)"))
            for example in odd[:5]:
                self.stdout.write(f"          {example}")
        else:
            self.ok("every code's group segment matches its current group")

    def check_no_duplicate_names(self):
        """Two materials with the same name and specification cannot be told apart."""
        from masters.imports import normalise
        seen, clashes = {}, []
        for material in Material.objects.all():
            key = normalise(f"{material.name}|{material.specification}")
            if key in seen:
                clashes.append(f"{material.code} and {seen[key]} — '{material.name}'")
            else:
                seen[key] = material.code
        if clashes:
            self.bad(f"{len(clashes)} pairs share a name and specification", clashes)
        else:
            self.ok("no two materials share a name and specification")

    # ----------------------------------------------------------------- vendor
    def check_every_vendor_has_a_phone(self):
        """A vendor's identity is their phone number. Without it there is none."""
        missing = list(Vendor.objects.filter(phone="").values_list("code", flat=True))
        if missing:
            self.bad(f"{len(missing)} vendors have no phone number", missing)
        else:
            self.ok(f"all {Vendor.objects.count()} vendors have a phone number")

    def check_gstins_look_valid(self):
        import re
        pattern = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][A-Z\d]Z[A-Z\d]$")
        bad = [f"{v.code} '{v.gst_number}'" for v in Vendor.objects.exclude(gst_number="")
               if not pattern.match(v.gst_number)]
        if bad:
            self.bad(f"{len(bad)} GSTINs are not in the right format", bad)
        else:
            captured = Vendor.objects.exclude(gst_number="").count()
            total = Vendor.objects.count()
            self.ok(f"{captured} of {total} vendors have a valid GSTIN"
                    + ("" if captured else " — none yet, so no PO can be issued"))

    # --------------------------------------------------------------- activity
    def check_abbreviations(self):
        bad = [a.name for a in Activity.objects.all()
               if not (a.abbreviation and len(a.abbreviation) == 3 and a.abbreviation.isupper())]
        if bad:
            self.bad(f"{len(bad)} activities have a bad abbreviation — no material can be "
                     f"coded under them", bad)
        else:
            self.ok(f"all {Activity.objects.count()} activities have a valid abbreviation")

    # -------------------------------------------------------------------- BOM
    def check_quantities_are_not_negative(self):
        bad = []
        for line in BomLine.objects.select_related("material"):
            for field in ("planned_qty", "stock_qty", "min_qty"):
                if getattr(line, field) < 0:
                    bad.append(f"{line.material.code} has {field} = {getattr(line, field)}")
        if bad:
            self.bad(f"{len(bad)} BOM quantities are negative", bad)
        else:
            self.ok(f"no negative quantities across {BomLine.objects.count()} BOM lines")

    def check_approved_orders_have_a_gstin(self):
        """
        An approved order was issued to a vendor, and cannot legally have been
        issued without their GSTIN. One without means approval was bypassed.

        ⚠⚠ EXCEPT FOR AN UNREGISTERED VENDOR, WHO HAS NO GSTIN AND NEVER WILL.
           `po_service.approve()` lets those through deliberately — see
           `ANCHOR: GSTIN-CAPTURE`, the hardware shop down the road — so an order
           to one is correct, not bypassed. Without this exclusion the check
           reported `PO-000003` to `VEN-LOCAL` as a problem, which is the worst
           thing an integrity check can do: cry wolf about a decision somebody
           made on purpose. Run it before go-live, see a FAIL that is not one,
           and the next real FAIL gets waved through too.

        ⚠ THE EXEMPTION IS THE VENDOR'S TICK, NOT A BLANK GSTIN. A registered
          vendor with no number on an issued order is still a genuine problem
          and still reported.
        """
        bad = list(PurchaseOrder.objects
                   .filter(vendor_gstin="")
                   .exclude(status=PurchaseOrder.Status.DRAFT)
                   .exclude(vendor__is_unregistered=True)
                   .values_list("number", flat=True))
        issued = PurchaseOrder.objects.exclude(status=PurchaseOrder.Status.DRAFT)
        exempt = issued.filter(vendor__is_unregistered=True).count()
        if bad:
            self.bad(f"{len(bad)} issued orders to a registered vendor have no GSTIN", bad)
        else:
            self.ok(f"all {issued.count() - exempt} issued orders to registered vendors "
                    f"carry a GSTIN"
                    + (f" ({exempt} to unregistered vendors, correctly without one)"
                       if exempt else ""))

    def check_receipts_belong_to_delivered_orders(self):
        """Material cannot have arrived against an order still sitting in draft."""
        from projects.bom_models import Receipt
        bad = list(Receipt.objects.filter(
            po_line__purchase_order__status=PurchaseOrder.Status.DRAFT
        ).values_list("po_line__purchase_order__number", flat=True).distinct())
        if bad:
            self.bad(f"{len(bad)} draft orders have material recorded against them", bad)
        else:
            self.ok(f"all {Receipt.objects.count()} receipts belong to issued orders")
