"""
The home screen's figures — the money band, the module cards, the attention
list and the per-site cards.

>>> ANCHOR: HOME-SCREEN <<<
WHAT THIS FILE IS FOR
    One function, `home_for(user)`, returning everything the launchpad prints.
    The view hands it to the template and decides nothing.

⚠ EVERY FIGURE COMES FROM A CALCULATOR THAT ALREADY EXISTS — analytics.money,
  analytics.budget, sales.calc, tasks.models. Nothing here is a second
  implementation of a rule; this file only chooses which existing answers to put
  on the first screen. If a number on the home screen looks wrong, the fault is
  in the module that owns it, and the anchor for that module is where to look.

⚠ FILTERED BY PERMISSION, BLOCK BY BLOCK. The money band needs analytics.view
  (vendor side) and sales.view (buyer side); each module card needs the key that
  opens the module; the attention list only names things the reader can open.
  A figure a role cannot drill into is a figure it does not see — the tile rule
  applied to numbers.

⚠ COST. The launchpad is the page everybody loads most. Each block is a handful
  of queries and nothing is per row: bulk helpers throughout. A test pins the
  query count for an Admin (who sees every block).
"""
from datetime import date, timedelta
from decimal import Decimal

from django.urls import reverse

from accounts.perms import role_can

ZERO = Decimal("0")


def _lakh_crore(value):
    """₹ figures the way the office says them: 4.57 Cr, 24.7 L, 8,500."""
    value = Decimal(value or 0)
    sign = "−" if value < 0 else ""
    value = abs(value)
    if value >= 10_000_000:
        return f"{sign}₹{value / 10_000_000:.2f} Cr"
    if value >= 100_000:
        return f"{sign}₹{value / 100_000:.1f} L"
    return f"{sign}₹{int(value):,}".replace(",", ",")


