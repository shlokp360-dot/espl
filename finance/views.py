"""
The Finance & Accounting screens: overview, bills, RA bills, payments, the
vendor ledger and the TDS report.

>>> ANCHOR: FIN-SCREENS <<<
WHO MAY DO WHAT (accounts/perms.py)
    finance.view      Admin · Project manager · Accountant — every register, PDF, Excel
    finance.certify   Admin · Project manager · Site — raise a bill, type certified quantities
    finance.approve   Admin · Project manager — approve a bill
    finance.pay       Admin · Accountant — record a bill (invoice) and payments

THE TABS  Orders · Overview · Bills · RA bills · Payments · Vendor ledger · TDS
    po_register             the purchase order register (projects/views.py) —
                            FIRST tab since 11 Sep 2026, shown to register.view;
                            finance_home redirects a register-only role there
    finance_home            KPIs, ageing, cash-out, top vendors — project filter
    finance_bills           one row per vendor bill, VB- on a PO or RA- on a WO
    finance_bill_pick       "Record a bill": pick the PO first, then invoice_new
    finance_ra_bills        the RA bill tracker, project first
    finance_payments        the register keyed into Tally
    finance_vendor_ledger   one vendor, everything, running balance
    finance_tds             per quarter, per vendor, grouped by section — for 26Q

⚠ RETENTION IS SWITCHED OFF (customer, 11 Sep 2026). The Retention tab, the
  release form and its route are gone; the fields and the ladder rung stay.

⚠ TWO SCREENS OPEN TO EITHER finance.view OR finance.certify: the work order
  screen and the bill screen. The site engineer holds certify and not view —
  the matrix gives them the measuring, not the books — and a permission is
  only real if the role can reach the screen its button sits on. `requires_any`
  is used ONLY on those two reads; every write behind them carries its own
  single key. See ANCHOR: PERMS-MATRIX on why that decorator is otherwise
  avoided.

⚠ NO ARITHMETIC HERE. Every figure comes from finance.calc, the list screens
  through its bulk functions. Every write goes through finance.services and is
  a POST. Raw ids from the query string are `.isdigit()`-guarded.
"""
import io
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from accounts.perms import can, requires, requires_any
from masters.models import CompanyProfile, DocumentType, Vendor
from projects.bom_models import PurchaseOrder
from projects.models import Project

from . import calc, services
from .models import RABill, VendorInvoice, VendorPayment
from .services import FinanceError

ZERO = Decimal("0")

BILL_PILL = {"draft": "p-draft", "certified": "p-onsheet", "approved": "p-approved", "paid": "p-paid"}
INVOICE_PILL = {"open": "p-draft", "part_paid": "p-onsheet", "settled": "p-paid"}
INVOICE_WORDS = {"open": "Open", "part_paid": "Part-paid", "settled": "Settled"}


# ---------------------------------------------------------------- helpers

def _date(raw, default=None):
    parsed = parse_date((raw or "").strip()) if raw else None
    return parsed or default


def _int(raw):
    raw = (raw or "").strip()
    return int(raw) if raw.isdigit() else None


def _projects():
    return Project.objects.filter(purchase_orders__isnull=False).distinct().order_by("name")


def _won_projects():
    """The RA bill tracker's first control: every Won project, billed or not."""
    return Project.objects.filter(status=Project.Status.WON).order_by("name")


def _vendors(doc_type=None):
    vendors = Vendor.objects.filter(purchase_orders__isnull=False)
    if doc_type:
        vendors = vendors.filter(purchase_orders__document_type=doc_type)
    return vendors.distinct().order_by("name")


def _work_orders():
    """Approved-or-later work orders that have at least one RA bill."""
    return (PurchaseOrder.objects
            .filter(document_type=DocumentType.WO, ra_bills__isnull=False)
            .exclude(status=PurchaseOrder.Status.DRAFT)
            .distinct().select_related("vendor", "project")
            .prefetch_related("lines"))


def _wo_or_404(po_id):
    return get_object_or_404(
        PurchaseOrder.objects.select_related("vendor", "project")
        .prefetch_related("lines__bom_line__material", "lines__bom_line__activity"),
        pk=po_id, document_type=DocumentType.WO)


def _po_or_404(po_id):
    return get_object_or_404(
        PurchaseOrder.objects.select_related("vendor", "project").prefetch_related("lines"),
        pk=po_id, document_type=DocumentType.PO)


def _bill_or_404(bill_id):
    return get_object_or_404(
        RABill.objects.select_related("purchase_order__vendor", "purchase_order__project",
                                      "certified_by", "approved_by", "created_by"),
        pk=bill_id)


def _bill_lines(bill):
    return list(bill.lines.select_related("po_line__bom_line__material",
                                          "po_line__bom_line__activity").order_by("id"))


