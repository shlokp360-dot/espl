"""
The sales screens: units, enquiries, bookings, demands, receipts, collections.

>>> ANCHOR: SALES-SCREENS <<<

WHO MAY DO WHAT (accounts/perms.py)
    sales.view      Admin · Project manager · Accountant — every read, every PDF, every Excel
    sales.edit      Admin · Project manager — units, enquiries, bookings, cancel, transfer
    sales.collect   Admin · Accountant — raise a demand, record a receipt

⚠ NO ARITHMETIC HERE. Every figure comes from `sales.calc`, by name, and the
  list screens use its bulk functions so the query count does not grow with
  the rows. Every write goes through `sales.services` and is a POST.

⚠ RAW IDS FROM THE QUERY STRING ARE `.isdigit()`-GUARDED before they reach a
  filter, and anything belonging to a project is fetched scoped to it.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from accounts.perms import can, requires
from masters.models import CompanyProfile
from projects.models import Project
from sales import calc, services
from sales.models import (
    Booking, Customer, CustomerReceipt, Demand, Enquiry, EnquirySource, PaymentMilestone,
    ReceiptMode, SiteVisit, Unit, UnitKind,
)
from sales.services import SalesError
from tasks.models import TaskHeader

# --------------------------------------------------------------- helpers
def live_projects():
    """Sales starts at Won — a quoted job has nothing to sell."""
    return Project.objects.filter(
        status__in=[Project.Status.WON, Project.Status.COMPLETED]).order_by("name")


def _project_from(request, projects, key="project"):
    """The project the query string names, else the first live one, else None."""
    raw = (request.GET.get(key) or request.POST.get(key) or "").strip()
    if raw.isdigit():
        for project in projects:
            if project.pk == int(raw):
                return project
    return projects[0] if projects else None


def _date(raw):
    return parse_date((raw or "").strip()) if raw else None


def _decimal(raw, default=None):
    raw = (raw or "").strip().replace(",", "")
    if raw == "":
        return default
    try:
        return Decimal(raw)
    except ArithmeticError:
        return None


def _people():
    from django.contrib.auth import get_user_model
    return get_user_model().objects.filter(is_active=True).order_by("first_name", "username")


def _pill(status):
    """The status word to a pill class. Words, not colours alone — the word is printed too."""
    return {
        "available": "p-draft", "booked": "p-approved", "registered": "p-paid",
        "cancelled": "p-lost", "agreement": "p-quoted",
        "open": "p-draft", "part_paid": "p-onsheet", "paid": "p-paid",
        "new": "p-draft", "visited": "p-quoted", "negotiating": "p-onsheet",
        "lost": "p-lost", "not_due": "p-draft", "0_30": "p-onsheet",
        "31_60": "p-onsheet", "61_90": "p-lost", "90_plus": "p-lost",
    }.get(status, "p-draft")


STATUS_WORDS = {"available": "Available", "booked": "Booked", "registered": "Registered",
                "cancelled": "Cancelled", "open": "Open", "part_paid": "Part-paid", "paid": "Paid"}


def _schedule_rows_from_post(post, headers_by_id):
    """The editable schedule rows of the booking form and the booking screen."""
    rows = []
    for index in range(1, 25):
        name = (post.get(f"ms_name_{index}") or "").strip()
        percent = (post.get(f"ms_pct_{index}") or "").strip()
        if not name and not percent:
            continue
        header_id = (post.get(f"ms_header_{index}") or "").strip()
        rows.append({
            "name": name, "percent": percent or "0",
            "due_on": _date(post.get(f"ms_due_{index}")),
            "task_header": headers_by_id.get(int(header_id)) if header_id.isdigit() else None,
        })
    return rows


# ------------------------------------------------------------ the dashboard
@requires("sales.view")
def home(request):
    """KPIs across every live project, a per-project table, and the funnel."""
    today = timezone.localdate()
    projects = list(live_projects())
    units = list(Unit.objects.filter(project__in=projects, is_active=True))
    status_of = calc.bulk_unit_status(units)
    bookings = list(Booking.objects.filter(unit__project__in=projects)
                    .exclude(status=Booking.Status.CANCELLED).select_related("unit"))
    figures = calc.bulk_booking_figures(bookings, today)

    month_start = today.replace(day=1)
    enquiries_this_month = Enquiry.objects.filter(
        project__in=projects, created_at__date__gte=month_start).count()
    funnel_counts = dict(Enquiry.objects.filter(project__in=projects)
                         .values_list("stage").annotate(n=Count("id")).values_list("stage", "n"))
    funnel = [{"stage": value, "label": label, "count": funnel_counts.get(value, 0)}
              for value, label in Enquiry.Stage.choices]

    per_project = []
    for project in projects:
        own_units = [u for u in units if u.project_id == project.id]
        own_bookings = [b for b in bookings if b.unit.project_id == project.id]
        sold = sum(1 for u in own_units if status_of[u.id] in ("booked", "registered"))
        per_project.append({
            "project": project,
            "units": len(own_units),
            "sold": sold,
            "available": len(own_units) - sold,
            "booked_pct": calc.percent_of(sold, len(own_units)),
            "value": sum((figures[b.id]["agreement"] for b in own_bookings), calc.ZERO),
            "collected": sum((figures[b.id]["collected"] for b in own_bookings), calc.ZERO),
            "outstanding": sum((figures[b.id]["outstanding"] for b in own_bookings), calc.ZERO),
            "overdue": sum((figures[b.id]["overdue"] for b in own_bookings), calc.ZERO),
        })

    kpis = {
        "available": sum(1 for u in units if calc.is_bookable(status_of[u.id])),
        "booked": sum(1 for u in units if status_of[u.id] == "booked"),
        "registered": sum(1 for u in units if status_of[u.id] == "registered"),
        "enquiries_month": enquiries_this_month,
        "value": sum((row["value"] for row in per_project), calc.ZERO),
        "collected": sum((row["collected"] for row in per_project), calc.ZERO),
        "outstanding": sum((row["outstanding"] for row in per_project), calc.ZERO),
        "overdue": sum((row["overdue"] for row in per_project), calc.ZERO),
    }
    return render(request, "sales/home.html", {
        "kpis": kpis, "per_project": per_project, "funnel": funnel, "projects": projects,
    })


# ------------------------------------------------------------------- units
@requires("sales.view")
def units(request):
    """The grid of one project's units, grouped by block and floor."""
    projects = list(live_projects())
    project = _project_from(request, projects)
    rows, groups = [], []
    if project:
        unit_rows = list(Unit.objects.filter(project=project).order_by("block", "-floor", "number"))
        status_of = calc.bulk_unit_status(unit_rows)
        live = {b.unit_id: b for b in Booking.objects.filter(unit__project=project)
                .exclude(status=Booking.Status.CANCELLED).select_related("customer")}
        for unit in unit_rows:
            status = status_of[unit.id]
            rows.append({"unit": unit, "status": status, "word": STATUS_WORDS[status],
                         "pill": _pill(status), "bookable": calc.is_bookable(status) and unit.is_active,
                         "booking": live.get(unit.id)})
        # Group by (block, floor), in the order the rows already carry.
        current = None
        for row in rows:
            key = (row["unit"].block, row["unit"].floor)
            if current is None or current["key"] != key:
                current = {"key": key, "block": key[0], "floor": key[1], "rows": []}
                groups.append(current)
            current["rows"].append(row)
    counts = {word: sum(1 for r in rows if r["status"] == word)
              for word in ("available", "booked", "registered", "cancelled")}
    return render(request, "sales/units.html", {
        "projects": projects, "project": project, "groups": groups, "counts": counts,
        "total": len(rows),
    })


