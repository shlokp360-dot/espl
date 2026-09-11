"""
Finance & Accounting and Drawings repository demo data on top of `seed_showcase`
(and `seed_sales_showcase`): vendor bills and payments on the showcase purchase
orders, two work orders with RA bills, and a drawings register on every
"Showcase — …" project — plus one Completed project so that section of the
Drawings overview has a row in it.

HOW TO RUN IT
    python manage.py seed_showcase                  first — this needs its projects
    python manage.py seed_sales_showcase            then (optional)
    python manage.py seed_finance_showcase          then this
    python manage.py seed_finance_showcase --remove

⚠ IT REFUSES TO RUN WITHOUT THE SHOWCASE PROJECTS, and it touches no project
    that is not one of them. Everything it makes is found again through the
    projects' names, the WO-S work order numbers, the VEN-S contractor codes
    and the architects' @showcase.example addresses — so `--remove` takes away
    exactly what was made and nothing else.

⚠ `seed_showcase --remove` DELETES ITS PROJECTS, ORDERS AND VENDORS, and a
    vendor bill, a payment and a drawing all PROTECT theirs. Run THIS command's
    `--remove` first (and `seed_sales_showcase --remove`), or that one refuses.

⚠ EVERY FINANCE ROW GOES THROUGH finance.services — never a raw model write —
    so the figures on the Bills, RA bills, Payments, Vendor ledger and TDS tabs
    are exactly what the screens would have produced had somebody typed them.
    The one thing written directly is the work order itself, as seed_showcase
    writes its purchase orders. Dates that the services stamp with "now"
    (certified_at, approved_at, paid_at, uploaded_at) are moved back afterwards
    to sit on the bill dates, the same way seed_showcase backdates uploads.
"""
import random
from datetime import timedelta
from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import Role
from compliance.models import ComplianceDocument, ComplianceItem, ComplianceType, Kind, ProjectCompliance
from drawings.models import Architect, Drawing, DrawingGroup, DrawingRevision
from finance import services
from finance.models import RABill, RABillLine, VendorInvoice, VendorPayment
from masters.models import DocumentType, Vendor
from projects.bom_models import Bom, BomLine, PurchaseOrder, PurchaseOrderLine, Receipt, _money
from projects.models import Project

MARK = "Showcase — "
COMPLETED_NAME = f"{MARK}Vastrapur Court"
WO_PREFIX = "WO-S"
VENDOR_PREFIX = "VEN-S"
ARCHITECT_DOMAIN = "@showcase.example"
SEED = 20260911

#: A minimal, valid-enough PDF — the same bytes seed_showcase writes for a
#: compliance document. Nobody opens it; the register only needs a file.
PDF = b"%PDF-1.4\n% showcase sample drawing\n"

#: Two labour contractors, numbered after seed_showcase's six suppliers so
#: `VEN-S` finds them all. Invented names, invented phones, dummy GSTINs in the
#: `ZZDMY` pattern seed_dummy_gstins uses, so nothing here is confusable with
#: a real vendor.
CONTRACTORS = [
    ("VEN-S07", "Ashapura Construction Co", "9876501107", "24ZZDMY0107Z1Z5", "194C"),
    ("VEN-S08", "Jay Ambe Labour Contractors", "9876501108", "24ZZDMY0108Z1Z5", "194C"),
]

ARCHITECTS = [
    ("Hiren Vaghela", "Vaghela & Associates", "9825001001"),
    ("Sonal Trivedi", "Studio Trivedi", "9825001002"),
    ("Kunal Mehta", "Mehta Structural Consultants", "9825001003"),
]

#: (group, number, title). The register is grouped ARC · STR · SUR · PAS · MEP.
SHEETS = [
    ("SUR", "SV-01", "Site survey and contour plan"),
    ("ARC", "A-101", "Ground floor plan"),
    ("ARC", "A-102", "Typical floor plan"),
    ("ARC", "A-201", "Elevations"),
    ("ARC", "A-301", "Sections"),
    ("STR", "S-101", "Foundation layout"),
    ("STR", "S-102", "Column schedule"),
    ("STR", "S-201", "Slab reinforcement — 3rd floor"),
    ("PAS", "P-01", "AMC passed plan set"),
    ("MEP", "M-101", "Plumbing and drainage layout"),
    ("MEP", "E-101", "Electrical layout"),
]