def _month_bounds(day):
    first = day.replace(day=1)
    following = (first + timedelta(days=32)).replace(day=1)
    return first, following - timedelta(days=1)


def _decorate_bills(bills, ladders, paid_on_bill=None):
    rows = []
    for bill in bills:
        rows.append({"bill": bill, "ladder": ladders.get(bill.id),
                     "pill": BILL_PILL.get(bill.status, "p-draft"),
                     "paid": (paid_on_bill or {}).get(bill.id, ZERO)})
    return rows


# ---------------------------------------------------------------- the overview

def _register_selection(source):
    """The bills-register filters, shared by the screen, its Excel and the overview."""
    project = _int(source.get("project"))
    vendor = _int(source.get("vendor"))
    kind = (source.get("type") or "").strip().lower()
    status = (source.get("status") or "").strip()
    date_from = _date(source.get("from"))
    date_to = _date(source.get("to"))
    invoices = (VendorInvoice.objects.select_related("purchase_order__vendor",
                                                     "purchase_order__project"))
    bills = (RABill.objects.filter(status__in=RABill.COUNTED)
             .select_related("purchase_order__vendor", "purchase_order__project"))
    if project:
        invoices = invoices.filter(purchase_order__project_id=project)
        bills = bills.filter(purchase_order__project_id=project)
    if vendor:
        invoices = invoices.filter(purchase_order__vendor_id=vendor)
        bills = bills.filter(purchase_order__vendor_id=vendor)
    if date_from:
        invoices = invoices.filter(invoice_date__gte=date_from)
        bills = bills.filter(bill_date__gte=date_from)
    if date_to:
        invoices = invoices.filter(invoice_date__lte=date_to)
        bills = bills.filter(bill_date__lte=date_to)
    if kind == "po":
        bills = bills.none()
    elif kind == "wo":
        invoices = invoices.none()
    else:
        kind = ""
    rows = calc.bills_register(list(invoices), list(bills))
    if status in calc.BILL_STATUS_WORDS:
        rows = [r for r in rows if r["status"] == status]
    else:
        status = ""
    for row in rows:
        row["pill"] = INVOICE_PILL[row["status"]]
        row["word"] = INVOICE_WORDS[row["status"]]
    chosen = {"project": project, "vendor": vendor, "type": kind, "status": status,
              "from": date_from, "to": date_to}
    return rows, chosen


def home(request):
    """
    The Overview — and the doorway for the whole module.

    ⚠ THE FINANCE TILE IS SHOWN TO finance.view OR register.view (ANCHOR:
      HUB-TILES, `any_of`), because the purchase order register is the first
      tab of this strip since 11 Sep 2026. Somebody holding register.view
      alone — the Purchase manager, the Site engineer — is sent to the register
      rather than refused, so a tile never leads to a 403. Everybody else
      without finance.view is refused here exactly as `requires` would.
    """
    if not can(request.user, "finance.view"):
        if can(request.user, "register.view"):
            return redirect("po_register")
        return HttpResponseForbidden(
            "Your role does not include this. Ask an Admin if you think it should.")
    today = timezone.localdate()
    project = _int(request.GET.get("project"))
    rows, _chosen = _register_selection({"project": request.GET.get("project")})
    open_rows = [r for r in rows if r["balance"] > ZERO]

    month_from, month_to = _month_bounds(today)
    _key, _label, quarter_from, quarter_to = calc.quarter_bounds(today)
    month_payments = VendorPayment.objects.filter(paid_on__range=(month_from, month_to))
    quarter_payments = VendorPayment.objects.filter(paid_on__range=(quarter_from, quarter_to))
    if project:
        month_payments = month_payments.filter(purchase_order__project_id=project)
        quarter_payments = quarter_payments.filter(purchase_order__project_id=project)

    late = calc.overdue(open_rows, today)
    kpis = {
        "payable_now": calc.bills_total(open_rows)["balance"],
        "open_count": len(open_rows),
        "overdue": late["balance"],
        "overdue_count": late["count"],
        "overdue_assumed": late["assumed"],
        "paid_month": calc.payments_total(month_payments)["amount"],
        "tds_quarter": calc.payments_total(quarter_payments)["tds"],
    }
    return render(request, "finance/home.html", {
        "kpis": kpis, "today": today,
        "ageing": calc.ageing(open_rows, today),
        "cash_out": calc.cash_out(open_rows, today),
        "vendors": calc.top_vendors(open_rows),
        "projects": _won_projects(), "project": project,
        "month": f"{month_from:%b %Y}", "quarter": f"{quarter_from:%b} – {quarter_to:%b %Y}",
    })


# ---------------------------------------------------------------- RA bills