@requires("sales.edit")
def unit_form(request, unit_id=None):
    """Add or edit one unit."""
    projects = list(live_projects())
    unit = get_object_or_404(Unit, pk=unit_id) if unit_id else None
    project = unit.project if unit else _project_from(request, projects)
    if project is None:
        messages.error(request, "No project is Won yet. Units belong to a Won project.")
        return redirect("sales_units")

    if request.method == "POST":
        if unit is None:
            unit = Unit(project=project)
        unit.number = (request.POST.get("number") or "").strip()[:20]
        unit.block = (request.POST.get("block") or "").strip()[:20]
        floor = (request.POST.get("floor") or "0").strip()
        unit.floor = int(floor) if floor.lstrip("-").isdigit() else 0
        unit.kind = request.POST.get("kind") or UnitKind.OTHER
        unit.carpet_sqft = _decimal(request.POST.get("carpet_sqft"), Decimal("0"))
        unit.saleable_sqft = _decimal(request.POST.get("saleable_sqft"), Decimal("0"))
        unit.base_price = _decimal(request.POST.get("base_price"), Decimal("0"))
        unit.is_active = request.POST.get("is_active") == "yes" if unit.pk else True
        errors = []
        if not unit.number:
            errors.append("Type the unit number, e.g. A-101.")
        if None in (unit.carpet_sqft, unit.saleable_sqft, unit.base_price):
            errors.append("Areas and the price must be numbers.")
        if unit.kind not in UnitKind.values:
            errors.append("Choose a type.")
        if not errors and Unit.objects.filter(project=project, number=unit.number).exclude(pk=unit.pk).exists():
            errors.append(f"{project.code} already has a unit {unit.number}.")
        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            unit.save()
            messages.success(request, f"{unit.number} saved on {project.code}.")
            return redirect(f"{reverse('sales_units')}?project={project.pk}")

    return render(request, "sales/unit_form.html", {
        "project": project, "unit": unit, "kinds": UnitKind.choices,
    })


@requires("sales.edit")
def units_bulk(request):
    """
    Generate a block of units: floors × units per floor.

    Numbers are BLOCK-FLOOR-POSITION, e.g. A-101 … A-704. A number that
    already exists is skipped, not overwritten, and the message says how many.
    """
    projects = list(live_projects())
    project = _project_from(request, projects)
    if project is None:
        messages.error(request, "No project is Won yet. Units belong to a Won project.")
        return redirect("sales_units")

    form = {"block": "A", "floor_from": "1", "floor_to": "7", "per_floor": "4",
            "kind": UnitKind.TWO_BHK, "carpet_sqft": "", "saleable_sqft": "", "base_price": ""}
    if request.method == "POST":
        form.update({key: (request.POST.get(key) or "").strip() for key in form})
        errors = []
        numbers = {}
        for key in ("floor_from", "floor_to", "per_floor"):
            if not form[key].isdigit():
                errors.append(f"{key.replace('_', ' ').capitalize()} must be a whole number.")
            else:
                numbers[key] = int(form[key])
        carpet = _decimal(form["carpet_sqft"], Decimal("0"))
        saleable = _decimal(form["saleable_sqft"], Decimal("0"))
        price = _decimal(form["base_price"], Decimal("0"))
        if None in (carpet, saleable, price):
            errors.append("Areas and the price must be numbers.")
        if form["kind"] not in UnitKind.values:
            errors.append("Choose a type.")
        if not errors and numbers["floor_from"] > numbers["floor_to"]:
            errors.append("The first floor is above the last floor.")
        if not errors and (numbers["per_floor"] < 1 or numbers["per_floor"] > 50):
            errors.append("Units per floor must be between 1 and 50.")
        if not errors and (numbers["floor_to"] - numbers["floor_from"]) > 99:
            errors.append("That is more than 100 floors.")
        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            block = form["block"][:20]
            taken = set(Unit.objects.filter(project=project).values_list("number", flat=True))
            made, skipped = 0, 0
            for floor in range(numbers["floor_from"], numbers["floor_to"] + 1):
                for position in range(1, numbers["per_floor"] + 1):
                    number = f"{block}-{floor}{position:02d}" if block else f"{floor}{position:02d}"
                    if number in taken:
                        skipped += 1
                        continue
                    Unit.objects.create(project=project, number=number, block=block, floor=floor,
                                        kind=form["kind"], carpet_sqft=carpet, saleable_sqft=saleable,
                                        base_price=price)
                    made += 1
            messages.success(
                request, f"{made} unit{'' if made == 1 else 's'} added to {project.code}."
                + (f" {skipped} already existed and were left alone." if skipped else ""))
            return redirect(f"{reverse('sales_units')}?project={project.pk}")

    return render(request, "sales/units_bulk.html", {
        "project": project, "form": form, "kinds": UnitKind.choices,
    })


