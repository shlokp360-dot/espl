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


def _month_bounds(day):
    first = day.replace(day=1)
    last_prev = first - timedelta(days=1)
    return first, last_prev.replace(day=1), last_prev


def _delta(now, before):
    """Percent change, or None when there is nothing to compare with."""
    if not before:
        return None
    return int(round((Decimal(now) - Decimal(before)) * 100 / Decimal(before)))


def home_for(role, user=None, today=None):
    today = today or date.today()
    out = {"money": [], "cards": [], "attention": [], "sites": [],
           "kpis": [], "mine": [], "activity": [], "upcoming": [], "chart": "", "donut": None}
    first, prev_first, prev_last = _month_bounds(today)

    # ---------------------------------------------------- this month vs last
    # >>> ANCHOR: HOME-SCREEN <<< four cards, each a figure the office asks for
    # weekly, with the change against last month beside it.
    if role_can(role, "analytics.view"):
        from analytics import charts, money, periods
        now_c = money.add_up(money.documents("committed", first, today))["taxable"]
        was_c = money.add_up(money.documents("committed", prev_first, prev_last))["taxable"]
        now_p = money.add_up(money.documents("paid", first, today))["net_payable"]
        was_p = money.add_up(money.documents("paid", prev_first, prev_last))["net_payable"]
        out["kpis"] += [
            {"label": "Committed this month", "value": _lakh_crore(now_c), "delta": _delta(now_c, was_c),
             "url": reverse("analytics_home")},
            {"label": "Paid this month", "value": _lakh_crore(now_p), "delta": _delta(now_p, was_p),
             "url": reverse("analytics_payments")},
        ]
        # One fetch per stage for the whole fiscal year so far, bucketed by
        # month here — two queries per month would be a query per row.
        months = [(key, label, periods.bounds(today, key)[:2]) for key, label in periods.months_so_far(today)]
        year_a, year_b = months[0][2][0], months[-1][2][1]
        bucket = {stage: {key: [] for key, _l, _ab in months}
                  for stage in ("committed", "paid")}
        for stage in bucket:
            field = money.STAGE_DATE[stage]
            for order in money.documents(stage, year_a, year_b):
                when = getattr(order, field).date()
                for key, _l, (a, b) in months:
                    if a <= when <= b:
                        bucket[stage][key].append(order)
                        break
        rows = [{"label": label.split()[0], "values": [
                    money.add_up(bucket["committed"][key])["taxable"],
                    money.add_up(bucket["paid"][key])["net_payable"]]}
                for key, label, _ab in months]
        out["chart"] = charts.bars(rows, [{"label": "Committed", "colour": charts.PALETTE[0]},
                                          {"label": "Paid", "colour": charts.PALETTE[5]}], height=170)
    if role_can(role, "sales.view"):
        from sales.models import Booking, CustomerReceipt, Unit
        from sales import calc as scalc
        from analytics import charts
        got_now = sum((scalc.receipt_credit(r) for r in CustomerReceipt.objects.filter(received_on__gte=first, received_on__lte=today)), ZERO)
        got_was = sum((scalc.receipt_credit(r) for r in CustomerReceipt.objects.filter(received_on__gte=prev_first, received_on__lte=prev_last)), ZERO)
        bk_now = Booking.objects.filter(booked_on__gte=first, booked_on__lte=today).exclude(status=Booking.Status.CANCELLED).count()
        bk_was = Booking.objects.filter(booked_on__gte=prev_first, booked_on__lte=prev_last).exclude(status=Booking.Status.CANCELLED).count()
        out["kpis"] += [
            {"label": "Collected this month", "value": _lakh_crore(got_now), "delta": _delta(got_now, got_was),
             "url": reverse("sales_receipts")},
            {"label": "Bookings this month", "value": str(bk_now), "delta": _delta(bk_now, bk_was),
             "url": reverse("sales_bookings")},
        ]
        units = list(Unit.objects.filter(is_active=True, project__status="won").only("id"))
        st = scalc.bulk_unit_status(units)
        counts = {"available": 0, "booked": 0, "registered": 0}
        for u in units:
            k = st.get(u.id, "available")
            k = "available" if k == "cancelled" else k
            counts[k] = counts.get(k, 0) + 1
        slices = [{"label": "Available", "value": counts["available"], "colour": "#2E5C9A"},
                  {"label": "Booked", "value": counts["booked"], "colour": "#B45309"},
                  {"label": "Registered", "value": counts["registered"], "colour": "#375623"}]
        out["donut"] = {"svg": charts.donut(slices, size=150), "rows": slices, "total": len(units),
                        "title": "Units, all live sites", "url": reverse("sales_units")}
    elif role_can(role, "register.view"):
        from analytics import charts
        from projects.bom_models import PurchaseOrder
        S = PurchaseOrder.Status
        c = {s: 0 for s in S.values}
        for st in PurchaseOrder.objects.values_list("status", flat=True):
            c[st] += 1
        slices = [{"label": "Draft", "value": c[S.DRAFT], "colour": "#8A9099"},
                  {"label": "Approved", "value": c[S.APPROVED], "colour": "#2E5C9A"},
                  {"label": "Delivered", "value": c[S.DELIVERED], "colour": "#375623"},
                  {"label": "Paid", "value": c[S.PAID], "colour": "#4A3B79"}]
        out["donut"] = {"svg": charts.donut(slices, size=150), "rows": slices, "total": sum(c.values()),
                        "title": "Orders by status", "url": reverse("po_register")}

    # ------------------------------------------------------------ your work
    if user is not None:
        from tasks.models import Subtask
        mine = list(Subtask.objects.filter(assignee=user).exclude(status=Subtask.Status.DONE)
                    .select_related("header__project").only("title", "start", "days", "status", "header__project__name"))
        mine.sort(key=lambda t: t.planned_end)
        for t in mine[:5]:
            late = (today - t.planned_end).days
            out["mine"].append({"what": t.title, "where": t.header.project.name,
                                "when": t.planned_end, "late": late if late > 0 else 0,
                                "url": reverse("task_mine")})
        if role_can(role, "sales.edit"):
            from sales.models import Enquiry
            for e in Enquiry.objects.filter(assigned_to=user, stage__in=["new", "visited", "negotiating"]).order_by("-updated_at")[:3]:
                out["mine"].append({"what": f"Enquiry · {e.name}", "where": e.project.name,
                                    "when": None, "late": 0, "url": reverse("sales_enquiry_form", args=[e.id])})
        if role_can(role, "po.approve"):
            from projects.bom_models import PurchaseOrder
            n = PurchaseOrder.objects.filter(status=PurchaseOrder.Status.DRAFT).count()
            if n:
                out["mine"].insert(0, {"what": f"{n} order{'s' if n != 1 else ''} waiting for your approval",
                                       "where": "", "when": None, "late": 0,
                                       "url": reverse("po_register") + "?status=draft"})

    # ------------------------------------------------------- recent activity
    events = []
    if role_can(role, "register.view"):
        from projects.bom_models import PurchaseOrder
        for o in (PurchaseOrder.objects.filter(approved_at__isnull=False).select_related("vendor", "approved_by")
                  .order_by("-approved_at")[:5]):
            events.append((o.approved_at, "Order", f"{o.number} to {o.vendor.name} approved",
                           o.approved_by.get_full_name() if o.approved_by else "", reverse("po_detail", args=[o.project_id, o.id]) + "?from=register"))
    if role_can(role, "sales.view"):
        from sales.models import Booking, CustomerReceipt
        for b in Booking.objects.select_related("unit", "customer").order_by("-booked_on", "-id")[:4]:
            events.append((b.booked_on, "Sales", f"{b.unit.number} booked by {b.customer.name}", "",
                           reverse("sales_booking", args=[b.id])))
        for r in CustomerReceipt.objects.select_related("booking__customer").order_by("-received_on", "-id")[:4]:
            events.append((r.received_on, "Sales", f"{_lakh_crore(r.amount)} received from {r.booking.customer.name}", "",
                           reverse("sales_booking", args=[r.booking_id])))
    if role_can(role, "compliance.view"):
        from compliance.models import ComplianceDocument
        for d in ComplianceDocument.objects.select_related("item", "project").order_by("-uploaded_at")[:4]:
            events.append((d.uploaded_at, "Compliance", f"{d.item.name} filed for {d.project.name}", "",
                           reverse("compliance_project", args=[d.project_id])))
    from datetime import datetime
    def _day(e):
        return e[0].date() if isinstance(e[0], datetime) else e[0]
    events.sort(key=_day, reverse=True)
    out["activity"] = [{"when": e[0], "kind": e[1], "text": e[2], "who": e[3], "url": e[4]} for e in events[:8]]

    # -------------------------------------------------------------- upcoming
    horizon = today + timedelta(days=14)
    if role_can(role, "tasks.view"):
        from tasks.models import Subtask
        for t in (Subtask.objects.exclude(status=Subtask.Status.DONE).select_related("header__project", "assignee")
                  .only("title", "start", "days", "header__project__name", "assignee__first_name", "assignee__last_name")):
            if today <= t.planned_end <= horizon:
                out["upcoming"].append((t.planned_end, "Task due", t.title, t.header.project.name, reverse("task_board")))
    if role_can(role, "compliance.view"):
        from compliance.models import ComplianceDocument
        for d in ComplianceDocument.objects.filter(expires_on__gte=today, expires_on__lte=today + timedelta(days=60)).select_related("item", "project"):
            out["upcoming"].append((d.expires_on, "Expiry", d.item.name, d.project.name, reverse("compliance_project", args=[d.project_id])))
    if role_can(role, "sales.view"):
        from sales.models import Demand
        for d in Demand.objects.filter(due_on__gte=today, due_on__lte=horizon).select_related("booking__customer", "booking__unit"):
            out["upcoming"].append((d.due_on, "Demand due", f"{_lakh_crore(d.amount)} · {d.booking.customer.name}", d.booking.unit.number, reverse("sales_booking", args=[d.booking_id])))
    out["upcoming"].sort(key=lambda e: e[0])
    out["upcoming"] = [{"when": e[0], "kind": e[1], "what": e[2], "where": e[3], "url": e[4]} for e in out["upcoming"][:8]]

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