def _bill_selection(request):
    bills = (RABill.objects.select_related("purchase_order__vendor", "purchase_order__project")
             .order_by("-bill_date", "-id"))
    project = _int(request.GET.get("project") or request.POST.get("project"))
    vendor = _int(request.GET.get("vendor") or request.POST.get("vendor"))
    status = (request.GET.get("status") or request.POST.get("status") or "").strip()
    if project:
        bills = bills.filter(purchase_order__project_id=project)
    if vendor:
        bills = bills.filter(purchase_order__vendor_id=vendor)
    if status in RABill.Status.values:
        bills = bills.filter(status=status)
    return list(bills), {"project": project, "vendor": vendor, "status": status}


@requires("finance.view")
def ra_bills(request):
    """
    The RA bill tracker. Project is the first control and "all projects" the
    default; the tab strip carries the chosen project along. With a project
    chosen the tfoot adds that project's position: certified to date, billed,
    paid and balance — over its APPROVED and PAID bills, as everywhere else.
    """
    bills, chosen = _bill_selection(request)
    ladders = calc.bulk_bill_figures(bills)
    paid_on_bill = defaultdict(Decimal)
    for payment in VendorPayment.objects.filter(ra_bill_id__in=[b.id for b in bills]):
        paid_on_bill[payment.ra_bill_id] += payment.amount
    rows = _decorate_bills(bills, ladders, paid_on_bill)
    counted = [b for b in bills if b.status in RABill.COUNTED]
    totals = {
        "taxable": calc._sum(ladders[b.id]["taxable"] for b in bills),
        "net_payable": calc._sum(ladders[b.id]["net_payable"] for b in bills),
        "paid": calc._sum(paid_on_bill[b.id] for b in bills),
    }
    subtotals = None
    if chosen["project"]:
        subtotals = {
            "certified": calc._sum(ladders[b.id]["taxable"] for b in counted),
            "billed": calc._sum(ladders[b.id]["invoice_value"] for b in counted),
            "paid": calc._sum(paid_on_bill[b.id] for b in counted),
            "balance": calc._sum(max(ZERO, ladders[b.id]["net_payable"] - paid_on_bill[b.id])
                                 for b in counted),
            "project": Project.objects.filter(pk=chosen["project"]).first(),
        }
    return render(request, "finance/ra_bills.html", {
        "rows": rows, "totals": totals, "subtotals": subtotals, "chosen": chosen,
        "projects": _won_projects(), "vendors": _vendors(DocumentType.WO),
        "statuses": RABill.Status.choices,
    })