# --------------------------------------------------------------- enquiries
@requires("sales.view")
def enquiries(request):
    """Every enquiry, with the stage, assignee and search filters."""
    projects = list(live_projects())
    rows = Enquiry.objects.select_related("project", "assigned_to")
    applied = {}
    raw = (request.GET.get("project") or "").strip()
    if raw.isdigit():
        rows = rows.filter(project_id=int(raw))
        applied["project"] = int(raw)
    stage = (request.GET.get("stage") or "").strip()
    if stage == "open":
        rows = rows.filter(stage__in=Enquiry.OPEN_STAGES)
        applied["stage"] = stage
    elif stage in Enquiry.Stage.values:
        rows = rows.filter(stage=stage)
        applied["stage"] = stage
    assigned = (request.GET.get("assigned") or "").strip()
    if assigned.isdigit():
        rows = rows.filter(assigned_to_id=int(assigned))
        applied["assigned"] = int(assigned)
    q = (request.GET.get("q") or "").strip()
    if q:
        rows = rows.filter(Q(name__icontains=q) | Q(phone__icontains=q) | Q(broker_name__icontains=q))
        applied["q"] = q
    rows = list(rows.order_by("-created_at", "-id")[:500])
    visits = dict(SiteVisit.objects.filter(enquiry__in=rows).values_list("enquiry_id")
                  .annotate(n=Count("id")).values_list("enquiry_id", "n"))
    for row in rows:
        row.visit_count = visits.get(row.id, 0)
        row.pill = _pill(row.stage)
    return render(request, "sales/enquiries.html", {
        "rows": rows, "projects": projects, "applied": applied, "people": _people(),
        "stages": Enquiry.Stage.choices,
    })


@requires("sales.edit")
def enquiry_form(request, enquiry_id=None):
    """Add or edit an enquiry. Visits and stage changes have their own POSTs."""
    projects = list(live_projects())
    enquiry = get_object_or_404(Enquiry.objects.select_related("project"), pk=enquiry_id) if enquiry_id else None
    if enquiry is None and not projects:
        messages.error(request, "No project is Won yet. An enquiry is about a Won project.")
        return redirect("sales_enquiries")

    fields = ("name", "phone", "email", "source", "broker_name", "interested_in", "budget", "notes")
    form = {key: (getattr(enquiry, key) if enquiry else "") for key in fields}
    form["source"] = form["source"] or EnquirySource.WALK_IN
    form["assigned_to"] = enquiry.assigned_to_id if enquiry else None
    form["project"] = enquiry.project_id if enquiry else (projects[0].pk if projects else None)

    if request.method == "POST":
        form.update({key: (request.POST.get(key) or "").strip() for key in fields})
        assigned = (request.POST.get("assigned_to") or "").strip()
        form["assigned_to"] = int(assigned) if assigned.isdigit() else None
        if enquiry is None:
            form["project"] = _project_from(request, projects).pk
        budget = _decimal(form["budget"])
        errors = []
        if not form["name"]:
            errors.append("Type the name.")
        if not form["phone"] or not form["phone"].isdigit():
            errors.append("The phone is digits only, and it is required.")
        if form["source"] not in EnquirySource.values:
            errors.append("Choose a source.")
        if form["interested_in"] and form["interested_in"] not in UnitKind.values:
            errors.append("Choose a unit type.")
        if form["budget"] and budget is None:
            errors.append("The budget must be a number.")
        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            row = enquiry or Enquiry(project_id=form["project"])
            row.name, row.phone, row.email = form["name"][:160], form["phone"], form["email"]
            row.source, row.broker_name = form["source"], form["broker_name"][:120]
            row.interested_in, row.budget, row.notes = form["interested_in"], budget, form["notes"]
            row.assigned_to = (_people().filter(pk=form["assigned_to"]).first()
                               if form["assigned_to"] else None)
            row.save()
            messages.success(request, f"Enquiry from {row.name} saved.")
            return redirect("sales_enquiries")

    return render(request, "sales/enquiry_form.html", {
        "enquiry": enquiry, "form": form, "projects": projects, "people": _people(),
        "sources": EnquirySource.choices, "kinds": UnitKind.choices, "stages": Enquiry.Stage.choices,
        "visits": list(enquiry.visits.all()) if enquiry else [], "today": timezone.localdate(),
        "pill": _pill(enquiry.stage) if enquiry else "",
        "units": _bookable_units(enquiry.project) if enquiry else [],
    })