def home_for(role, user=None, today=None):
    today = today or date.today()
    out = {"money": [], "cards": [], "attention": [], "sites": []}

    # ---------------------------------------------------------- the money band
    if role_can(role, "analytics.view"):
        from analytics import money, periods
        start = periods.fiscal_start(today)
        committed = money.add_up(money.documents("committed", start, today))
        paid = money.add_up(money.documents("paid", start, today))
        owed = money.add_up(money.outstanding())
        out["money"] += [
            ("Committed this year", _lakh_crore(committed["taxable"]), reverse("analytics_home"), ""),
            ("Paid this year", _lakh_crore(paid["net_payable"]), reverse("analytics_payments"), ""),
            ("Owed to vendors", _lakh_crore(owed["net_payable"]), reverse("analytics_payments"), "warn"),
        ]
    if role_can(role, "sales.view"):
        from sales import calc as scalc
        from sales.models import Booking
        live = list(Booking.objects.exclude(status=Booking.Status.CANCELLED).only("id", "agreement_value", "gst_percent"))
        figures = scalc.bulk_booking_figures(live, today=today)
        collected = sum((f["collected"] for f in figures.values()), ZERO)
        overdue = sum((f["overdue"] for f in figures.values()), ZERO)
        out["money"] += [
            ("Collected from buyers", _lakh_crore(collected), reverse("sales_receipts"), "good"),
            ("Buyers overdue", _lakh_crore(overdue), reverse("sales_collections"), "bad"),
        ]

    # ---------------------------------------------------------- module cards
    if role_can(role, "projects.view"):
        from projects.models import Project
        live = Project.objects.filter(status=Project.Status.WON).count()
        quoted = Project.objects.filter(status=Project.Status.QUOTED).count()
        out["cards"].append(_card("Projects", "#2E5C9A", reverse("project_list"), [
            ("Live", live, ""), ("Quoted, awaiting answer", quoted, ""),
        ]))
    if role_can(role, "register.view"):
        from projects.bom_models import PurchaseOrder
        S = PurchaseOrder.Status
        counts = {s: 0 for s in S.values}
        for status in PurchaseOrder.objects.values_list("status", flat=True):
            counts[status] += 1
        out["cards"].append(_card("Purchase orders", "#8A6D1F", reverse("po_register"), [
            ("Awaiting approval", counts[S.DRAFT], "warn" if counts[S.DRAFT] else ""),
            ("Approved, not delivered", counts[S.APPROVED], ""),
            ("Delivered, not paid", counts[S.DELIVERED], ""),
        ]))
        if counts[S.DRAFT]:
            out["attention"].append(("#B45309", f"{counts[S.DRAFT]} purchase order"
                                     f"{'s' if counts[S.DRAFT] != 1 else ''} waiting for approval",
                                     "Review", reverse("po_register") + "?status=draft"))
    if role_can(role, "tasks.view"):
        from tasks.models import Subtask
        open_rows = list(Subtask.objects.exclude(status=Subtask.Status.DONE)
                         .select_related("header__project").only(
                             "start", "days", "status", "header__project__name"))
        overdue = [t for t in open_rows if t.planned_end < today]
        week = [t for t in open_rows if today <= t.planned_end <= today + timedelta(days=7)]
        out["cards"].append(_card("Site work", "#C55A11", reverse("task_board"), [
            ("Tasks due this week", len(week), ""),
            ("Overdue", len(overdue), "bad" if overdue else ""),
        ]))
        by_site = {}
        for t in overdue:
            by_site[t.header.project.name] = by_site.get(t.header.project.name, 0) + 1
        for name, n in sorted(by_site.items(), key=lambda kv: -kv[1])[:2]:
            out["attention"].append(("#A32D2D", f"{n} task{'s' if n != 1 else ''} overdue on {name}",
                                     "Board", reverse("task_board")))
    if role_can(role, "sales.view"):
        from sales.models import Enquiry, Unit
        from sales import calc as scalc
        units = list(Unit.objects.filter(is_active=True).only("id"))
        status = scalc.bulk_unit_status(units)
        free = sum(1 for u in units if scalc.is_bookable(status.get(u.id, "available")))
        month_start = today.replace(day=1)
        enquiries = Enquiry.objects.filter(created_at__date__gte=month_start).count()
        out["cards"].append(_card("Sales", "#0F766E", reverse("sales_home"), [
            ("Units available", free, ""), ("Enquiries this month", enquiries, ""),
        ]))
        if role_can(role, "sales.view") and out["money"]:
            band = dict((label, val) for label, val, _u, _k in out["money"])
            if band.get("Buyers overdue") not in (None, "₹0"):
                out["attention"].append(("#0F766E", f"{band['Buyers overdue']} of demand letters overdue",
                                         "Collect", reverse("sales_collections")))
    if role_can(role, "compliance.view"):
        from compliance.models import ComplianceDocument
        soon = ComplianceDocument.objects.filter(
            expires_on__isnull=False, expires_on__gte=today,
            expires_on__lte=today + timedelta(days=60)).select_related("project", "item").order_by("expires_on")
        expired = ComplianceDocument.objects.filter(expires_on__isnull=False, expires_on__lt=today).count()
        soon = list(soon)
        out["cards"].append(_card("Compliance", "#A32D2D", reverse("compliance_home"), [
            ("Expiring in 60 days", len(soon), "warn" if soon else ""),
            ("Expired", expired, "bad" if expired else ""),
        ]))
        for doc in soon[:2]:
            days = (doc.expires_on - today).days
            out["attention"].append(("#A32D2D", f"{doc.item.name} for {doc.project.name} expires in {days} day{'s' if days != 1 else ''}",
                                     "Open", reverse("compliance_project", args=[doc.project_id])))
    if role_can(role, "drawings.view"):
        from drawings.models import Drawing, DrawingRevision
        received = DrawingRevision.objects.filter(approved_on__isnull=True).count()
        required = Drawing.objects.filter(is_active=True, revisions__isnull=True).count()
        out["cards"].append(_card("Drawings", "#1D4ED8", reverse("drawings_home"), [
            ("Awaiting approval", received, "warn" if received else ""),
            ("Required, not received", required, ""),
        ]))

    # ---------------------------------------------------------- per-site cards
    if role_can(role, "projects.view"):
        from analytics import budget
        from projects.models import Project
        from tasks.models import Subtask
        projects = list(Project.objects.filter(status=Project.Status.WON).order_by("code")[:6])
        budgets = {row["project"].id: row for row in budget.by_project(projects)} if role_can(role, "bom.view") else {}
        tasks_by = {p.id: [0, 0] for p in projects}
        for pid, status in Subtask.objects.filter(header__project__in=projects).values_list(
                "header__project_id", "status"):
            tasks_by[pid][1] += 1
            if status == Subtask.Status.DONE:
                tasks_by[pid][0] += 1
        sold_by = {}
        if role_can(role, "sales.view"):
            from sales.models import Booking
            from sales import calc as scalc
            bookings = list(Booking.objects.filter(unit__project__in=projects)
                            .exclude(status=Booking.Status.CANCELLED).select_related("unit"))
            figs = scalc.bulk_booking_figures(bookings)
            for b in bookings:
                row = sold_by.setdefault(b.unit.project_id, {"total": ZERO, "collected": ZERO})
                row["total"] += figs[b.id]["total"]
                row["collected"] += figs[b.id]["collected"]
        for p in projects:
            done, total = tasks_by[p.id]
            bars = []
            if p.id in budgets:
                pct = budgets[p.id]["used_pct"]
                bars.append(("Budget used", pct, "#A32D2D" if pct > 90 else "#2E5C9A"))
            bars.append(("Work done", int(round(done * 100 / total)) if total else 0, "#C55A11"))
            if p.id in sold_by and sold_by[p.id]["total"]:
                pct = int(round(sold_by[p.id]["collected"] * 100 / sold_by[p.id]["total"]))
                bars.append(("Collected of booked", pct, "#0F766E"))
            links = [("Orders", reverse("po_screen", args=[p.id]))]
            if role_can(role, "bom.view"):
                links.insert(0, ("BOM", reverse("bom_screen", args=[p.id])))
            links.append(("Tasks", reverse("task_board") + f"?project={p.id}"))
            if role_can(role, "compliance.view"):
                links.append(("Compliance", reverse("compliance_project", args=[p.id])))
            out["sites"].append({"project": p, "bars": bars, "links": links,
                                 "meta": f"{int(p.bua_sqft):,} sqft" + (f" · {p.floors}" if p.floors else "")})
    return out


def _card(title, color, url, rows):
    return {"title": title, "color": color, "url": url, "rows": rows}