@require_POST
@requires("finance.view")
def ra_bills_excel(request):
    """
    The register as a spreadsheet: one row per bill with the whole ladder, and
    a second sheet one row per line. Widths and formats are keyed off the
    headings, as projects.views.po_register_excel — never counted by hand.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    bills, _ = _bill_selection(request)
    ladders = calc.bulk_bill_figures(bills)

    book = Workbook()
    sheet = book.active
    sheet.title = "RA bills"
    headings = [
        "RA bill", "No.", "Final", "Status", "Bill date", "Contractor ref", "Approved", "Paid",
        "Project", "Work order", "Contractor", "GSTIN",
        "Gross", "Line discount", "Taxable", "GST", "Invoice value",
        "Deduction %", "Deduction", "Advance recovery",
        "Round off", "Payable", "TDS %", "TDS", "Net payable",
    ]
    money_from = headings.index("Gross")
    _sheet_header(sheet, headings, Font, PatternFill, Alignment)
    for bill in bills:
        ladder = ladders[bill.id]
        po = bill.purchase_order
        sheet.append([
            bill.number, bill.sequence, "Yes" if bill.is_final else "", bill.get_status_display(),
            bill.bill_date, bill.contractor_ref,
            bill.approved_at.date() if bill.approved_at else None,
            bill.paid_at.date() if bill.paid_at else None,
            po.project.code, po.number, po.vendor.name, po.vendor_gstin or po.vendor.gst_number,
            float(ladder["gross"]), float(ladder["discount"]), float(ladder["taxable"]),
            float(ladder["gst"]), float(ladder["invoice_value"]),
            float(po.deduction_pct), float(ladder["deduction"]), float(ladder["advance_recovery"]),
            float(ladder["round_off"]), float(ladder["payable"]),
            float(po.tds_pct), float(ladder["tds"]), float(ladder["net_payable"]),
        ])
    _sheet_finish(sheet, headings, money_from,
                  {"RA bill": 12, "Contractor ref": 16, "Project": 12, "Work order": 12,
                   "Contractor": 24, "GSTIN": 18, "Status": 11})

    lines = book.create_sheet("Lines")
    line_headings = [
        "RA bill", "Status", "Project", "Work order", "Contractor",
        "Construction activity", "Material code", "Scope", "UOM",
        "Order qty", "Claimed", "Certified", "Rate", "Gross", "Disc %", "Taxable", "GST %", "GST",
        "Line total",
    ]
    _sheet_header(lines, line_headings, Font, PatternFill, Alignment)
    bill_lines = (RABill.objects.filter(pk__in=[b.id for b in bills])
                  .prefetch_related("lines__po_line__bom_line__material",
                                    "lines__po_line__bom_line__activity")
                  .select_related("purchase_order__vendor", "purchase_order__project"))
    for bill in bill_lines:
        ladder = ladders[bill.id]
        by_line = {row["line"].id: row for row in ladder["lines"]}
        po = bill.purchase_order
        for line in bill.lines.all():
            row = by_line[line.id]
            material = line.po_line.bom_line.material
            lines.append([
                bill.number, bill.get_status_display(), po.project.code, po.number, po.vendor.name,
                line.po_line.bom_line.activity.name, material.code, material.name, material.uom,
                float(line.po_line.quantity), float(line.claimed_qty),
                float(line.certified_qty) if line.certified_qty is not None else None,
                float(line.rate), float(row["gross"]), float(line.discount_pct),
                float(row["taxable"]), float(line.gst_percent), float(row["gst"]),
                float(row["total"]),
            ])
    _sheet_finish(lines, line_headings, line_headings.index("Order qty"),
                  {"RA bill": 12, "Contractor": 24, "Material code": 16, "Scope": 30,
                   "Construction activity": 18})

    return _xlsx(book, "RABills")


def _sheet_header(sheet, headings, Font, PatternFill, Alignment):
    sheet.append(headings)
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F3864")
        cell.alignment = Alignment(vertical="center", wrap_text=True)


def _sheet_finish(sheet, headings, money_from, widths):
    for index, heading in enumerate(headings, start=1):
        letter = sheet.cell(row=1, column=index).column_letter
        sheet.column_dimensions[letter].width = widths.get(heading, 13)
    for row in sheet.iter_rows(min_row=2, min_col=money_from + 1, max_col=len(headings)):
        for cell in row:
            cell.number_format = "#,##,##0.00"
    sheet.freeze_panes = "B2"


def _xlsx(book, stem):
    stream = io.BytesIO()
    book.save(stream)
    stream.seek(0)
    response = HttpResponse(
        stream.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="{stem}_{timezone.localdate()}.xlsx"'
    return response


@requires_any("finance.view", "finance.certify")
def work_order(request, po_id):
    """One work order: its lines to date, bills, advance and payments."""
    po = _wo_or_404(po_id)
    today = timezone.localdate()
    summary = calc.cumulative(po, today=today)
    bills = _decorate_bills(summary["bills"], summary["ladders"], summary["paid_on_bill"])
    payments = sorted(summary["payments"], key=lambda p: (p.paid_on, p.id), reverse=True)
    return render(request, "finance/wo.html", {
        "po": po, "s": summary, "bills": bills, "today": today,
        "advances": [p for p in payments if p.kind == VendorPayment.Kind.ADVANCE],
        "payments": payments,
        "can_bill": (po.status in (PurchaseOrder.Status.APPROVED, PurchaseOrder.Status.DELIVERED)
                     and summary["open_bill"] is None and summary["final_bill"] is None),
        "modes": VendorPayment.Mode.choices,
    })


@require_POST
@requires("finance.certify")
def ra_bill_new(request, po_id):
    po = _wo_or_404(po_id)
    claims = {}
    for line in po.lines.all():
        raw = (request.POST.get(f"claim-{line.id}") or "").strip()
        if raw:
            claims[line.id] = raw
    try:
        bill = services.create_ra_bill(
            po, request.user, claims,
            is_final=bool(request.POST.get("is_final")),
            bill_date=_date(request.POST.get("bill_date"), timezone.localdate()),
            contractor_ref=request.POST.get("contractor_ref", ""),
            period_from=_date(request.POST.get("period_from")),
            period_to=_date(request.POST.get("period_to")),
            note=request.POST.get("note", ""))
    except FinanceError as refusal:
        messages.error(request, str(refusal))
        return redirect(reverse("finance_wo", args=[po.id]))
    messages.success(request, f"{bill.number} raised on {po.number} — bill no. {bill.sequence}. "
                              f"Certify the quantities next.")
    return redirect(reverse("finance_ra_bill", args=[bill.id]))


@requires_any("finance.view", "finance.certify")
def ra_bill(request, bill_id):
    bill = _bill_or_404(bill_id)
    po = bill.purchase_order
    lines = _bill_lines(bill)
    ladder = calc.bill_figures(bill)
    by_line = {row["line"].id: row for row in ladder["lines"]}
    before = calc.certified_before(po, exclude_bill=bill)
    rows = []
    for line in lines:
        done = before[line.po_line_id]
        rows.append({"line": line, "figures": by_line[line.id], "before": done,
                     "remaining": line.po_line.quantity - done})
    payments = list(bill.payments.order_by("paid_on", "id"))
    paid = calc._sum(p.amount for p in payments)
    return render(request, "finance/ra_bill.html", {
        "bill": bill, "po": po, "rows": rows, "ladder": ladder, "payments": payments,
        "paid": paid, "left": calc._money(ladder["net_payable"] - paid),
        "pill": BILL_PILL.get(bill.status, "p-draft"),
        "editable": bill.is_editable and can(request.user, "finance.certify"),
        "company": CompanyProfile.get_solo(),
        "interstate": _interstate(po),
    })


def _interstate(po):
    """The same rule as projects.views._is_interstate, for the ladder's GST rows."""
    if po.vendor.is_unregistered:
        return False
    ours = CompanyProfile.get_solo().gst_number
    theirs = po.vendor_gstin or po.vendor.gst_number
    if not ours or not theirs:
        return False
    return ours[:2] != theirs[:2]