def _bookable_units(project):
    rows = list(Unit.objects.filter(project=project, is_active=True))
    status_of = calc.bulk_unit_status(rows)
    return [u for u in rows if calc.is_bookable(status_of[u.id])]


@require_POST
@requires("sales.edit")
def enquiry_visit(request, enquiry_id):
    """Record a site visit. A New enquiry becomes Visited."""
    enquiry = get_object_or_404(Enquiry, pk=enquiry_id)
    visited_on = _date(request.POST.get("visited_on")) or timezone.localdate()
    SiteVisit.objects.create(enquiry=enquiry, visited_on=visited_on,
                             note=(request.POST.get("note") or "").strip()[:300],
                             recorded_by=request.user)
    if enquiry.stage == Enquiry.Stage.NEW:
        enquiry.stage = Enquiry.Stage.VISITED
        enquiry.save(update_fields=["stage", "updated_at"])
    messages.success(request, f"Visit on {visited_on:%d/%m/%Y} recorded for {enquiry.name}.")
    return redirect("sales_enquiry_form", enquiry_id=enquiry.pk)


@require_POST
@requires("sales.edit")
def enquiry_stage(request, enquiry_id):
    """
    Move the stage by hand. Booked is NOT set here — booking a unit sets it,
    so the funnel cannot say Booked with no booking behind it.
    """
    enquiry = get_object_or_404(Enquiry, pk=enquiry_id)
    stage = (request.POST.get("stage") or "").strip()
    if stage not in Enquiry.Stage.values or stage == Enquiry.Stage.BOOKED:
        messages.error(request, "Choose a stage. Booked is set by booking a unit.")
        return redirect("sales_enquiry_form", enquiry_id=enquiry.pk)
    reason = (request.POST.get("lost_reason") or "").strip()[:200]
    if stage == Enquiry.Stage.LOST and not reason:
        messages.error(request, "Type why it was lost — it is the one thing worth knowing later.")
        return redirect("sales_enquiry_form", enquiry_id=enquiry.pk)
    enquiry.stage = stage
    enquiry.lost_reason = reason if stage == Enquiry.Stage.LOST else ""
    enquiry.save(update_fields=["stage", "lost_reason", "updated_at"])
    messages.success(request, f"{enquiry.name} is now {enquiry.get_stage_display()}.")
    return redirect("sales_enquiry_form", enquiry_id=enquiry.pk)


# ---------------------------------------------------------------- bookings
@requires("sales.edit")
def booking_new(request, unit_id):
    """Book one unit: the customer by phone, the value, and the schedule as rows."""
    unit = get_object_or_404(Unit.objects.select_related("project"), pk=unit_id)
    project = unit.project
    headers = list(TaskHeader.objects.filter(project=project).order_by("start", "id"))
    headers_by_id = {h.id: h for h in headers}
    enquiry = None
    raw = (request.GET.get("enquiry") or request.POST.get("enquiry") or "").strip()
    if raw.isdigit():
        enquiry = Enquiry.objects.filter(pk=int(raw), project=project).first()

    form = {
        "phone": enquiry.phone if enquiry else "", "name": enquiry.name if enquiry else "",
        "email": enquiry.email if enquiry else "", "pan": "", "address": "",
        "agreement_value": f"{unit.base_price:.2f}", "gst_percent": "5",
        "booked_on": timezone.localdate().isoformat(),
    }
    schedule = [{"name": name, "percent": f"{pct:.2f}", "due_on": "", "task_header": ""}
                for name, pct in calc.DEFAULT_SCHEDULE]

    if request.method == "POST":
        form.update({key: (request.POST.get(key) or "").strip() for key in form})
        rows = _schedule_rows_from_post(request.POST, headers_by_id)
        schedule = [{"name": r["name"], "percent": r["percent"],
                     "due_on": r["due_on"].isoformat() if r["due_on"] else "",
                     "task_header": r["task_header"].id if r["task_header"] else ""} for r in rows]
        try:
            booking = services.book_unit(
                unit, phone=form["phone"], name=form["name"], email=form["email"],
                pan=form["pan"], address=form["address"],
                agreement_value=_decimal(form["agreement_value"]) or Decimal("0"),
                gst_percent=_decimal(form["gst_percent"], Decimal("5")) or Decimal("0"),
                booked_on=_date(form["booked_on"]), schedule=rows, enquiry=enquiry, by=request.user)
        except SalesError as error:
            messages.error(request, str(error))
        else:
            messages.success(request, f"{booking.number}: {unit.number} booked to {booking.customer.name}.")
            return redirect("sales_booking", booking_id=booking.pk)

    return render(request, "sales/booking_new.html", {
        "unit": unit, "project": project, "form": form, "schedule": schedule,
        "headers": headers, "enquiry": enquiry, "status": unit.status,
        "schedule_total": calc.schedule_total_percent(schedule),
        "existing": Customer.objects.filter(phone=form["phone"]).first() if form["phone"] else None,
    })


