"""
A deliberately awkward set of test data, for finding out what the screens do at
the edges.

HOW TO RUN IT
    python manage.py seed_stress            build it
    python manage.py seed_stress --remove   take it all away again

WHAT IT IS FOR, AND HOW IT DIFFERS FROM seed_demo
    seed_demo builds one plausible project out of YOUR REAL materials, so you
    can look at something familiar.

    seed_stress builds its own dummy master data and three projects designed to
    be difficult: every activity used at once, an activity with no budget, a
    material on two activities, a line with no vendor, a rate of zero, stock
    above and below its threshold, a project with no BOM at all. The point is
    not that it looks realistic — it is that if a screen is going to behave
    oddly, it will do it here.

    It needs nothing imported first. That matters: it can be built, broken and
    thrown away without going anywhere near the real 705 materials.

EVERYTHING IT CREATES IS MARKED
    Material and group codes start ZZ, vendors are VEN-Z01 upwards, projects are
    PRJ-Z01 upwards. `--remove` deletes exactly those and nothing else, and says
    what it removed. If a delete is blocked because something real ended up
    pointing at a dummy row, it says that too rather than forcing it.

⚠ THIS WRITES TO WHATEVER DATABASE IT IS POINTED AT, including the real one.
    That is on purpose — the point is to try things on a real installation — but
    take the backup you would take before any other experiment.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import ProtectedError

from masters.codes import next_code
from masters.models import (Activity, Material, MaterialGroup, Vendor, VendorGroup,
                            VendorRate)
from projects.bom_models import Bom, BomLine, PurchaseOrder, Receipt
from projects.models import Estimate, EstimateLine, Project

D = Decimal

GROUP_PREFIX = "ZZ"
VENDOR_PREFIX = "VEN-Z"
PROJECT_PREFIX = "PRJ-Z"

# Three groups, because the third one is not a stock item — services are ordered
# but never held, and a reorder threshold on one would be meaningless.
GROUPS = [
    ("ZZ1", "TEST — general goods", True),
    ("ZZ2", "TEST — bulk materials", True),
    ("ZZ3", "TEST — services (not stocked)", False),
]

# Three vendors covering the three GST situations that change a purchase order:
# a Gujarat GSTIN (CGST + SGST), an out-of-state one (IGST), and none at all
# (approval must refuse).
VENDORS = [
    ("VEN-Z01", "TEST Gujarat Supplier", "9800000001", "24AAAAA0000A1Z5", "Cement, General"),
    ("VEN-Z02", "TEST Outstate Supplier", "9800000002", "27BBBBB1111B1Z5", "Steel"),
    ("VEN-Z03", "TEST No-GSTIN Supplier", "9800000003", "", "Sand / Aggregate"),
]


class Command(BaseCommand):
    help = "Create (or remove) awkward test data across every activity."

    def add_arguments(self, parser):
        parser.add_argument("--remove", action="store_true", help="Delete everything this command made.")

    def handle(self, *args, **options):
        if options["remove"]:
            return self.remove()
        if Project.objects.filter(code__startswith=PROJECT_PREFIX).exists():
            self.stdout.write(self.style.WARNING(
                "Stress data already exists. Run with --remove first to rebuild it."))
            return

        with transaction.atomic():
            groups = self.make_groups()
            vendors = self.make_vendors()
            materials = self.make_materials(groups)
            self.make_everything_project(materials, vendors)
            self.make_lopsided_project(materials, vendors)
            self.make_bomless_project()
            self.make_finished_projects()

        self.stdout.write(self.style.SUCCESS("\nStress data built."))
        self.stdout.write(
            "\nWhat to go and look at:"
            "\n  PRJ-Z01  every activity at once, including one with no reserve, a material on"
            "\n           two activities, a line with no vendor and a rate of zero"
            "\n  PRJ-Z02  a very large built-up area, so the reserve dwarfs the plan"
            "\n  PRJ-Z03  an estimate but no BOM — the Generate BOM path"
            "\n  PRJ-Z04  Completed, PRJ-Z05 Lost — neither shows until you change the filter"
            f"\n\nRemove it all with:  python manage.py seed_stress --remove")

    # ------------------------------------------------------------------ build
    def make_groups(self):
        groups = {}
        for code, name, stocked in GROUPS:
            groups[code], _ = MaterialGroup.objects.get_or_create(
                code=code, defaults={"name": name, "is_stock_item": stocked})
        self.stdout.write(f"  groups     {len(groups)}")
        return groups

    def make_vendors(self):
        """
        ⚠ SLICE 8: a vendor's classification is a GROUP on the vendor, not a row
          in the old VendorCategory table. That table still holds its rows so the
          migration can be checked against it, but nothing reads it — writing to
          it here would have produced test data that looked right and did nothing.
        """
        vendors = []
        for code, name, phone, gstin, category in VENDORS:
            group, _ = VendorGroup.objects.get_or_create(name=category)
            vendor, _ = Vendor.objects.get_or_create(
                code=code,
                defaults={"name": name, "phone": phone, "gst_number": gstin, "group": group})
            if vendor.group_id is None:
                vendor.group = group
                vendor.save(update_fields=["group"])
            vendors.append(vendor)
        self.stdout.write(f"  vendors    {len(vendors)} — one Gujarat, one out-of-state, one with no GSTIN")
        return vendors

    def make_materials(self, groups):
        """
        One material in EVERY activity, plus three awkward extras.

        Codes come from masters.codes.next_code, the same generator the import
        uses, so they look like real codes and take real serials.

        ⚠ SLICE 8: a material's trade is `home_activity` (required) and
          `also_used_in` (optional), both columns on the material. The old
          MaterialActivity table is dead — writing to it here produced materials
          with no trade at all, which is why this command crashed with
          `NOT NULL constraint failed: masters_material.home_activity_id`.
          367 tests passed while it was broken, because no test calls it.
        """
        made = []
        for activity in Activity.objects.filter(is_active=True).order_by("sort_order"):
            group = groups["ZZ1"]
            material = Material.objects.create(
                code=next_code(activity, group), name=f"TEST MATERIAL — {activity.name}",
                group=group, specification="ZZ TEST", uom="Nos",
                estimation_rate=D("100.00"), gst_percent=D("18"),
                home_activity=activity)
            made.append(material)

        first = Activity.objects.filter(is_active=True).order_by("sort_order").first()
        second = Activity.objects.filter(is_active=True).order_by("sort_order")[1]

        # A common material: belongs to one activity, offered under all of them.
        common = Material.objects.create(
            code=next_code(first, groups["ZZ1"]), name="TEST COMMON — used by every trade",
            group=groups["ZZ1"], uom="Packet", estimation_rate=D("12.50"),
            gst_percent=D("18"), is_common=True, home_activity=first)

        # A material with NO estimation rate. Variance against it cannot be
        # calculated — the screen must show that, not divide by zero.
        rateless = Material.objects.create(
            code=next_code(first, groups["ZZ2"]), name="TEST NO RATE — nobody has priced this",
            group=groups["ZZ2"], uom="Cum", estimation_rate=D("0"), gst_percent=D("5"),
            home_activity=first)

        # ⚠ A material on TWO activities. It no longer tests a double-count bug —
        #   that turned out not to be one — but it is exactly the case the stock
        #   echo warning exists for: the same material holding site stock on two
        #   lines of one BOM, which is either an allocation or one pile typed
        #   twice, and only a person can tell.
        shared = Material.objects.create(
            code=next_code(first, groups["ZZ2"]), name="TEST SHARED — on two activities at once",
            group=groups["ZZ2"], uom="Bag", estimation_rate=D("289.06"), gst_percent=D("28"),
            home_activity=first, also_used_in=second)

        # A service: ordered, never stocked, taxed differently.
        service = Material.objects.create(
            code=next_code(first, groups["ZZ3"]), name="TEST SERVICE — transport, never stocked",
            group=groups["ZZ3"], uom="Trip", estimation_rate=D("1850.00"), gst_percent=D("5"),
            home_activity=first)

        self.stdout.write(f"  materials  {len(made)} (one per activity) + common, rateless, shared, service")
        return {"per_activity": made, "common": common, "rateless": rateless,
                "shared": shared, "service": service, "first": first, "second": second}

    def make_everything_project(self, materials, vendors):
        """
        PRJ-Z01 — every activity in use at once, and every awkward line on it.
        """
        project = Project.objects.create(
            code=f"{PROJECT_PREFIX}01", name="TEST — every activity at once",
            location="Nowhere", bua_sqft=D("10000"), floors="G+3", status=Project.Status.WON)
        estimate = Estimate.objects.create(project=project)

        activities = list(Activity.objects.filter(is_active=True).order_by("sort_order"))
        # One activity is deliberately LEFT OFF the estimate, so its lines have a
        # reserve of zero. That is the "spend against something nobody quoted"
        # case, and it must stay visible rather than disappear.
        for activity in activities[:-1]:
            EstimateLine.objects.create(estimate=estimate, name=activity.name, rate=activity.rate,
                                        gst_percent=activity.gst_percent, basis=activity.basis,
                                        sort_order=activity.sort_order)

        bom = Bom.objects.create(project=project)
        gujarat, outstate, no_gstin = vendors
        count = 0

        for index, material in enumerate(materials["per_activity"]):
            activity = material.home_activity
            # Stock alternates above and below the threshold. A flag that fires
            # on every row tells you nothing — that was a real bug in the mock.
            below = index % 3 == 0
            BomLine.objects.create(
                bom=bom, activity=activity, material=material,
                planned_qty=D("500"), stock_qty=D("20") if below else D("200"),
                min_qty=D("100"), vendor=[gujarat, outstate, no_gstin][index % 3],
                vendor_rate=D("100.00") + index, sort_order=count)
            count += 1

        first, second = materials["first"], materials["second"]

        # No vendor: nothing wrong with it, it is simply not ready to order.
        BomLine.objects.create(bom=bom, activity=first, material=materials["common"],
                               planned_qty=D("1000"), min_qty=D("0"), sort_order=count)
        count += 1

        # No rate anywhere: variance has nothing to compare against.
        BomLine.objects.create(bom=bom, activity=first, material=materials["rateless"],
                               planned_qty=D("40"), vendor=gujarat, sort_order=count)
        count += 1

        # The same material on two activities, each subtracting the same stock.
        for activity in (first, second):
            BomLine.objects.create(bom=bom, activity=activity, material=materials["shared"],
                                   planned_qty=D("600"), stock_qty=D("200"), min_qty=D("150"),
                                   vendor=gujarat, vendor_rate=D("292.97"),
                                   remark=f"shared — {activity.abbreviation} half", sort_order=count)
            count += 1

        # The same material TWICE on ONE activity, which is allowed and real.
        BomLine.objects.create(bom=bom, activity=first, material=materials["shared"],
                               planned_qty=D("450"), stock_qty=D("200"), min_qty=D("150"),
                               vendor=outstate, vendor_rate=D("285.00"),
                               remark="second pour — separate line", sort_order=count)
        count += 1

        # An override that is deliberately larger than the suggestion.
        BomLine.objects.create(bom=bom, activity=first, material=materials["service"],
                               planned_qty=D("30"), order_qty_override=D("50"),
                               vendor=no_gstin, vendor_rate=D("1900.00"), sort_order=count)
        count += 1

        self.stdout.write(f"  {project.code}   {count} BOM lines across {len(activities)} activities "
                          f"· one activity has no reserve")
        return project

    def make_lopsided_project(self, materials, vendors):
        """
        PRJ-Z02 — a huge built-up area against a tiny plan, so every percentage
        is very small, and one line planned far beyond its reserve so one is very
        large. Both ends of the bar at once.
        """
        project = Project.objects.create(
            code=f"{PROJECT_PREFIX}02", name="TEST — very large area, very small plan",
            location="Nowhere", bua_sqft=D("250000"), floors="G+30", status=Project.Status.WON)
        estimate = Estimate.objects.create(project=project)

        first, second = materials["first"], materials["second"]
        EstimateLine.objects.create(estimate=estimate, name=first.name, rate=first.rate,
                                    gst_percent=first.gst_percent, sort_order=first.sort_order)
        # A rate of ZERO on the estimate: the activity is on the project but has
        # no budget, so percent-used has nothing to divide by.
        EstimateLine.objects.create(estimate=estimate, name=second.name, rate=D("0"),
                                    gst_percent=second.gst_percent, sort_order=second.sort_order)

        bom = Bom.objects.create(project=project)
        BomLine.objects.create(bom=bom, activity=first, material=materials["per_activity"][0],
                               planned_qty=D("5"), vendor=vendors[0], vendor_rate=D("100"))
        BomLine.objects.create(bom=bom, activity=second, material=materials["per_activity"][1],
                               planned_qty=D("900000"), vendor=vendors[1], vendor_rate=D("100"))
        self.stdout.write(f"  {project.code}   2 lines · one activity budgeted at zero")
        return project

    def make_bomless_project(self):
        """PRJ-Z03 — an estimate and no BOM, and it is not Won either."""
        project = Project.objects.create(
            code=f"{PROJECT_PREFIX}03", name="TEST — quoted, no BOM yet",
            location="Nowhere", bua_sqft=D("5000"), status=Project.Status.QUOTED)
        estimate = Estimate.objects.create(project=project)
        for activity in Activity.objects.filter(is_active=True).order_by("sort_order")[:3]:
            EstimateLine.objects.create(estimate=estimate, name=activity.name, rate=activity.rate,
                                        gst_percent=activity.gst_percent, sort_order=activity.sort_order)
        self.stdout.write(f"  {project.code}   estimate only, status Quoted")
        return project

    def make_finished_projects(self):
        """
        PRJ-Z04 Completed and PRJ-Z05 Lost — the two that should NOT be in the
        default view. Without them the project filter has nothing to prove.
        """
        Project.objects.create(
            code=f"{PROJECT_PREFIX}04", name="TEST — finished last year",
            location="Nowhere", bua_sqft=D("8000"), status=Project.Status.COMPLETED)
        Project.objects.create(
            code=f"{PROJECT_PREFIX}05", name="TEST — quoted and lost",
            location="Nowhere", bua_sqft=D("3000"), status=Project.Status.LOST)
        self.stdout.write(f"  {PROJECT_PREFIX}04   Completed · {PROJECT_PREFIX}05   Lost "
                          f"— both out of the default project view")

    # ----------------------------------------------------------------- remove
    def remove(self):
        """
        Take it all away, in dependency order, and say what happened.

        ⚠ RECEIPTS HAVE TO GO FIRST, and that is worth knowing about the real
        system too. A Receipt protects the purchase-order line it was booked
        against, which protects the order, which protects the project. So once
        anything has been marked Delivered, THAT PROJECT CAN NEVER BE DELETED —
        the database refuses, all the way up the chain.

        That is defensible for real work (material that arrived on site is not
        a mistake you can erase) but it is absolute: there is no archive, no
        deactivate, no override. Only test data gets this treatment here.
        """
        projects = Project.objects.filter(code__startswith=PROJECT_PREFIX)
        orders = PurchaseOrder.objects.filter(project__in=projects)
        receipts = Receipt.objects.filter(po_line__purchase_order__in=orders)
        counts = {"receipts": receipts.count(),
                  "purchase orders": orders.count(),
                  "projects": projects.count()}
        receipts.delete()
        orders.delete()
        projects.delete()                       # cascades to estimate, BOM and its lines

        materials = Material.objects.filter(code__contains="-ZZ")
        blocked = []
        removed = 0
        for material in materials:
            try:
                material.delete()
                removed += 1
            except ProtectedError:
                blocked.append(material.code)
        counts["materials"] = removed

        counts["vendors"] = Vendor.objects.filter(code__startswith=VENDOR_PREFIX).count()
        VendorRate.objects.filter(vendor__code__startswith=VENDOR_PREFIX).delete()
        Vendor.objects.filter(code__startswith=VENDOR_PREFIX).delete()

        groups = MaterialGroup.objects.filter(code__startswith=GROUP_PREFIX)
        counts["groups"] = groups.count()
        groups.delete()

        for label, number in counts.items():
            self.stdout.write(f"  removed {number} {label}")
        if blocked:
            self.stdout.write(self.style.WARNING(
                f"\n  {len(blocked)} material(s) could NOT be removed because something outside the "
                f"test data points at them: {', '.join(blocked)}."
                f"\n  That is the delete rule working. Deactivate them instead, or remove whatever "
                f"is using them first."))
        self.stdout.write(self.style.SUCCESS("\nStress data removed."))