@require_POST
@requires("finance.certify")
def ra_bill_save(request, bill_id):
    """Save the typed quantities; with action=certify, certify them too."""
    bill = _bill_or_404(bill_id)
    claimed, certified, remarks = {}, {}, {}
    for line in bill.lines.all():
        if f"claim-{line.id}" in request.POST:
            claimed[line.id] = request.POST.get(f"claim-{line.id}") or "0"
        if f"cert-{line.id}" in request.POST:
            certified[line.id] = request.POST.get(f"cert-{line.id}")
        if f"remark-{line.id}" in request.POST:
            remarks[line.id] = request.POST.get(f"remark-{line.id}")
    try:
        services.update_bill_lines(
            bill, claimed=claimed, certified=certified, remarks=remarks,
            is_final=bool(request.POST.get("is_final")),
            contractor_ref=request.POST.get("contractor_ref"),
            bill_date=_date(request.POST.get("bill_date"), bill.bill_date),
            period_from=_date(request.POST.get("period_from")) or "",
            period_to=_date(request.POST.get("period_to")) or "",
            note=request.POST.get("note"))
        if request.POST.get("action") == "certify":
            services.certify(bill, request.user)
            messages.success(request, f"{bill.number} certified. It can be approved now.")
        else:
            messages.success(request, f"{bill.number} saved.")
    except FinanceError as refusal:
        messages.error(request, str(refusal))
    return redirect(reverse("finance_ra_bill", args=[bill.id]))


@require_POST
@requires("finance.approve")
def ra_bill_approve(request, bill_id):
    bill = _bill_or_404(bill_id)
    try:
        services.approve(bill, request.user)
    except FinanceError as refusal:
        messages.error(request, str(refusal))
    else:
        word = (" The work order is marked completed." if bill.is_final else "")
        messages.success(request, f"{bill.number} approved and locked. Certified quantities are "
                                  f"recorded as received on the BOM.{word}")
    return redirect(reverse("finance_ra_bill", args=[bill.id]))


@requires("finance.pay")
def ra_bill_pay(request, bill_id):
    bill = _bill_or_404(bill_id)
    ladder = calc.bill_figures(bill)
    paid = calc._sum(p.amount for p in bill.payments.all())
    left = calc._money(ladder["net_payable"] - paid)
    if request.method == "POST":
        try:
            payment = services.record_ra_payment(
                bill, request.user, request.POST.get("amount", ""),
                paid_on=_date(request.POST.get("paid_on"), timezone.localdate()),
                mode=request.POST.get("mode", ""), reference=request.POST.get("reference", ""),
                tds_amount=request.POST.get("tds_amount") or "0", note=request.POST.get("note", ""))
        except FinanceError as refusal:
            messages.error(request, str(refusal))
        else:
            messages.success(request, f"{payment.number} recorded against {bill.number}.")
            return redirect(reverse("finance_ra_bill", args=[bill.id]))
    return render(request, "finance/ra_bill_pay.html", {
        "bill": bill, "ladder": ladder, "paid": paid, "left": left,
        "modes": VendorPayment.Mode.choices, "today": timezone.localdate(),
    })


@requires("finance.view")
def ra_bill_pdf(request, bill_id):
    """
    The bill as a PDF, approved onwards — the same rule as PO-PDF, for the same
    reason: an open bill is a claim under discussion, not a document.
    WeasyPrint is imported inside the view; CI does not install it.
    """
    bill = _bill_or_404(bill_id)
    if bill.status in RABill.OPEN:
        messages.warning(request, f"{bill.number} is not approved yet, so there is nothing to "
                                  f"download. Approve it first.")
        return redirect(reverse("finance_ra_bill", args=[bill.id]))
    po = bill.purchase_order
    ladder = calc.bill_figures(bill)
    by_line = {row["line"].id: row for row in ladder["lines"]}
    before = calc.certified_before(po, exclude_bill=bill)
    rows = [{"line": line, "figures": by_line[line.id], "before": before[line.po_line_id]}
            for line in _bill_lines(bill)]
    html = render_to_string("finance/ra_bill_pdf.html", {
        "bill": bill, "po": po, "rows": rows, "ladder": ladder,
        "company": CompanyProfile.get_solo(), "interstate": _interstate(po),
    }, request=request)
    from weasyprint import HTML
    pdf = HTML(string=html, base_url=request.build_absolute_uri("/")).write_pdf()
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{bill.number}_{po.number}.pdf"'
    return response