#: How many revisions each sheet holds, cycled per project so the three sites
#: do not look identical. 0 = still Required.
REVISION_PLAN = [1, 2, 0, 1, 3, 1, 0, 2, 1, 1, 2]


class Command(BaseCommand):
    help = ("Vendor bills, payments, work orders with RA bills, and a drawings register "
            "on the showcase projects — plus one Completed project.")

    def add_arguments(self, parser):
        parser.add_argument("--remove", action="store_true",
                            help="Take the finance and drawings demo data away.")

    def handle(self, *args, **options):
        projects = list(Project.objects.filter(name__startswith=MARK)
                        .exclude(name=COMPLETED_NAME).order_by("id"))
        if options["remove"]:
            return self.remove(projects)
        if not projects:
            self.stderr.write("No showcase projects. Run `python manage.py seed_showcase` first.")
            return
        if (VendorInvoice.objects.filter(purchase_order__project__in=projects).exists()
                or PurchaseOrder.objects.filter(number__startswith=WO_PREFIX).exists()
                or Drawing.objects.filter(project__in=projects).exists()
                or Project.objects.filter(name=COMPLETED_NAME).exists()):
            self.stderr.write("Finance showcase data already exists. Use --remove first.")
            return
        random.seed(SEED)
        with transaction.atomic():
            self.build(projects)

    # ---------------------------------------------------------------- build
    def build(self, projects):
        self.today = timezone.localdate()
        self.people = self._people()
        self.made = {}

        self.vendor_bills(projects)
        self.work_orders(projects)
        self.drawings(projects)
        completed = self.completed_project()
        self.report(completed)

    def _people(self):
        """The demo colleagues seed_showcase made, else the first active user for everything."""
        User = get_user_model()
        fallback = User.objects.filter(is_active=True).order_by("id").first()
        by_role = {}
        for user in User.objects.filter(username__endswith=".demo").select_related("profile"):
            profile = getattr(user, "profile", None)
            if profile is not None:
                by_role.setdefault(profile.role, user)
        return {
            "site": by_role.get(Role.SITE, fallback),
            "pm": by_role.get(Role.PROJECT_MANAGER, fallback),
            "accountant": by_role.get(Role.ACCOUNTANT, fallback),
            "compliance": by_role.get(Role.COMPLIANCE, fallback),
        }

    # ---- vendor bills and payments on the showcase purchase orders --------
    def vendor_bills(self, projects):
        """
        Ten invoices across the last four months: on paid orders settled in
        full; on delivered orders left unpaid, part-paid or paid — with the
        oldest ones overdue, and TDS withheld wherever the order carries a rate.

        ⚠ FULL PAYMENTS GO ONLY ON ORDERS ALREADY PAID. Settling a delivered
          order would flip its status to Paid, and that is a change to a row
          this command did not make — so it leaves the delivered ones short.
        """
        accountant = self.people["accountant"]
        since = self.today - timedelta(days=125)
        candidates = list(
            PurchaseOrder.objects.filter(
                project__in=projects, document_type=DocumentType.PO,
                status__in=[PurchaseOrder.Status.DELIVERED, PurchaseOrder.Status.PAID],
                delivered_at__date__gte=since, delivered_at__date__lt=self.today)
            .select_related("vendor").prefetch_related("lines").order_by("delivered_at", "id"))
        with_tds = [po for po in candidates if po.tds_pct > 0]
        without = [po for po in candidates if po.tds_pct == 0]
        chosen = _spread(with_tds, 4) + _spread(without, 6)
        if len(chosen) < 10:
            rest = [po for po in candidates if po not in chosen]
            chosen += _spread(rest, 10 - len(chosen))
        chosen.sort(key=lambda po: (po.delivered_at, po.id))

        made = {"invoices": 0, "paid": 0, "part_paid": 0, "unpaid": 0, "tds": 0}
        serial = {}
        for index, po in enumerate(chosen):
            totals = po.totals()
            taxable, gst = totals["taxable"], totals["gst"]
            if index == 3:
                # One invoice the vendor wrote higher than the order — the
                # three-way flag on the order screen needs a case to show.
                taxable = _money(taxable * D("1.03"))
                gst = _money(taxable * D("0.18"))
            serial[po.vendor_id] = serial.get(po.vendor_id, 0) + 1
            invoice_date = po.delivered_at.date() + timedelta(days=1)
            invoice = services.record_vendor_invoice(
                po, accountant,
                vendor_invoice_no=f"{_initials(po.vendor.name)}/26-27/{serial[po.vendor_id]:03d}",
                invoice_date=invoice_date, taxable=taxable, gst=gst, total=_money(taxable + gst),
                note="Received with the delivery challan." if index % 3 == 0 else "")
            made["invoices"] += 1

            if po.status == PurchaseOrder.Status.PAID:
                fraction, paid_on = D("1"), max(po.paid_at.date(), invoice_date)
            else:
                # Delivered: unpaid, half, unpaid, 60% — the oldest of them are
                # past their due date, which is what the Overdue KPI counts.
                fraction = [D("0"), D("0.5"), D("0"), D("0.6")][index % 4]
                paid_on = max(invoice_date, self.today - timedelta(days=2 + (index % 4) * 3))
            if fraction == 0:
                made["unpaid"] += 1
                continue
            tds = _money(invoice.taxable * po.tds_pct / 100 * fraction)
            amount = _money(invoice.total * fraction - tds)
            services.record_invoice_payment(
                invoice, accountant, amount, paid_on=paid_on,
                mode=random.choice([VendorPayment.Mode.NEFT, VendorPayment.Mode.NEFT,
                                    VendorPayment.Mode.CHEQUE, VendorPayment.Mode.UPI]),
                reference=_reference(), tds_amount=tds,
                note="Balance held pending credit note." if fraction < 1 else "")
            made["paid" if fraction == 1 else "part_paid"] += 1
            if tds:
                made["tds"] += 1
        self.made["bills"] = made

    # ---- two work orders, RA bills at every status -----------------------
    def work_orders(self, projects):
        """
        WO-S01 on the first site: advance paid, RA1 paid, RA2 approved and
        part-paid, RA3 still a draft. WO-S02 on the second: advance paid, RA1
        certified and waiting for approval. Every status the tracker can show,
        and an advance recovered pro rata on the bills that were approved.
        """
        pm, site, accountant = self.people["pm"], self.people["site"], self.people["accountant"]
        made = {"work_orders": 0, "ra_bills": 0, "advances": 0}
        plans = [
            # (claim fractions per bill, what happens to each)
            [(D("0.40"), "paid"), (D("0.35"), "part"), (D("0.15"), "draft")],
            [(D("0.45"), "certified")],
        ]
        for index, (code, name, phone, gstin, section) in enumerate(CONTRACTORS):
            project = projects[index % len(projects)]
            vendor = Vendor.objects.create(
                code=code, name=name, phone=_free_phone(phone), gst_number=gstin,
                payment_terms="15 days", default_document_type=DocumentType.WO)
            approved_on = self.today - timedelta(days=[100, 62][index])
            wo = PurchaseOrder.objects.create(
                number=f"{WO_PREFIX}{index + 1:02d}", project=project, vendor=vendor,
                document_type=DocumentType.WO, status=PurchaseOrder.Status.APPROVED,
                vendor_gstin=gstin, required_by=approved_on + timedelta(days=120),
                deduction_pct=D("0"), tds_pct=D("2"), tds_section=section,
                approved_at=_at(approved_on), approved_by=pm, created_by=pm,
                notes="Labour-only contract; materials issued from site.")
            self._work_order_lines(wo, project, vendor)
            taxable = wo.totals()["taxable"]
            # ⚠ The advance is a term on the order (WO-TERMS) — 10 % of the work
            #   value, rounded to the thousand so it reads like an agreed sum.
            advance = (taxable * D("0.10") / 1000).quantize(D("1")) * 1000
            wo.mobilisation_advance = advance
            wo.save(update_fields=["mobilisation_advance"])
            made["work_orders"] += 1

            services.record_advance(
                wo, accountant, advance, paid_on=approved_on + timedelta(days=3),
                mode=VendorPayment.Mode.NEFT, reference=_reference(),
                tds_amount=_money(advance * wo.tds_pct / 100), note="Mobilisation advance")
            made["advances"] += 1

            bill_on = approved_on + timedelta(days=24)
            for sequence, (fraction, fate) in enumerate(plans[index], start=1):
                bill_on = min(bill_on, self.today - timedelta(days=2))
                self._ra_bill(wo, sequence, fraction, fate, bill_on, pm, site, accountant)
                made["ra_bills"] += 1
                bill_on = bill_on + timedelta(days=31)
        self.made["work"] = made

    def _work_order_lines(self, wo, project, vendor):
        """Three lines of their own on the project's BOM, so nothing on a PO is counted twice."""
        bom = Bom.objects.filter(project=project).order_by("id").first()
        sources = list(BomLine.objects.filter(bom=bom).select_related("material")
                       .order_by("id")[:3]) if bom else []
        for source in sources:
            quantity = D(str(random.randint(40, 120)))
            labour_rate = _money(source.material.estimation_rate * D("0.45"))
            line = BomLine.objects.create(
                bom=bom, activity=source.activity, material=source.material,
                planned_qty=quantity, vendor=vendor, vendor_rate=labour_rate)
            PurchaseOrderLine.objects.create(
                purchase_order=wo, bom_line=line, quantity=quantity, rate=labour_rate,
                gst_percent=D("18"), discount_pct=D("0"))

    def _ra_bill(self, wo, sequence, fraction, fate, bill_on, pm, site, accountant):
        claims = {line.id: (line.quantity * fraction).quantize(D("0.001"))
                  for line in wo.lines.all()}
        bill = services.create_ra_bill(
            wo, site, claims, bill_date=bill_on, contractor_ref=f"RA/{sequence}/{bill_on:%m%y}",
            period_from=bill_on - timedelta(days=30), period_to=bill_on,
            note="Measured jointly with the site engineer." if sequence == 1 else "")
        if fate == "draft":
            return bill
        # Certified a shade under the claim on one line, so the two columns
        # differ. Keyed by the BILL line, as the screen posts it.
        certified = {line.id: line.claimed_qty for line in bill.lines.all()}
        first = next(iter(certified))
        certified[first] = (certified[first] * D("0.95")).quantize(D("0.001"))
        services.certify(bill, site, certified)
        RABill.objects.filter(pk=bill.pk).update(certified_at=_at(bill_on + timedelta(days=2)))
        if fate == "certified":
            return bill
        services.approve(bill, pm)
        RABill.objects.filter(pk=bill.pk).update(approved_at=_at(bill_on + timedelta(days=4)))
        bill.refresh_from_db()
        ladder = services.calc.bill_figures(bill)
        share = D("1") if fate == "paid" else D("0.6")
        amount = _money(ladder["net_payable"] * share)
        tds = _money(ladder["tds"] * share)
        # The full payment followed the bill; the part payment went out this
        # week, so the Payments tab (this month by default) has it.
        paid_on = (min(bill_on + timedelta(days=12), self.today - timedelta(days=1))
                   if fate == "paid" else max(bill_on, self.today - timedelta(days=3)))
        services.record_ra_payment(
            bill, accountant, amount, paid_on=paid_on, mode=VendorPayment.Mode.NEFT,
            reference=_reference(), tds_amount=tds)
        if fate == "paid":
            RABill.objects.filter(pk=bill.pk).update(paid_at=_at(paid_on))
        return bill

    # ---- the drawings register -------------------------------------------
    def drawings(self, projects):
        pm = self.people["pm"]
        self.groups = {group.code: group for group in DrawingGroup.objects.filter(is_active=True)}
        self.architects = [
            Architect.objects.create(name=name, firm=firm, phone=_free_architect_phone(phone),
                                     email=f"{_slug(name)}{ARCHITECT_DOMAIN}")
            for name, firm, phone in ARCHITECTS]
        made = {"drawings": 0, "revisions": 0, "approved": 0, "required": 0, "overdue": 0}
        for index, project in enumerate(projects):
            sheets = [sheet for position, sheet in enumerate(SHEETS)
                      if (position + index) % 5 != 4]           # 8 or 9 of the eleven
            for position, (code, number, title) in enumerate(sheets):
                group = self.groups.get(code)
                if group is None:
                    continue
                revisions = REVISION_PLAN[(position + index * 3) % len(REVISION_PLAN)]
                if position == 0:
                    revisions = 1                             # every site has its survey
                required_by = self.today + timedelta(days=[-18, 21, -6, 45, 9][(position + index) % 5])
                drawing = Drawing.objects.create(
                    project=project, group=group, number=number, title=title,
                    architect=self.architects[(index + (code == "STR")) % len(self.architects)],
                    required_by=required_by, created_by=pm)
                made["drawings"] += 1
                if revisions == 0:
                    made["required"] += 1
                    if required_by < self.today:
                        made["overdue"] += 1
                    continue
                first_on = self.today - timedelta(days=70 + position * 4 - index * 7)
                for label_index in range(revisions):
                    received_on = first_on + timedelta(days=label_index * 19)
                    last = label_index == revisions - 1
                    # The newest revision is approved on most sheets; an R1 that
                    # arrived after an approved R0 goes back to Received.
                    approved = (not last) or (position % 3 != 1)
                    self._revision(drawing, f"R{label_index}", received_on, approved, pm)
                    made["revisions"] += 1
                    if last and approved:
                        made["approved"] += 1
        self.made["drawings"] = made

    def _revision(self, drawing, label, received_on, approved, pm, note=""):
        name = f"{_slug(drawing.number)}-{label.lower()}.pdf"
        revision = DrawingRevision.objects.create(
            drawing=drawing, label=label, file=ContentFile(PDF, name=name),
            original_name=name, size_bytes=len(PDF), received_on=received_on,
            note=note or ("Issued for construction" if approved else "For review"),
            approved_on=received_on + timedelta(days=5) if approved else None,
            approved_by=pm if approved else None, uploaded_by=pm)
        # ⚠ uploaded_at is auto_now_add and it is what "newest" is judged by
        #   (DRAWINGS-STATUS), so it must follow the label order.
        DrawingRevision.objects.filter(pk=revision.pk).update(
            uploaded_at=_at(received_on) + timedelta(hours=10, minutes=int(label[1:])))
        return revision

    # ---- one finished building, so "Completed projects" has a row ---------
    def completed_project(self):
        """
        A building handed over last year: every drawing approved, a compliance
        file with the AMC documents that a finished site still holds.
        """
        pm, compliance = self.people["pm"], self.people["compliance"]
        project = Project.objects.create(
            name=COMPLETED_NAME, bua_sqft=D("15200"), status=Project.Status.COMPLETED,
            location="Ahmedabad", billing_address="Elegance Skyz Pvt Ltd, Ahmedabad",
            site_address="Vastrapur Court, Ahmedabad")
        made = {"drawings": 0, "documents": 0}
        for position, (code, number, title) in enumerate(SHEETS[:8]):
            group = self.groups.get(code)
            if group is None:
                continue
            drawing = Drawing.objects.create(
                project=project, group=group, number=number, title=title,
                architect=self.architects[position % len(self.architects)], created_by=pm)
            self._revision(drawing, "R0", self.today - timedelta(days=420 - position * 9), True, pm,
                           note="As built")
            made["drawings"] += 1

        amc = ComplianceType.objects.filter(code="AMC").first()
        if amc is not None:
            items = list(ComplianceItem.objects.filter(title__type=amc, is_active=True)[:8])
            for position, item in enumerate(items):
                if position % 2:
                    continue
                name = f"{_slug(item.name)}.pdf"
                expires = (self.today + timedelta(days=[300, -40, 150, 500][position % 4])
                           if item.kind == Kind.VALID else None)
                ComplianceDocument.objects.create(
                    project=project, item=item, file=ContentFile(PDF, name=name),
                    original_name=name, size_bytes=len(PDF),
                    reference=f"AMC/2025/{item.pk:05d}",
                    issued_on=self.today - timedelta(days=400 + position * 11),
                    expires_on=expires, uploaded_by=compliance)
                made["documents"] += 1
        self.made["completed"] = made
        return project

    # ---------------------------------------------------------------- report
    def report(self, completed):
        bills, work, drawings, done = (self.made["bills"], self.made["work"],
                                       self.made["drawings"], self.made["completed"])
        write = self.stdout.write
        write(self.style.SUCCESS("\nFinance and drawings showcase data built.\n"))
        write(f"  {bills['invoices']} vendor bills — {bills['paid']} paid, {bills['part_paid']} "
              f"part-paid, {bills['unpaid']} unpaid; TDS withheld on {bills['tds']} payments")
        write(f"  {work['work_orders']} work orders ({WO_PREFIX}01 upwards, contractors "
              f"{CONTRACTORS[0][0]} and {CONTRACTORS[1][0]}) with {work['advances']} mobilisation "
              f"advances and {work['ra_bills']} RA bills — draft, certified, approved and paid")
        write(f"  {drawings['drawings']} drawings on the live sites, {drawings['revisions']} "
              f"revisions — {drawings['approved']} approved, {drawings['required']} still "
              f"required ({drawings['overdue']} past their date)")
        write(f"  1 completed project, {completed.name}, with {done['drawings']} drawings and "
              f"{done['documents']} compliance documents")
        write(f"  {len(self.architects)} architects")
        write("\n  Take it away again:  python manage.py seed_finance_showcase --remove"
              "\n  (before seed_showcase --remove — its orders and vendors are protected by "
              "these rows)\n")

    # ---------------------------------------------------------------- remove
    def remove(self, projects):
        """
        Dependency order: payments protect bills, invoices, orders and vendors;
        RA bill lines and receipts protect order lines; order lines protect the
        BOM lines this command added; drawings and documents protect the
        completed project.
        """
        counts = {}
        completed = Project.objects.filter(name=COMPLETED_NAME)
        every = list(projects) + list(completed)
        work_orders = PurchaseOrder.objects.filter(number__startswith=WO_PREFIX, project__in=every)

        # ⚠ A payment on a WO points at the order; a payment on an invoice at
        #   the invoice. Both are found through the order's project.
        payments = VendorPayment.objects.filter(purchase_order__project__in=every)
        counts["payments"] = payments.count()
        payments.delete()
        bills = RABill.objects.filter(purchase_order__in=work_orders)
        counts["ra_bills"] = bills.count()
        RABillLine.objects.filter(ra_bill__in=bills).delete()
        bills.delete()
        invoices = VendorInvoice.objects.filter(purchase_order__project__in=every)
        counts["vendor_bills"] = invoices.count()
        invoices.delete()

        wo_lines = PurchaseOrderLine.objects.filter(purchase_order__in=work_orders)
        Receipt.objects.filter(po_line__in=wo_lines).delete()
        bom_line_ids = list(wo_lines.values_list("bom_line_id", flat=True))
        wo_lines.delete()
        counts["work_orders"] = work_orders.count()
        work_orders.delete()
        BomLine.objects.filter(pk__in=bom_line_ids).delete()
        contractors = Vendor.objects.filter(code__in=[row[0] for row in CONTRACTORS],
                                            purchase_orders__isnull=True, payments__isnull=True)
        counts["contractors"] = contractors.count()
        contractors.delete()

        revisions = DrawingRevision.objects.filter(drawing__project__in=every)
        counts["revisions"] = revisions.count()
        for revision in revisions:
            revision.file.delete(save=False)          # the file, not just the row
        revisions.delete()
        drawings = Drawing.objects.filter(project__in=every)
        counts["drawings"] = drawings.count()
        drawings.delete()
        architects = Architect.objects.filter(email__endswith=ARCHITECT_DOMAIN,
                                              drawings__isnull=True)
        counts["architects"] = architects.count()
        architects.delete()

        if completed.exists():
            if completed.filter(units__isnull=False).exists():
                self.stderr.write(f"{COMPLETED_NAME} has sales units on it — run "
                                  f"`seed_sales_showcase --remove` first. Left in place.")
            else:
                documents = ComplianceDocument.objects.filter(project__in=completed)
                counts["documents"] = documents.count()
                for document in documents:
                    document.file.delete(save=False)
                documents.delete()
                ProjectCompliance.objects.filter(project__in=completed).delete()
                counts["completed_projects"] = completed.count()
                completed.delete()

        self.stdout.write(self.style.SUCCESS("Finance and drawings showcase data removed."))
        for label, number in counts.items():
            self.stdout.write(f"  {number} {label}")