@requires("sales.view")
def bookings(request):
    """The register of bookings across projects, with the money columns."""
    today = timezone.localdate()
    projects = list(live_projects())
    rows = Booking.objects.select_related("unit__project", "customer")
    applied = {}
    raw = (request.GET.get("project") or "").strip()
    if raw.isdigit():
        rows = rows.filter(unit__project_id=int(raw))
        applied["project"] = int(raw)
    status = (request.GET.get("status") or "").strip()
    if status in Booking.Status.values:
        rows = rows.filter(status=status)
        applied["status"] = status
    elif status != "all":
        rows = rows.exclude(status=Booking.Status.CANCELLED)
        applied["status"] = "live"
    q = (request.GET.get("q") or "").strip()
    if q:
        rows = rows.filter(Q(number__icontains=q) | Q(customer__name__icontains=q)
                           | Q(customer__phone__icontains=q) | Q(unit__number__icontains=q))
        applied["q"] = q
    rows = list(rows.order_by("-booked_on", "-id")[:500])
    figures = calc.bulk_booking_figures(rows, today)
    for row in rows:
        row.figures = figures[row.id]
        row.pill = _pill(row.status)
    totals = {key: sum((figures[r.id][key] for r in rows), calc.ZERO)
              for key in ("agreement", "total", "collected", "outstanding", "overdue")}
    return render(request, "sales/bookings.html", {
        "rows": rows, "projects": projects, "applied": applied, "totals": totals,
        "statuses": Booking.Status.choices,
    })


def _booking_context(booking, today):
    demands = list(booking.demands.select_related("milestone").order_by("raised_on", "id"))
    receipts = list(booking.receipts.select_related("demand").order_by("received_on", "id"))
    milestones = list(booking.milestones.select_related("task_header").order_by("sequence", "id"))
    demand_figures = calc.bulk_demand_figures(demands)
    demand_by_milestone = {d.milestone_id: d for d in demands if d.milestone_id}
    schedule = []
    for milestone in milestones:
        demand = demand_by_milestone.get(milestone.id)
        schedule.append({
            "milestone": milestone,
            "amount": calc.milestone_amount(booking.agreement_value, milestone.percent),
            "demand": demand,
            "status": demand_figures[demand.id]["status"] if demand else "",
            "word": STATUS_WORDS.get(demand_figures[demand.id]["status"], "") if demand else "Not raised",
            "pill": _pill(demand_figures[demand.id]["status"]) if demand else "p-draft",
        })
    for demand in demands:
        demand.figures = demand_figures[demand.id]
        demand.word = STATUS_WORDS[demand.figures["status"]]
        demand.pill = _pill(demand.figures["status"])
    figures = calc.bulk_booking_figures([booking], today)[booking.id]
    return {
        "booking": booking, "demands": demands, "receipts": receipts, "milestones": milestones,
        "schedule": schedule, "figures": figures,
        "schedule_total": calc.schedule_total_percent(milestones),
        "ledger": calc.ledger(booking, demands, receipts),
        "events": list(booking.events.select_related("by")),
        "suggested_tds": calc.suggested_tds(booking),
        "pill": _pill(booking.status),
        "unit_status": calc.unit_status(booking.unit, [booking]),
    }


@requires("sales.view")
def booking(request, booking_id):
    """One sale: the customer, the value ladder, the schedule, and the money."""
    booking = get_object_or_404(
        Booking.objects.select_related("unit__project", "customer", "enquiry", "transferred_from", "created_by"),
        pk=booking_id)
    today = timezone.localdate()
    context = _booking_context(booking, today)
    context.update({
        "today": today,
        "headers": list(TaskHeader.objects.filter(project=booking.unit.project).order_by("start", "id")),
        "can_edit_schedule": can(request.user, "sales.edit") and booking.is_live,
    })
    return render(request, "sales/booking.html", context)


@require_POST
@requires("sales.edit")
def booking_schedule(request, booking_id):
    """Rewrite the schedule rows from the booking screen. Must still total 100."""
    booking = get_object_or_404(Booking.objects.select_related("unit__project"), pk=booking_id)
    headers_by_id = {h.id: h for h in TaskHeader.objects.filter(project=booking.unit.project)}
    rows = _schedule_rows_from_post(request.POST, headers_by_id)
    try:
        if not booking.is_live:
            raise SalesError(f"{booking.number} is cancelled; its schedule is closed.")
        services.write_schedule(booking, rows, by=request.user)
    except SalesError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, f"Schedule saved for {booking.number}.")
    return redirect("sales_booking", booking_id=booking.pk)


@require_POST
@requires("sales.edit")
def booking_mark(request, booking_id):
    """Agreement signed, or sale registered."""
    booking = get_object_or_404(Booking, pk=booking_id)
    step = (request.POST.get("step") or "").strip()
    on = _date(request.POST.get("on"))
    try:
        if step == "agreement":
            services.mark_agreement(booking, on=on, by=request.user)
        elif step == "registered":
            services.mark_registered(booking, on=on, by=request.user)
        else:
            raise SalesError("Choose Agreement or Registered.")
    except SalesError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, f"{booking.number} is now {booking.get_status_display()}.")
    return redirect("sales_booking", booking_id=booking.pk)


@requires("sales.edit")
def booking_cancel(request, booking_id):
    """A confirm screen that shows the refund before anything is written."""
    booking = get_object_or_404(Booking.objects.select_related("unit", "customer"), pk=booking_id)
    deduction_pct = _decimal(request.POST.get("deduction_pct") or request.GET.get("deduction_pct"),
                             Decimal("0"))
    if deduction_pct is None or deduction_pct < 0 or deduction_pct > 100:
        deduction_pct = Decimal("0")
    receipts = list(booking.receipts.all())
    deduction, refund = calc.refund_on_cancel(booking, deduction_pct, receipts)
    if request.method == "POST" and request.POST.get("confirm") == "yes":
        try:
            services.cancel_booking(booking, reason=request.POST.get("reason") or "",
                                    deduction_pct=deduction_pct, on=_date(request.POST.get("on")),
                                    by=request.user)
        except SalesError as error:
            messages.error(request, str(error))
        else:
            messages.success(request, f"{booking.number} cancelled. {booking.unit.number} is for sale again. "
                                      f"Refund due Rs {booking.refund_amount}.")
            return redirect("sales_booking", booking_id=booking.pk)
    return render(request, "sales/booking_cancel.html", {
        "booking": booking, "collected": calc.collected(booking, receipts),
        "deduction_pct": deduction_pct, "deduction": deduction, "refund": refund,
        "reason": (request.POST.get("reason") or "").strip(), "today": timezone.localdate(),
        "refusal": (f"{booking.number} is registered and cannot be cancelled here."
                    if booking.status == Booking.Status.REGISTERED else
                    f"{booking.number} is already cancelled." if not booking.is_live else ""),
    })