@requires("finance.certify")
def ra_bill_discard(request, bill_id):
    bill = _bill_or_404(bill_id)
    po = bill.purchase_order
    if request.method == "POST":
        try:
            number = services.discard_draft(bill)
        except FinanceError as refusal:
            messages.error(request, str(refusal))
            return redirect(reverse("finance_ra_bill", args=[bill.id]))
        messages.success(request, f"{number} discarded. Its number is not reused.")
        return redirect(reverse("finance_wo", args=[po.id]))
    return render(request, "finance/ra_bill_discard.html", {"bill": bill, "po": po})


# ---------------------------------------------------------------- bills (PO/WO billing)

@requires("finance.view")
def bills(request):
    """
    ONE register for every vendor bill: a VB- invoice against a purchase order
    or an RA- bill against a work order, in the same columns. Filters: project,
    vendor, type, status, date range. The Excel export takes the same selection.
    """
    rows, chosen = _register_selection(request.GET)
    return render(request, "finance/bills.html", {
        "rows": rows, "totals": calc.bills_total(rows), "chosen": chosen,
        "projects": _projects(), "vendors": _vendors(),
        "statuses": INVOICE_WORDS.items(),
    })


@require_POST
@requires("finance.view")
def bills_excel(request):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    rows, chosen = _register_selection(request.POST)
    book = Workbook()
    sheet = book.active
    sheet.title = "Bills"
    headings = ["Bill no", "Type", "Document", "Vendor's ref", "Project", "Vendor", "GSTIN",
                "Bill date", "Due", "Status", "Basic", "Amount", "TDS", "Paid to date", "Balance"]
    _sheet_header(sheet, headings, Font, PatternFill, Alignment)
    for row in rows:
        sheet.append([
            row["number"], "PO" if row["kind"] == "po" else "WO", row["po"].number,
            row["reference"], row["project"].code, row["vendor"].name,
            row["po"].vendor_gstin or row["vendor"].gst_number,
            row["bill_date"], row["due_date"], row["word"],
            float(row["taxable"]), float(row["amount"]), float(row["tds"]),
            float(row["paid"]), float(row["balance"]),
        ])
    _sheet_finish(sheet, headings, headings.index("Basic"),
                  {"Bill no": 12, "Document": 14, "Vendor's ref": 16, "Vendor": 26, "GSTIN": 18,
                   "Status": 11})
    return _xlsx(book, "Bills")


@requires("finance.pay")
def bill_pick(request):
    """
    "Record a bill" from the Bills tab: pick the purchase order first. Lists
    approved-or-later POs by project; the row leads to finance_invoice_new.
    """
    project = _int(request.GET.get("project"))
    orders = (PurchaseOrder.objects.filter(document_type=DocumentType.PO)
              .exclude(status=PurchaseOrder.Status.DRAFT)
              .select_related("vendor", "project").prefetch_related("lines")
              .order_by("project__name", "-approved_at", "-id"))
    if project:
        orders = orders.filter(project_id=project)
    orders = list(orders)
    settlements = calc.bulk_po_settlement(orders)
    rows = [{"po": po, "s": settlements[po.id]} for po in orders]
    return render(request, "finance/bill_pick.html", {
        "rows": rows, "projects": _projects(), "project": project,
    })


@requires("finance.view")
def purchase_order(request, po_id):
    po = _po_or_404(po_id)
    settlement = calc.po_settlement(po)
    invoices_ = list(VendorInvoice.objects.filter(purchase_order=po).order_by("invoice_date", "id"))
    payments_ = list(VendorPayment.objects.filter(purchase_order=po)
                     .select_related("vendor_invoice").order_by("-paid_on", "-id"))
    rows = [{"invoice": i, "f": settlement["invoices"][i.id],
             "pill": INVOICE_PILL[settlement["invoices"][i.id]["status"]],
             "word": INVOICE_WORDS[settlement["invoices"][i.id]["status"]]} for i in invoices_]
    return render(request, "finance/po.html", {
        "po": po, "s": settlement, "invoices": rows, "payments": payments_,
        "totals": po.totals(),
    })


