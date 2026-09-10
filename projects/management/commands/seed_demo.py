"""
Builds a demo project so there is something to click through before the real
screens exist.

HOW TO RUN IT
    python manage.py seed_demo              create it
    python manage.py seed_demo --remove     delete it again

    Needs the master data imported first — it uses your real materials and
    vendors rather than inventing any.

WHAT IT CREATES
    A project (PRJ-DEMO), its BOQ across every trade, and a BOM with real
    materials under RCC, Masonry, Doors & Windows, Electrical and Common —
    the same shape as BOM_Prototype.html.

WHY IT EXISTS
    Two reasons. You can see the real structure in Admin now instead of waiting
    for the BOM screen. And when something looks wrong, we can both look at the
    same numbers rather than describing them to each other.

IT IS OBVIOUSLY DEMO DATA
    The project code is PRJ-DEMO and its name says so. One command removes it,
    and removal touches nothing else. It is never created automatically.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from masters.models import Material, Vendor
from projects.bom_models import Bom, BomLine
from projects.models import Activity, Estimate, EstimateLine, Project

D = Decimal
DEMO_CODE = "PRJ-DEMO"
BUA = D("26545")        # Bhudarpura's built-up area, so the numbers are familiar

# activity abbreviation -> how many of its materials to put on the BOM.
# Planned quantities are derived from the built-up area so they stay plausible
# rather than being invented twice.
SHAPE = [("RCC", 12), ("MAS", 5), ("DRW", 8), ("ELE", 9), ("COM", 8)]


class Command(BaseCommand):
    help = "Create (or remove) a demo project with a BOQ and a BOM."

    def add_arguments(self, parser):
        parser.add_argument("--remove", action="store_true", help="Delete the demo project.")

    def handle(self, *args, **options):
        if options["remove"]:
            return self.remove()

        if Project.objects.filter(code=DEMO_CODE).exists():
            self.stdout.write(self.style.WARNING(
                f"{DEMO_CODE} already exists. Run with --remove first to rebuild it."))
            return

        if not Material.objects.exists():
            self.stdout.write(self.style.ERROR(
                "No materials in the database. Run import_masters first — this command uses "
                "your real materials rather than inventing any."))
            return

        with transaction.atomic():
            project = self.create_project()
            self.create_estimate(project)
            lines = self.create_bom(project)

        self.stdout.write(self.style.SUCCESS(
            f"\nCreated {DEMO_CODE} with {lines} BOM lines across {len(SHAPE)} activities."))
        self.stdout.write(
            "\nLook at it in Admin under Projects, BOMs and BOM lines."
            f"\nRemove it with:  python manage.py seed_demo --remove")

    # ------------------------------------------------------------------------
    def create_project(self):
        project = Project.objects.create(
            code=DEMO_CODE, name="DEMO — Bhudarpura (sample data, safe to delete)",
            location="Ahmedabad", bua_sqft=BUA, floors="G+7",
            status=Project.Status.WON,     # Won, so a BOM may exist
        )
        self.stdout.write(f"  project   {project.code} · {BUA:,.0f} sqft")
        return project

    def create_estimate(self, project):
        """
        The BOQ. Every trade at its master rate — the composite that produced
        Bhudarpura's real cost per sqft.
        """
        estimate = Estimate.objects.create(project=project)
        trades = Activity.objects.exclude(abbreviation="COM").filter(is_active=True)
        for activity in trades:
            EstimateLine.objects.create(
                estimate=estimate, name=activity.name, rate=activity.rate,
                gst_percent=activity.gst_percent, basis=activity.basis,
                sort_order=activity.sort_order)
        self.stdout.write(f"  estimate  {trades.count()} trades · "
                          f"Rs {estimate.composite_rate:,.0f}/sqft · "
                          f"Rs {estimate.grand_total:,.0f} all in")
        return estimate

    def create_bom(self, project):
        """
        A BOM using real materials. Planned quantities are scaled from the
        built-up area so they are plausible; stock and thresholds are set so
        that a few lines flag for reorder and most do not — a flag that fires
        on every row tells you nothing.
        """
        bom = Bom.objects.create(project=project)
        vendors = list(Vendor.objects.filter(is_active=True).order_by("code")[:12])
        total = 0

        for abbreviation, wanted in SHAPE:
            activity = Activity.objects.filter(abbreviation=abbreviation).first()
            if activity is None:
                continue

            # ⚠ home_activity, not the dead link table — see BOM-MATERIAL-FILTER.
            materials = list(Material.objects.filter(
                home_activity=activity, is_active=True
            ).select_related("group").order_by("code")[:wanted])

            for index, material in enumerate(materials):
                planned = self.plausible_quantity(material)
                # Roughly a fifth of lines sit below their threshold.
                low = index % 5 == 0
                stock = (planned * D("0.05")).quantize(D("0.001"))
                minimum = stock * (D("2") if low else D("0.5"))

                BomLine.objects.create(
                    bom=bom, activity=activity, material=material,
                    planned_qty=planned, stock_qty=stock, min_qty=minimum,
                    vendor=vendors[index % len(vendors)] if vendors else None,
                    # A little above and below the benchmark, so the variance
                    # column shows both colours.
                    vendor_rate=(material.estimation_rate or D("0")) *
                                (D("1.02") if index % 3 else D("0.97")),
                    remark="footing & plinth" if index == 0 else "",
                    sort_order=index,
                )
                total += 1

            self.stdout.write(f"  {abbreviation:<9} {len(materials)} materials")

        return total

    @staticmethod
    def plausible_quantity(material):
        """
        A believable planned quantity for this material's unit.

        Not accurate estimating — just enough that the screen reads like a real
        project rather than showing 100 of everything.
        """
        by_uom = {
            "Bag": D("1200"), "Cum": D("1150"), "MT": D("50"), "Kg": D("950"),
            "Trip": D("150"), "Metre": D("4200"), "Sqft": D("2600"), "Sqm": D("240"),
            "Box": D("180"), "Tin": D("40"), "Packet": D("300"), "Bundle": D("60"),
            "Litre": D("400"), "Hour": D("80"), "KW": D("25"), "Lumpsum": D("1"),
        }
        return by_uom.get(material.uom, D("500"))

    # ------------------------------------------------------------------------
    def remove(self):
        project = Project.objects.filter(code=DEMO_CODE).first()
        if project is None:
            self.stdout.write(f"{DEMO_CODE} is not there — nothing to remove.")
            return

        with transaction.atomic():
            # Purchase orders raised against the demo have to go first, since
            # BOM lines are protected while anything points at them.
            for order in project.purchase_orders.all():
                order.lines.all().delete()
                order.delete()
            if hasattr(project, "bom"):
                project.bom.lines.all().delete()
                project.bom.delete()
            project.delete()

        self.stdout.write(self.style.SUCCESS(
            f"Removed {DEMO_CODE}. Master data is untouched."))