@requires("sales.edit")
def booking_transfer(request, booking_id):
    """Move the sale to another customer, by phone — new or existing."""
    booking = get_object_or_404(Booking.objects.select_related("unit", "customer"), pk=booking_id)
    form = {"phone": "", "name": "", "email": "", "pan": "", "address": "", "note": ""}
    if request.method == "POST":
        form.update({key: (request.POST.get(key) or "").strip() for key in form})
        try:
            customer, _created = services.find_or_create_customer(
                form["phone"], form["name"], form["email"], form["pan"], form["address"])
            services.transfer_booking(booking, customer, note=form["note"], by=request.user)
        except SalesError as error:
            messages.error(request, str(error))
        else:
            messages.success(request, f"{booking.number} transferred to {customer.name}.")
            return redirect("sales_booking", booking_id=booking.pk)
    return render(request, "sales/booking_transfer.html", {"booking": booking, "form": form})


@requires("sales.edit")
def customer_form(request, customer_id):
    """Correct a customer's details. The phone is their identity and stays unique."""
    customer = get_object_or_404(Customer, pk=customer_id)
    if request.method == "POST":
        customer.name = (request.POST.get("name") or "").strip()[:160]
        customer.phone = (request.POST.get("phone") or "").strip()
        customer.email = (request.POST.get("email") or "").strip()
        customer.pan = (request.POST.get("pan") or "").strip().upper()
        customer.address = (request.POST.get("address") or "").strip()
        errors = []
        if not customer.name:
            errors.append("Type the name.")
        if not customer.phone.isdigit() or not customer.phone:
            errors.append("The phone is digits only, and it is required.")
        elif Customer.objects.filter(phone=customer.phone).exclude(pk=customer.pk).exists():
            errors.append(f"Another customer already has the phone {customer.phone}.")
        if customer.pan and not (len(customer.pan) == 10 and customer.pan[:5].isalpha()
                                 and customer.pan[5:9].isdigit() and customer.pan[9].isalpha()):
            errors.append("A PAN is 10 characters, e.g. ABCDE1234F.")
        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            customer.save()
            messages.success(request, f"{customer.name} saved.")
            nxt = (request.POST.get("next") or "").strip()
            if nxt.isdigit():
                return redirect("sales_booking", booking_id=int(nxt))
            return redirect("sales_bookings")
    return render(request, "sales/customer_form.html", {
        "customer": customer, "next": (request.GET.get("next") or request.POST.get("next") or ""),
    })


# ----------------------------------------------------------------- demands
@requires("sales.collect")
def demand_new(request, booking_id):
    """Raise a demand letter on a milestone that has none, or an ad-hoc one."""
    booking = get_object_or_404(Booking.objects.select_related("unit__project", "customer"), pk=booking_id)
    demanded = set(Demand.objects.filter(booking=booking, milestone__isnull=False)
                   .values_list("milestone_id", flat=True))
    milestones = [m for m in booking.milestones.order_by("sequence", "id") if m.id not in demanded]
    for milestone in milestones:
        milestone.amount = calc.milestone_amount(booking.agreement_value, milestone.percent)
    today = timezone.localdate()
    form = {"milestone": str(milestones[0].id) if milestones else "", "amount": "",
            "raised_on": today.isoformat(), "due_on": (today + timedelta(days=15)).isoformat(), "note": ""}
    if request.method == "POST":
        form.update({key: (request.POST.get(key) or "").strip() for key in form})
        milestone = None
        if form["milestone"].isdigit():
            milestone = PaymentMilestone.objects.filter(pk=int(form["milestone"]), booking=booking).first()
        try:
            demand = services.raise_demand(
                booking, milestone, due_on=_date(form["due_on"]), raised_on=_date(form["raised_on"]),
                amount=_decimal(form["amount"]) if milestone is None else None,
                note=form["note"], by=request.user)
        except SalesError as error:
            messages.error(request, str(error))
        else:
            messages.success(request, f"{demand.number} raised for Rs {calc.demand_total(demand)}.")
            return redirect("sales_booking", booking_id=booking.pk)
    return render(request, "sales/demand_new.html", {
        "booking": booking, "milestones": milestones, "form": form, "today": today,
        "gst_percent": booking.gst_percent,
    })


@requires("sales.view")
def demand_pdf(request, demand_id):
    """
    The demand letter as a PDF.

    ⚠ WEASYPRINT IS IMPORTED INSIDE THIS FUNCTION, exactly as `projects.views.po_pdf`
      does and for the same reason: CI does not install it, and a module-level
      import would fail every test at import time.
    """
    demand = get_object_or_404(
        Demand.objects.select_related("booking__unit__project", "booking__customer", "milestone"),
        pk=demand_id)
    booking = demand.booking
    figures = calc.bulk_demand_figures([demand])[demand.id]
    booking_figures = calc.bulk_booking_figures([booking])[booking.id]
    html = render_to_string("sales/demand_pdf.html", {
        "demand": demand, "booking": booking, "customer": booking.customer,
        "unit": booking.unit, "project": booking.unit.project,
        "figures": figures, "booking_figures": booking_figures,
        "company": CompanyProfile.get_solo(),
        "status_word": STATUS_WORDS[figures["status"]],
    }, request=request)

    from weasyprint import HTML          # see the note above — deliberately here

    pdf = HTML(string=html, base_url=request.build_absolute_uri("/")).write_pdf()
    customer = slugify(booking.customer.name).replace("-", "_") or "customer"
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{demand.number}_{customer}.pdf"'
    return response