@requires("finance.pay")
def invoice_new(request, po_id):
    po = _po_or_404(po_id)
    if request.method == "POST":
        try:
            invoice = services.record_vendor_invoice(
                po, request.user, request.POST.get("vendor_invoice_no", ""),
                _date(request.POST.get("invoice_date"), timezone.localdate()),
                request.POST.get("taxable", ""), request.POST.get("gst", ""),
                request.POST.get("total", ""), note=request.POST.get("note", ""))
        except FinanceError as refusal:
            messages.error(request, str(refusal))
        else:
            messages.success(request, f"{invoice.number} recorded — {po.vendor.name}'s invoice "
                                      f"{invoice.vendor_invoice_no} on {po.number}.")
            return redirect(reverse("finance_po", args=[po.id]))
    return render(request, "finance/invoice_new.html", {
        "po": po, "totals": po.totals(), "today": timezone.localdate(), "typed": request.POST,
    })


@requires("finance.pay")
def po_pay(request, po_id):
    """Record money against an invoice on this order, or an advance before one."""
    po = _po_or_404(po_id)
    settlement = calc.po_settlement(po)
    open_invoices = [i for i in VendorInvoice.objects.filter(purchase_order=po).order_by("invoice_date")
                     if settlement["invoices"][i.id]["status"] != "settled"]
    chosen = _int(request.GET.get("invoice") or request.POST.get("invoice"))
    if request.method == "POST":
        try:
            common = dict(
                paid_on=_date(request.POST.get("paid_on"), timezone.localdate()),
                mode=request.POST.get("mode", ""), reference=request.POST.get("reference", ""),
                tds_amount=request.POST.get("tds_amount") or "0", note=request.POST.get("note", ""))
            if request.POST.get("kind") == VendorPayment.Kind.ADVANCE:
                payment = services.record_advance(po, request.user, request.POST.get("amount", ""),
                                                  **common)
            else:
                invoice = get_object_or_404(VendorInvoice, pk=chosen or 0, purchase_order=po)
                payment = services.record_invoice_payment(
                    invoice, request.user, request.POST.get("amount", ""), **common)
        except FinanceError as refusal:
            messages.error(request, str(refusal))
        else:
            messages.success(request, f"{payment.number} recorded on {po.number}.")
            return redirect(reverse("finance_po", args=[po.id]))
    return render(request, "finance/po_pay.html", {
        "po": po, "s": settlement, "open_invoices": open_invoices, "chosen": chosen,
        "modes": VendorPayment.Mode.choices, "today": timezone.localdate(),
        "kind": request.POST.get("kind") or request.GET.get("kind") or
                (VendorPayment.Kind.AGAINST_INVOICE if open_invoices else VendorPayment.Kind.ADVANCE),
    })


# ---------------------------------------------------------------- payments

def _payment_selection(request):
    source = request.GET if request.method == "GET" else request.POST
    today = timezone.localdate()
    month_from, _ = _month_bounds(today)
    date_from = _date(source.get("from"), month_from)
    date_to = _date(source.get("to"), today)
    project = _int(source.get("project"))
    vendor = _int(source.get("vendor"))
    kind = (source.get("kind") or "").strip()
    rows = (VendorPayment.objects.filter(paid_on__range=(date_from, date_to))
            .select_related("vendor", "purchase_order__project", "ra_bill", "vendor_invoice")
            .order_by("-paid_on", "-id"))
    if project:
        rows = rows.filter(purchase_order__project_id=project)
    if vendor:
        rows = rows.filter(vendor_id=vendor)
    if kind in VendorPayment.Kind.values:
        rows = rows.filter(kind=kind)
    return list(rows), {"from": date_from, "to": date_to, "project": project, "vendor": vendor,
                        "kind": kind}


@requires("finance.view")
def payments(request):
    rows, chosen = _payment_selection(request)
    return render(request, "finance/payments.html", {
        "rows": rows, "chosen": chosen, "totals": calc.payments_total(rows),
        "projects": _projects(), "vendors": _vendors(), "kinds": VendorPayment.Kind.choices,
    })


