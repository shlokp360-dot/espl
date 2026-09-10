"""
A complete, plausible system in one command — for showing somebody the app.

HOW TO RUN IT
    python manage.py seed_showcase              build it
    python manage.py seed_showcase --remove     take it all away again

⚠ IT NEEDS NOTHING IMPORTED FIRST. No spreadsheets, no master data, no `.env`.
    That is the whole point: somebody who has just cloned the repository has an
    empty database and no client files, because none of that is committed. One
    command has to be enough or they see six empty screens and form a view.

HOW IT DIFFERS FROM THE OTHER TWO SEEDERS

    seed_demo      one project built from YOUR REAL 705 materials. Needs the
                   spreadsheets imported first. For looking at something familiar.
    seed_stress    deliberately awkward data — zero rates, missing vendors, an
                   activity with no budget. For finding out what breaks.
    seed_showcase  THIS ONE. Plausible and complete: three sites, five months of
                   purchase orders at every stage, work that is partly done and
                   partly late, and a compliance file with documents that are
                   valid, expiring and expired. For a demonstration.

⚠ EVERY SCREEN IS MEANT TO HAVE SOMETHING ON IT. That is the acceptance test for
    this command, and the reason it writes orders across five different months
    with real payment dates: an analytics page with one document on it looks
    broken even when it is correct.

EVERYTHING IT CREATES IS MARKED AND REMOVABLE
    Projects are named "Showcase — …", materials sit in group SHW, vendors are
    VEN-S01 upwards, demo people have user IDs ending ".demo". `--remove`
    deletes exactly those and nothing else.

⚠ IT WRITES TO WHATEVER DATABASE IT IS POINTED AT. On a real installation that
    is fine — everything is prefixed and one flag removes it — but read the
    summary it prints before assuming.
"""
import random
from datetime import date, timedelta
from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import Role, UserProfile
from compliance.models import (
    ComplianceDocument, ComplianceItem, ComplianceType, Kind, ProjectCompliance,
)
from masters.models import Activity, Material, MaterialGroup, Vendor
from projects.bom_models import Bom, BomLine, PurchaseOrder, PurchaseOrderLine, Receipt
from projects.models import Estimate, EstimateLine, Project
from tasks.models import DelayReason, Subtask, TaskHeader

MARK = "Showcase — "
GROUP_CODE = "SHW"
VENDOR_PREFIX = "VEN-S"
USER_SUFFIX = ".demo"

#: ⚠ A FIXED SEED. Two people running this on two laptops should be looking at
#:   the same numbers — otherwise "the figure on my screen" and "the figure on
#:   yours" become different conversations.
SEED = 20260814

SITES = [
    ("Bhudarpura Residency", D("26545"), True),      # RERA applies
    ("Shilaj Villas", D("18400"), False),
    ("Prahladnagar Heights", D("41200"), True),
]

#: ⚠ C7. The first three of these used to be the actual names of real vendors
#:   from VENDOR_MASTER.xlsx — the seeder was written by copying real rows out
#:   of the master, and "Sambhav Hardware" collided on phone number too. Names
#:   here now stay obviously fictitious on purpose, the same way `ZZDMY` makes
#:   a dummy GSTIN unmistakable — a demo vendor should never be confusable with
#:   a real one, even before you check the phone number.
VENDORS = [
    ("Utkarsh Hardware Stores", "9409124489", "30 days"),
    ("Meghdoot Traders", "9825315844", "45 days"),
    ("Girnar Steel", "9898112233", "15 days"),
    ("Nakoda Cement", "9033445566", ""),             # no terms — the 30-day default
    ("Shreeji Electricals", "9727889900", "60 days"),
    ("Patel Plumbing Works", "9714455667", "30 days"),
]

PEOPLE = [
    ("ramesh.demo", "Ramesh Mistry", Role.SITE),
    ("priya.demo", "Priya Shah", Role.PROJECT_MANAGER),
    ("nilesh.demo", "Nilesh Patel", Role.PURCHASE),
    ("hetal.demo", "Hetal Desai", Role.ACCOUNTANT),
    ("bhavna.demo", "Bhavna Joshi", Role.COMPLIANCE),
]