@require_POST
@requires("sales.collect")
def demands_for_header(request):
    """The slab is cast: raise the letter on every booking that links this header."""
    projects = list(live_projects())
    project = _project_from(request, projects)
    raw = (request.POST.get("header") or "").strip()
    header = TaskHeader.objects.filter(pk=int(raw), project=project).first() if raw.isdigit() and project else None
    if header is None:
        messages.error(request, "Choose a project and a finished header task.")
        return redirect("sales_collections")
    try:
        raised = services.raise_demands_for_milestone(project, header, by=request.user)
    except SalesError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, f"{len(raised)} demand letter{'' if len(raised) == 1 else 's'} "
                                  f"raised for {header.name} on {project.code}."
                         + ("" if raised else " Every booking linked to it already had one, or none link it."))
    return redirect(f"{reverse('sales_collections')}?project={project.pk}")


# ---------------------------------------------------------------- receipts
@requires("sales.collect")
def receipt_new(request, booking_id):
    """Record money received, against a demand or on account."""
    booking = get_object_or_404(Booking.objects.select_related("unit__project", "customer"), pk=booking_id)
    demands = list(booking.demands.select_related("milestone").order_by("due_on", "id"))
    figures = calc.bulk_demand_figures(demands)
    open_demands = []
    for demand in demands:
        demand.figures = figures[demand.id]
        if demand.figures["status"] != "paid":
            open_demands.append(demand)
    today = timezone.localdate()
    form = {"demand": str(open_demands[0].id) if open_demands else "",
            "amount": f"{open_demands[0].figures['balance']:.2f}" if open_demands else "",
            "received_on": today.isoformat(), "mode": ReceiptMode.NEFT, "reference": "",
            "tds_amount": "0"}
    if request.method == "POST":
        form.update({key: (request.POST.get(key) or "").strip() for key in form})
        demand = None
        if form["demand"].isdigit():
            demand = Demand.objects.filter(pk=int(form["demand"]), booking=booking).first()
        if form["mode"] not in ReceiptMode.values:
            form["mode"] = ReceiptMode.OTHER
        try:
            amount = _decimal(form["amount"])
            tds = _decimal(form["tds_amount"], Decimal("0"))
            if amount is None or tds is None:
                raise SalesError("The amount and TDS must be numbers.")
            receipt = services.record_receipt(
                booking, amount=amount, received_on=_date(form["received_on"]), mode=form["mode"],
                reference=form["reference"], tds_amount=tds, demand=demand, by=request.user)
        except SalesError as error:
            messages.error(request, str(error))
        else:
            messages.success(request, f"{receipt.number}: Rs {calc.receipt_credit(receipt)} recorded.")
            return redirect("sales_booking", booking_id=booking.pk)
    return render(request, "sales/receipt_new.html", {
        "booking": booking, "open_demands": open_demands, "form": form, "today": today,
        "modes": ReceiptMode.choices, "suggested_tds": calc.suggested_tds(booking),
        "tds_applies": calc.suggested_tds(booking) > 0,
    })


def _receipt_selection(request):
    rows = CustomerReceipt.objects.select_related("booking__unit__project", "booking__customer", "demand")
    applied = {}
    raw = (request.GET.get("project") or "").strip()
    if raw.isdigit():
        rows = rows.filter(booking__unit__project_id=int(raw))
        applied["project"] = int(raw)
    since = _date(request.GET.get("from"))
    until = _date(request.GET.get("to"))
    if since:
        rows = rows.filter(received_on__gte=since)
        applied["from"] = since.isoformat()
    if until:
        rows = rows.filter(received_on__lte=until)
        applied["to"] = until.isoformat()
    mode = (request.GET.get("mode") or "").strip()
    if mode in ReceiptMode.values:
        rows = rows.filter(mode=mode)
        applied["mode"] = mode
    return rows.order_by("received_on", "id"), applied


@requires("sales.view")
def receipts(request):
    """The receipt register, by date range."""
    rows, applied = _receipt_selection(request)
    rows = list(rows[:1000])
    for row in rows:
        row.credit_amount = calc.receipt_credit(row)
    totals = {
        "amount": sum((r.amount for r in rows), calc.ZERO),
        "tds": sum((r.tds_amount for r in rows), calc.ZERO),
        "credit": sum((r.credit_amount for r in rows), calc.ZERO),
    }
    return render(request, "sales/receipts.html", {
        "rows": rows, "applied": applied, "totals": totals, "projects": list(live_projects()),
        "modes": ReceiptMode.choices,
    })