@require_POST
@requires("finance.view")
def payments_excel(request):
    """The register the accountant keys into Tally. Same selection as the screen."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    rows, chosen = _payment_selection(request)
    book = Workbook()
    sheet = book.active
    sheet.title = "Payments"
    headings = ["Date", "PV number", "Vendor", "GSTIN", "Project", "Document", "Kind",
                "Amount", "TDS", "Mode", "Reference"]
    _sheet_header(sheet, headings, Font, PatternFill, Alignment)
    for payment in rows:
        sheet.append([
            payment.paid_on, payment.number, payment.vendor.name,
            payment.purchase_order.vendor_gstin or payment.vendor.gst_number,
            payment.purchase_order.project.code, payment.document_number,
            payment.get_kind_display(), float(payment.amount), float(payment.tds_amount),
            payment.get_mode_display(), payment.reference,
        ])
    _sheet_finish(sheet, headings, headings.index("Amount"),
                  {"Vendor": 26, "GSTIN": 18, "Reference": 18, "Kind": 16, "PV number": 12})
    # Mode and Reference are text; the money format above ran to the last column.
    for row in sheet.iter_rows(min_row=2, min_col=headings.index("Mode") + 1, max_col=len(headings)):
        for cell in row:
            cell.number_format = "General"
    return _xlsx(book, f"Payments_{chosen['from']}_to_{chosen['to']}")


# ---------------------------------------------------------------- the vendor ledger

def _ledger_selection(source):
    vendor_id = _int(source.get("vendor"))
    vendor = Vendor.objects.filter(pk=vendor_id).first() if vendor_id else None
    date_from = _date(source.get("from"))
    date_to = _date(source.get("to"))
    ledger = calc.vendor_ledger(vendor, date_from, date_to) if vendor else None
    return vendor, ledger, {"vendor": vendor_id, "from": date_from, "to": date_to}


@requires("finance.view")
def vendor_ledger(request):
    """
    Pick a vendor; every order, bill and payment in date order with a running
    balance — what the accountant reconciles with Tally. calc.vendor_ledger
    holds the convention; this view only chooses and prints.
    """
    vendor, ledger, chosen = _ledger_selection(request.GET)
    return render(request, "finance/vendor_ledger.html", {
        "vendor": vendor, "ledger": ledger, "chosen": chosen, "vendors": _vendors(),
    })


@require_POST
@requires("finance.view")
def vendor_ledger_excel(request):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    vendor, ledger, chosen = _ledger_selection(request.POST)
    if vendor is None:
        messages.error(request, "Pick a vendor first.")
        return redirect(reverse("finance_vendor_ledger"))
    book = Workbook()
    sheet = book.active
    sheet.title = "Ledger"
    headings = ["Date", "Kind", "Number", "Particulars", "Project", "Order value", "Bill",
                "Paid", "TDS", "Balance"]
    _sheet_header(sheet, headings, Font, PatternFill, Alignment)
    opening = ledger["opening"]
    sheet.append([chosen["from"], "Opening", "", f"Opening balance for {vendor.name}", "",
                  None, float(opening["bill"]), float(opening["paid"]), float(opening["tds"]),
                  float(opening["balance"])])
    for row in ledger["rows"]:
        sheet.append([
            row["date"], row["kind"].title(), row["number"], row["label"], row["project"].code,
            float(row["order_value"]) if row["order_value"] else None,
            float(row["bill"]) if row["bill"] else None,
            float(row["paid"]) if row["paid"] else None,
            float(row["tds"]) if row["tds"] else None,
            float(row["balance"]),
        ])
    totals = ledger["totals"]
    sheet.append([None, "Closing", "", "Closing balance", "", float(totals["order_value"]),
                  float(totals["bill"]), float(totals["paid"]), float(totals["tds"]),
                  float(ledger["closing"])])
    _sheet_finish(sheet, headings, headings.index("Order value"),
                  {"Particulars": 40, "Number": 12, "Kind": 10})
    return _xlsx(book, f"Ledger_{vendor.code}")


# ---------------------------------------------------------------- the TDS report

def _tds_selection(source):
    today = timezone.localdate()
    key, label, start, end = calc.quarter_bounds(today, (source.get("q") or "").strip())
    report = calc.tds_report(start, end)
    return report, {"q": key, "label": label, "from": start, "to": end}


@requires("finance.view")
def tds(request):
    """
    Per fiscal quarter (April–March, as analytics.periods), per vendor and
    section: the basic value TDS was computed on, the rate from the order, the
    TDS withheld and the amount paid. What the CA files 26Q from.
    """
    report, chosen = _tds_selection(request.GET)
    return render(request, "finance/tds.html", {
        "report": report, "chosen": chosen,
        "quarters": calc.fiscal_quarters(timezone.localdate()),
    })


@require_POST
@requires("finance.view")
def tds_excel(request):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    report, chosen = _tds_selection(request.POST)
    book = Workbook()
    sheet = book.active
    sheet.title = "TDS"
    headings = ["Section", "Vendor", "GSTIN", "Payments", "Rate %", "Taxable base",
                "Paid + TDS", "TDS", "Paid"]
    _sheet_header(sheet, headings, Font, PatternFill, Alignment)
    for row in report["rows"]:
        sheet.append([
            row["section"], row["vendor"].name, row["gstin"], row["count"], float(row["rate"]),
            float(row["base"]), float(row["gross"]), float(row["tds"]), float(row["paid"]),
        ])
    _sheet_finish(sheet, headings, headings.index("Taxable base"),
                  {"Vendor": 26, "GSTIN": 18, "Section": 10})
    return _xlsx(book, f"TDS_{chosen['q']}")