PACKAGES = [
    ("Earthing", [("Dig earth pits", 6), ("Lay copper plates", 5), ("Test continuity", 3)]),
    ("Slab shuttering — 3rd floor", [("Erect props", 8), ("Ply and beams", 10),
                                     ("Level check", 4)]),
    ("Plumbing rough-in", [("Sleeve marking", 4), ("First fix pipework", 12),
                           ("Pressure test", 2)]),
    ("Internal plaster", [("Scaffold", 5), ("Base coat", 14), ("Finish coat", 9)]),
]


class Command(BaseCommand):
    help = "Build (or remove) a complete demonstration dataset. Needs nothing imported first."

    def add_arguments(self, parser):
        parser.add_argument("--remove", action="store_true",
                            help="Delete everything this command created, and nothing else.")

    def handle(self, *args, **options):
        if options["remove"]:
            return self.remove()
        self.build()

    # ------------------------------------------------------------------ build
    @transaction.atomic
    def build(self):
        random.seed(SEED)
        today = timezone.localdate()
        self.made = {}

        if Project.objects.filter(name__startswith=MARK).exists():
            self.stdout.write(self.style.WARNING(
                "Showcase data is already here. Run with --remove first if you want it fresh."))
            return

        activities = list(Activity.objects.filter(is_active=True)[:6])
        if not activities:
            self.stdout.write(self.style.ERROR(
                "No activities in the database. Run `python manage.py migrate` first."))
            return

        people = self.people()
        vendors = self.vendors()
        materials = self.materials(activities)
        projects = self.projects(activities)

        self.orders(projects, vendors, materials, people, today)
        self.work(projects, activities, people, today)
        self.compliance(projects, people, today)
        self.promote_superusers()

        self.report(today)

    # ---- the people ------------------------------------------------------
    def people(self):
        """
        Five demo colleagues, so screens that show a name have one to show.

        ⚠ THEY CANNOT SIGN IN. `set_unusable_password()` — a demo account with a
          known password on somebody's laptop is a habit worth not starting. The
          person running this signs in as their own superuser.
        """
        User = get_user_model()
        made = {}
        for username, name, role in PEOPLE:
            first, _, last = name.partition(" ")
            user = User.objects.create(username=username, first_name=first, last_name=last)
            user.set_unusable_password()
            user.save()
            UserProfile.objects.update_or_create(
                user=user, defaults={"role": role, "must_change_password": False})
            made[role] = made.get(role) or user
            made[username] = user
        self.made["people"] = len(PEOPLE)
        return made

    def promote_superusers(self):
        """
        ⚠ THE TRAP THIS AVOIDS: `createsuperuser` makes an account with NO
          PROFILE, and the permission matrix answers "no role" with an almost
          empty launchpad. Somebody demonstrating the app then concludes it is
          broken. Any superuser without a profile becomes an Admin here, and the
          summary says so out loud rather than doing it quietly.
        """
        User = get_user_model()
        promoted = []
        for user in User.objects.filter(is_superuser=True):
            profile, created = UserProfile.objects.get_or_create(
                user=user, defaults={"role": Role.ADMIN, "must_change_password": False})
            if created:
                promoted.append(user.get_username())
        self.made["promoted"] = promoted

    # ---- masters ---------------------------------------------------------
    def vendors(self):
        """⚠ C7: these six numbers are invented, but `phone` is unique and a real
        vendor from import_masters can legitimately already hold one of them —
        it happened with Sambhav Hardware. Rather than trust that this list will
        never again coincide with whatever's in the real master, nudge the last
        digit until the number is free before creating the row.
        """
        rows = []
        for index, (name, phone, terms) in enumerate(VENDORS, start=1):
            if Vendor.objects.filter(phone=phone).exists():
                for bump in range(1, 10):
                    candidate = phone[:-1] + str((int(phone[-1]) + bump) % 10)
                    if not Vendor.objects.filter(phone=candidate).exists():
                        phone = candidate
                        break
            rows.append(Vendor.objects.create(code=f"{VENDOR_PREFIX}{index:02d}", name=name,
                                              phone=phone, payment_terms=terms))
        self.made["vendors"] = len(rows)
        return rows

    def materials(self, activities):
        """Two materials per trade — enough for a BOM that reads like a real one."""
        group = MaterialGroup.objects.create(code=GROUP_CODE, name="Showcase materials")
        names = ["OPC 53 CEMENT", "TMT BAR 12MM", "AAC BLOCK 600x200x150", "RIVER SAND",
                 "PVC PIPE 110MM", "COPPER WIRE 2.5SQMM", "WHITE CEMENT", "PRIMER",
                 "SWITCH SOCKET 6A", "CP FITTING SET", "TILE ADHESIVE", "WATERPROOF MEMBRANE"]
        rates = ["420", "56200", "78", "1150", "310", "2450", "640", "285",
                 "190", "3400", "560", "1850"]
        uoms = ["Bag", "MT", "Nos", "Cum", "Nos", "Coil", "Bag", "Ltr", "Nos", "Set", "Bag", "Sqm"]

        rows = []
        for index, activity in enumerate(activities):
            for offset in (0, 1):
                slot = (index * 2 + offset) % len(names)
                rows.append(Material.objects.create(
                    code=f"{activity.abbreviation}-{GROUP_CODE}-{slot:03d}",
                    name=names[slot], group=group, uom=uoms[slot],
                    estimation_rate=D(rates[slot]), gst_percent=D("18"),
                    home_activity=activity))
        self.made["materials"] = len(rows)
        return rows

    # ---- projects, estimates, bills of materials -------------------------
    def projects(self, activities):
        out = []
        for name, area, _rera in SITES:
            project = Project.objects.create(
                name=f"{MARK}{name}", bua_sqft=area, status=Project.Status.WON,
                location="Ahmedabad",
                billing_address="Elegance Skyz Pvt Ltd, Ahmedabad",
                site_address=f"{name}, Ahmedabad")

            estimate = Estimate.objects.create(project=project)
            for activity in activities:
                EstimateLine.objects.create(
                    estimate=estimate, name=activity.name,
                    rate=activity.rate or D("120"), gst_percent=D("18"))
            out.append(project)

        self.made["projects"] = len(out)
        return out

    def boms(self, project, activities, vendors, materials):
        bom = Bom.objects.create(project=project)
        lines = []
        for material in materials:
            # ⚠ Planned quantity scaled to the built-up area, so a bigger site
            #   really does carry a bigger bill — otherwise every project shows
            #   the same numbers and the comparison screens say nothing.
            scale = float(project.bua_sqft) / 26545
            planned = D(str(round(random.randint(180, 900) * scale)))
            vendor = random.choice(vendors)
            lines.append(BomLine.objects.create(
                bom=bom, activity=material.home_activity, material=material,
                planned_qty=planned,
                stock_qty=D(str(random.choice([0, 0, 0, 25, 60]))),
                vendor=vendor,
                vendor_rate=(material.estimation_rate *
                             D(random.choice(["0.94", "1", "1", "1.06", "1.18"])))
                            .quantize(D("0.01"))))
        return lines

    # ---- the money -------------------------------------------------------
    def orders(self, projects, vendors, materials, people, today):
        """
        Five months of documents at every stage.

        ⚠ THE DATES ARE THE POINT. Every analytics figure counts on a different
          one — committed on approval, received on delivery, paid on payment —
          so a seeder that stamped them all with today would light up one column
          and leave every chart flat.
        """
        activities = {material.home_activity for material in materials}
        start = date(today.year if today.month >= 4 else today.year - 1, 4, 1)
        raised = PurchaseOrder.objects.count()
        counts = {"draft": 0, "approved": 0, "delivered": 0, "paid": 0}

        for project in projects:
            lines = self.boms(project, activities, vendors, materials)
            for line in lines:
                for _ in range(random.randint(1, 3)):
                    raised += 1
                    approved_on = start + timedelta(days=random.randint(0, (today - start).days - 20))
                    delivered_on = approved_on + timedelta(days=random.randint(4, 26))
                    paid_on = delivered_on + timedelta(days=random.randint(10, 55))

                    stage = random.choices(["draft", "approved", "delivered", "paid"],
                                           [2, 3, 4, 6])[0]
                    if stage == "paid" and paid_on > today:
                        stage = "delivered"
                    if stage == "delivered" and delivered_on > today:
                        stage = "approved"

                    order = PurchaseOrder.objects.create(
                        number=f"PO-{raised:06d}", project=project, vendor=line.vendor,
                        status=stage,
                        # ⚠ required_by IS SET HERE, and it is the field that is
                        #   empty on every real document today — without it the
                        #   vendor scorecard cannot exist. See OPEN-BEFORE-GO-LIVE.
                        required_by=delivered_on - timedelta(days=random.randint(0, 6)),
                        deduction_pct=D(random.choice(["0", "0", "0", "1.5", "2"])),
                        tds_pct=D(random.choice(["0", "0", "1", "2"])),
                        tds_section=random.choice(["", "194C", "194Q"]),
                        approved_at=_at(approved_on) if stage != "draft" else None,
                        approved_by=people.get(Role.PROJECT_MANAGER) if stage != "draft" else None,
                        delivered_at=_at(delivered_on) if stage in ("delivered", "paid") else None,
                        delivered_by=people.get(Role.SITE) if stage in ("delivered", "paid") else None,
                        paid_at=_at(paid_on) if stage == "paid" else None,
                        paid_by=people.get(Role.ACCOUNTANT) if stage == "paid" else None,
                        created_by=people.get(Role.PURCHASE))

                    quantity = (line.planned_qty / D(random.randint(3, 8))).quantize(D("0.01"))
                    po_line = PurchaseOrderLine.objects.create(
                        purchase_order=order, bom_line=line, quantity=quantity,
                        rate=line.vendor_rate, gst_percent=D("18"),
                        discount_pct=D(random.choice(["0", "0", "2.5", "5"])))

                    if stage in ("delivered", "paid"):
                        Receipt.objects.create(
                            po_line=po_line, quantity=quantity,
                            received_on=delivered_on, source="showcase")
                    counts[stage] += 1

        self.made["orders"] = counts

    # ---- the work --------------------------------------------------------
    def work(self, projects, activities, people, today):
        """
        Packages part done, part late, one blocked, one replanned.

        ⚠ EVERY STATE THE BOARD CAN SHOW APPEARS SOMEWHERE, including the two
          that are easy to forget: a subtask finished late with a reason, and one
          whose dates a manager moved. A demo where everything is green teaches
          nobody what the screen is for.
        """
        made = {"headers": 0, "subtasks": 0, "late": 0, "blocked": 0, "replanned": 0}

        for project in projects:
            start = today - timedelta(days=random.randint(40, 70))
            for index, (name, subtasks) in enumerate(PACKAGES):
                activity = activities[index % len(activities)]
                header = TaskHeader.objects.create(
                    project=project, activity=activity, name=name,
                    owner=people.get(Role.PROJECT_MANAGER),
                    start=start + timedelta(days=index * 12), days=random.randint(16, 30),
                    created_by=people.get(Role.PROJECT_MANAGER))
                made["headers"] += 1

                cursor = header.start
                for position, (title, days) in enumerate(subtasks):
                    subtask = Subtask.objects.create(
                        header=header, title=title,
                        assignee=people.get(Role.SITE) if position % 2 == 0
                                 else people.get(Role.PROJECT_MANAGER),
                        start=cursor, days=days,
                        priority=random.choice([Subtask.Priority.NORMAL, Subtask.Priority.NORMAL,
                                                Subtask.Priority.HIGH]),
                        created_by=people.get(Role.PROJECT_MANAGER))
                    made["subtasks"] += 1
                    cursor = cursor + timedelta(days=days)

                    if subtask.planned_end < today - timedelta(days=5):
                        late = random.choice([0, 0, 2, 4, 7])
                        subtask.status = Subtask.Status.DONE
                        subtask.finished_on = subtask.planned_end + timedelta(days=late)
                        if late:
                            subtask.delay_reason = random.choice(list(DelayReason.values))
                            subtask.delay_note = "Recorded on site."
                            made["late"] += 1
                        subtask.save()

            # ⚠ BLOCKED AND REPLANNED ARE FORCED AFTERWARDS, NOT CHOSEN INSIDE
            #   THE LOOP. They used to sit in an `elif` after "is it already past
            #   due", and because the packages start six weeks ago almost
            #   everything was done by the time that branch was reached — the
            #   seeder printed "0 blocked" and a demonstration never showed the
            #   state. Picking from what is genuinely still open guarantees both.
            still_open = list(Subtask.objects.filter(
                header__project=project, status=Subtask.Status.OPEN).order_by("start"))

            if still_open:
                stuck = still_open.pop()
                stuck.status = Subtask.Status.BLOCKED
                stuck.blocked_reason = DelayReason.TRADE
                stuck.blocked_note = "Carpenter gang on the other tower."
                stuck.save()
                made["blocked"] += 1

            if still_open:
                # a manager moved the plan, and the first promise is kept
                moved = still_open.pop()
                moved.original_start, moved.original_days = moved.start, moved.days
                moved.start = moved.start + timedelta(days=9)
                moved.shift_reason = DelayReason.SCOPE
                moved.shift_note = "Bathroom layout revised."
                moved.save()
                made["replanned"] += 1

            # ⚠ NO SEPARATE MILESTONE ROWS ANY MORE. A milestone IS a header
            #   task now — see the note where the model used to be in
            #   tasks/models.py — so the packages seeded above already are the
            #   milestones this project is judged on.
        self.made["work"] = made

    # ---- the compliance file --------------------------------------------
    def compliance(self, projects, people, today):
        """
        Documents that are valid, expiring, expired and replaced.

        ⚠ THE FOUR STATES HAVE TO BE VISIBLE OR THE SCREEN LOOKS LIKE A LIST OF
          TICKS. Expired is the state the whole module exists to prevent, so at
          least one of them is deliberately three weeks past its date.
        """
        made = {"documents": 0, "expiring": 0, "expired": 0, "replaced": 0}
        amc = ComplianceType.objects.filter(code="AMC").first()
        rera = ComplianceType.objects.filter(code="RERA").first()
        if amc is None:
            self.stdout.write(self.style.WARNING(
                "No compliance checklist found — run `migrate` and try again."))
            return

        for project, (_name, _area, has_rera) in zip(projects, SITES):
            if has_rera and rera:
                ProjectCompliance.objects.create(
                    project=project, type=rera, applicable=True,
                    decided_by=people.get(Role.COMPLIANCE))

            items = list(ComplianceItem.objects.filter(title__type=amc, is_active=True))
            for position, item in enumerate(items):
                if position % 4 == 3:
                    continue                      # leave a quarter of them Missing
                expires = None
                if item.kind == Kind.VALID:
                    offset = [420, 38, -21, 260][position % 4]
                    expires = today + timedelta(days=offset)
                    if offset == 38:
                        made["expiring"] += 1
                    if offset < 0:
                        made["expired"] += 1
                self.document(project, item, people, today, expires)
                made["documents"] += 1

            # one replaced document, so the version history has something in it
            if items:
                self.document(project, items[0], people, today, None)
                made["replaced"] += 1
                made["documents"] += 1

            if has_rera and rera:
                for position, item in enumerate(
                        ComplianceItem.objects.filter(title__type=rera, is_active=True)[:6]):
                    ago = [8, 40, 130, 15, 60, 100][position % 6]
                    self.document(project, item, people, today, None, uploaded_days_ago=ago)
                    made["documents"] += 1

        self.made["compliance"] = made

    def document(self, project, item, people, today, expires, uploaded_days_ago=0):
        document = ComplianceDocument.objects.create(
            project=project, item=item,
            file=ContentFile(b"%PDF-1.4\n% showcase sample document\n",
                             name=f"{_slug(item.name)}.pdf"),
            original_name=f"{_slug(item.name)}.pdf", size_bytes=44210,
            reference=f"AMC/2026/{item.pk:05d}",
            issued_on=today - timedelta(days=random.randint(60, 300)),
            expires_on=expires,
            uploaded_by=people.get(Role.COMPLIANCE))
        if uploaded_days_ago:
            # ⚠ uploaded_at is auto_now_add, so it can only be moved afterwards.
            ComplianceDocument.objects.filter(pk=document.pk).update(
                uploaded_at=timezone.now() - timedelta(days=uploaded_days_ago))
        return document

    # ----------------------------------------------------------------- report
    def report(self, today):
        made = self.made
        orders, work, comp = made["orders"], made["work"], made.get("compliance", {})
        write = self.stdout.write

        write(self.style.SUCCESS("\nShowcase data built.\n"))
        write(f"  {made['projects']} projects, all Won, with an estimate and a bill of materials")
        write(f"  {made['materials']} materials in group {GROUP_CODE}, "
              f"{made['vendors']} vendors {VENDOR_PREFIX}01 upwards")
        write(f"  {sum(orders.values())} purchase orders — {orders['paid']} paid, "
              f"{orders['delivered']} delivered, {orders['approved']} approved, "
              f"{orders['draft']} draft")
        write(f"  {work['headers']} packages and {work['subtasks']} subtasks — "
              f"{work['late']} finished late, {work['blocked']} blocked, "
              f"{work['replanned']} replanned")
        if comp:
            write(f"  {comp['documents']} compliance documents — {comp['expiring']} expiring, "
                  f"{comp['expired']} expired, {comp['replaced']} replaced")
        write(f"  {made['people']} demo colleagues (they cannot sign in)")

        if made.get("promoted"):
            write(self.style.WARNING(
                f"\n  Made {', '.join(made['promoted'])} an Admin, so the launchpad is not empty.\n"
                "  A superuser created with createsuperuser has no role, and the permission\n"
                "  matrix answers 'no role' with almost nothing."))

        write("\n  Start the server and sign in:  python manage.py runserver")
        write("  Take it all away again:        python manage.py seed_showcase --remove\n")

    # ----------------------------------------------------------------- remove
    @transaction.atomic
    def remove(self):
        """
        ⚠ DELETES EXACTLY WHAT IT MADE. Everything is prefixed for this reason,
          and the order below is the dependency order — documents before items,
          orders before bills of materials — so nothing is left orphaned and no
          PROTECT constraint has to be forced.
        """
        User = get_user_model()
        projects = Project.objects.filter(name__startswith=MARK)
        counts = {}

        counts["documents"] = ComplianceDocument.objects.filter(project__in=projects).count()
        for document in ComplianceDocument.objects.filter(project__in=projects):
            document.file.delete(save=False)          # the file, not just the row
            document.delete()

        ProjectCompliance.objects.filter(project__in=projects).delete()
        Subtask.objects.filter(header__project__in=projects).delete()
        counts["tasks"] = TaskHeader.objects.filter(project__in=projects).count()
        TaskHeader.objects.filter(project__in=projects).delete()

        Receipt.objects.filter(po_line__purchase_order__project__in=projects).delete()
        PurchaseOrderLine.objects.filter(purchase_order__project__in=projects).delete()
        counts["orders"] = PurchaseOrder.objects.filter(project__in=projects).count()
        PurchaseOrder.objects.filter(project__in=projects).delete()

        BomLine.objects.filter(bom__project__in=projects).delete()
        Bom.objects.filter(project__in=projects).delete()
        EstimateLine.objects.filter(estimate__project__in=projects).delete()
        Estimate.objects.filter(project__in=projects).delete()
        counts["projects"] = projects.count()
        projects.delete()

        counts["materials"] = Material.objects.filter(group__code=GROUP_CODE).count()
        Material.objects.filter(group__code=GROUP_CODE).delete()
        MaterialGroup.objects.filter(code=GROUP_CODE).delete()
        counts["vendors"] = Vendor.objects.filter(code__startswith=VENDOR_PREFIX).count()
        Vendor.objects.filter(code__startswith=VENDOR_PREFIX).delete()
        counts["people"] = User.objects.filter(username__endswith=USER_SUFFIX).count()
        User.objects.filter(username__endswith=USER_SUFFIX).delete()

        self.stdout.write(self.style.SUCCESS("Showcase data removed."))
        for label, number in counts.items():
            self.stdout.write(f"  {number} {label}")
        self.stdout.write(
            "\n  Nothing else was touched. Your own projects, materials and vendors are as "
            "they were.")


def _at(day):
    """A timezone-aware moment on a date, which is what the date fields expect."""
    return timezone.make_aware(timezone.datetime.combine(day, timezone.datetime.min.time()))


def _slug(name):
    keep = [character.lower() if character.isalnum() else "-" for character in name]
    return "".join(keep).strip("-")[:40] or "document"