@requires("sales.view")
def receipts_excel(request):
    """The same register as a spreadsheet — one row per receipt, every money column summable."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    rows, _applied = _receipt_selection(request)
    book = Workbook()
    sheet = book.active
    sheet.title = "Customer receipts"
    headings = ["Receipt", "Received", "Project", "Unit", "Booking", "Customer", "Phone",
                "Demand", "Mode", "Reference", "Amount", "TDS", "Credited"]
    sheet.append(headings)
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F3864")
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    for receipt in rows:
        sheet.append([
            receipt.number, receipt.received_on, receipt.booking.unit.project.code,
            receipt.booking.unit.number, receipt.booking.number, receipt.booking.customer.name,
            receipt.booking.customer.phone, receipt.demand.number if receipt.demand_id else "",
            receipt.get_mode_display(), receipt.reference,
            float(receipt.amount), float(receipt.tds_amount), float(calc.receipt_credit(receipt)),
        ])
    widths = {"Receipt": 13, "Received": 12, "Project": 12, "Unit": 10, "Booking": 13,
              "Customer": 28, "Phone": 14, "Demand": 13, "Mode": 12, "Reference": 20,
              "Amount": 15, "TDS": 12, "Credited": 15}
    for index, heading in enumerate(headings, 1):
        sheet.column_dimensions[get_column_letter(index)].width = widths[heading]
    money_from = headings.index("Amount") + 1
    for row in sheet.iter_rows(min_row=2, min_col=money_from, max_col=len(headings)):
        for cell in row:
            cell.number_format = "#,##0.00"
    sheet.freeze_panes = "A2"
    return _xlsx(book, "customer_receipts")


def _xlsx(book, stem):
    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="{stem}_{timezone.localdate():%Y%m%d}.xlsx"'
    book.save(response)
    return response


# ------------------------------------------------------------- collections
def _collection_rows(request, today):
    """Every open demand across live projects, with ageing. Bulk figures, few queries."""
    projects = list(live_projects())
    demands = Demand.objects.filter(booking__unit__project__in=projects) \
        .exclude(booking__status=Booking.Status.CANCELLED) \
        .select_related("booking__unit__project", "booking__customer", "milestone")
    applied = {}
    raw = (request.GET.get("project") or "").strip()
    if raw.isdigit():
        demands = demands.filter(booking__unit__project_id=int(raw))
        applied["project"] = int(raw)
    demands = list(demands.order_by("due_on", "id"))
    figures = calc.bulk_demand_figures(demands)
    rows = []
    for demand in demands:
        figure = figures[demand.id]
        if figure["status"] == "paid":
            continue
        bucket = calc.ageing_bucket(demand.due_on, today)
        rows.append({"demand": demand, "figures": figure, "bucket": bucket,
                     "bucket_word": dict(calc.AGEING_BUCKETS)[bucket], "pill": _pill(bucket),
                     "status_word": STATUS_WORDS[figure["status"]], "status_pill": _pill(figure["status"]),
                     "days": calc.days_past(demand.due_on, today)})
    return rows, applied, projects


@requires("sales.view")
def collections(request):
    today = timezone.localdate()
    rows, applied, projects = _collection_rows(request, today)
    buckets = [{"key": key, "label": label,
                "amount": sum((r["figures"]["balance"] for r in rows if r["bucket"] == key), calc.ZERO),
                "count": sum(1 for r in rows if r["bucket"] == key)}
               for key, label in calc.AGEING_BUCKETS]
    totals = {"total": sum((r["figures"]["total"] for r in rows), calc.ZERO),
              "paid": sum((r["figures"]["paid"] for r in rows), calc.ZERO),
              "balance": sum((r["figures"]["balance"] for r in rows), calc.ZERO),
              "overdue": sum((r["figures"]["balance"] for r in rows if r["bucket"] != "not_due"), calc.ZERO)}
    project = None
    if applied.get("project"):
        project = next((p for p in projects if p.pk == applied["project"]), None)
    headers = list(TaskHeader.objects.filter(project=project).order_by("start", "id")) if project else []
    return render(request, "sales/collections.html", {
        "rows": rows, "applied": applied, "projects": projects, "buckets": buckets, "totals": totals,
        "today": today, "project": project, "headers": headers,
    })


@requires("sales.view")
def collections_excel(request):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    today = timezone.localdate()
    rows, _applied, _projects = _collection_rows(request, today)
    book = Workbook()
    sheet = book.active
    sheet.title = "Open demands"
    headings = ["Demand", "Raised", "Due", "Days", "Ageing", "Project", "Unit", "Booking",
                "Customer", "Phone", "Milestone", "Basic", "GST %", "GST", "Amount",
                "Paid", "Balance", "Status"]
    sheet.append(headings)
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F3864")
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    for row in rows:
        demand = row["demand"]
        sheet.append([
            demand.number, demand.raised_on, demand.due_on, row["days"], row["bucket_word"],
            demand.booking.unit.project.code, demand.booking.unit.number, demand.booking.number,
            demand.booking.customer.name, demand.booking.customer.phone,
            demand.milestone.name if demand.milestone_id else demand.note,
            float(demand.amount), float(demand.gst_percent), float(row["figures"]["gst"]),
            float(row["figures"]["total"]), float(row["figures"]["paid"]),
            float(row["figures"]["balance"]), row["status_word"],
        ])
    widths = {"Demand": 13, "Raised": 12, "Due": 12, "Days": 7, "Ageing": 12, "Project": 12,
              "Unit": 10, "Booking": 13, "Customer": 28, "Phone": 14, "Milestone": 20,
              "Basic": 15, "GST %": 8, "GST": 13, "Amount": 15, "Paid": 15, "Balance": 15,
              "Status": 11}
    for index, heading in enumerate(headings, 1):
        sheet.column_dimensions[get_column_letter(index)].width = widths[heading]
    money_from, money_to = headings.index("Basic") + 1, headings.index("Balance") + 1
    for row in sheet.iter_rows(min_row=2, min_col=money_from, max_col=money_to):
        for cell in row:
            cell.number_format = "#,##0.00"
    sheet.freeze_panes = "A2"
    return _xlsx(book, "collections")