# ---------------------------------------------------------------- helpers

def _spread(rows, count):
    """`count` rows spread evenly across the list, oldest to newest."""
    if count <= 0 or not rows:
        return []
    if len(rows) <= count:
        return list(rows)
    step = len(rows) / count
    return [rows[int(position * step)] for position in range(count)]


def _at(day):
    """A timezone-aware moment on a date, which is what the datetime fields expect."""
    return timezone.make_aware(timezone.datetime.combine(day, timezone.datetime.min.time()))


def _slug(name):
    keep = [character.lower() if character.isalnum() else "-" for character in name]
    return "".join(keep).strip("-")[:40] or "document"


def _initials(name):
    return "".join(word[0] for word in name.split() if word[0].isalpha()).upper()[:4] or "INV"


def _reference():
    return f"UTR{random.randint(100000000, 999999999)}"


def _free_phone(phone):
    """`Vendor.phone` is unique and a real vendor may hold the invented number (C7)."""
    if not Vendor.objects.filter(phone=phone).exists():
        return phone
    for bump in range(1, 10):
        candidate = phone[:-1] + str((int(phone[-1]) + bump) % 10)
        if not Vendor.objects.filter(phone=candidate).exists():
            return candidate
    return phone


def _free_architect_phone(phone):
    return phone if not Architect.objects.filter(phone=phone).exists() else ""
