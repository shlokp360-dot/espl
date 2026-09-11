"""
The Drawings repository screens: the overview, the register, the revisions.

>>> ANCHOR: DRAWINGS-SCREENS <<<

WHO MAY DO WHAT — from accounts/perms.py, and nothing here widens it:

        view and download   Admin · Project manager · Purchase · Site engineer
        register, upload,   Admin · Project manager
          approve

⚠⚠ FILES ARE SERVED THROUGH `download` AND NEVER FROM A URL. There is no
    MEDIA_URL. A structural drawing readable by anybody holding a link is the
    one mistake this module must not make.

⚠ EVERY PER-PROJECT OBJECT IS FETCHED SCOPED TO THE PROJECT — a drawing id from
    one site's address must not open another site's drawing.

⚠ LIST SCREENS FETCH IN BULK. The newest revision for every drawing comes from
    one query (`status.latest_by_drawing`); nothing here asks per row.

⚠ WON AND COMPLETED ARE BOTH LIVE HERE. A finished building's drawings and its
    compliance file are exactly what the repository is for — `live_projects()`
    is the one place that says so, and the overview shows the two in separate
    sections so a live site is never mistaken for an old one.
"""
import os

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Max
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from accounts.perms import requires
from compliance.models import ComplianceDocument
from drawings import status as drawing_status
from drawings.models import Architect, Drawing, DrawingGroup, DrawingRevision
from projects.models import Project

#: ⚠ WHAT MAY BE UPLOADED. A whitelist: the formats a drawing arrives in and
#:   that somebody can still open in five years. DWG/DXF for the CAD file,
#:   PDF for the issued sheet, images for a photographed markup.
ALLOWED_SUFFIXES = {".pdf", ".dwg", ".dxf", ".jpg", ".jpeg", ".png", ".zip"}
MAX_BYTES = 50 * 1024 * 1024


def live_projects():
    """
    Won and Completed — a quoted job has no site to draw for, and a finished
    one keeps its file. The same pair as `compliance.views.live_projects`.
    """
    return Project.objects.filter(
        status__in=[Project.Status.WON, Project.Status.COMPLETED]).order_by("name")


def _project(project_id):
    return get_object_or_404(Project, pk=project_id)


def _drawing(project, drawing_id):
    """Scoped to the project, always."""
    return get_object_or_404(
        Drawing.objects.select_related("group", "architect", "project"),
        pk=drawing_id, project=project)


def _person(user):
    if user is None:
        return ""
    return user.get_full_name() or user.username


# ---------------------------------------------------------------- the overview
def _overview_rows(projects, drawings, latest, newest, compliance):
    """One row per project: the status counts, the newest revision date, the compliance count."""
    by_project = {project.id: [] for project in projects}
    for drawing in drawings:
        by_project[drawing.project_id].append(drawing)
    rows = []
    for project in projects:
        summary = drawing_status.summarise(
            drawing_status.rows_for(by_project[project.id], latest))
        rows.append({"project": project, "summary": summary,
                     "latest_on": newest.get(project.id),
                     "compliance": compliance.get(project.id, 0)})
    return rows


@requires("drawings.view")
def home(request):
    """
    Every live site and every completed project: drawings required, received,
    approved, the date the newest revision arrived, and how many compliance
    documents the project holds.

    ⚠ FOUR QUERIES FOR THE WHOLE SCREEN, however many projects — the drawings,
      their newest revisions, the newest revision date per project and the
      compliance count per project, each grouped in the database.
    """
    projects = list(live_projects())
    drawings = list(Drawing.objects.filter(project__in=projects, is_active=True))
    latest = drawing_status.latest_by_drawing(drawings)

    newest = dict(DrawingRevision.objects
                  .filter(drawing__project__in=projects, drawing__is_active=True)
                  .values_list("drawing__project_id")
                  .annotate(last=Max("received_on"))
                  .values_list("drawing__project_id", "last"))
    compliance = dict(ComplianceDocument.objects
                      .filter(project__in=projects)
                      .values_list("project_id")
                      .annotate(n=Count("id"))
                      .values_list("project_id", "n"))

    rows = _overview_rows(projects, drawings, latest, newest, compliance)
    live = [row for row in rows if row["project"].status == Project.Status.WON]
    completed = [row for row in rows if row["project"].status == Project.Status.COMPLETED]

    return render(request, "drawings/home.html", {
        "live": live,
        "completed": completed,
        "projects": projects,
        "required": sum(row["summary"]["required"] for row in rows),
        "received": sum(row["summary"]["received"] for row in rows),
        "approved": sum(row["summary"]["approved"] for row in rows),
        "compliance_total": sum(row["compliance"] for row in rows),
    })


# ---------------------------------------------------------------- the register
@requires("drawings.view")
def register(request, project_id=None):
    """One project's register, grouped by section, filtered by group and state."""
    projects = list(live_projects())
    project = (Project.objects.filter(pk=project_id).first() if project_id
               else (projects[0] if projects else None))
    if project is None:
        return render(request, "drawings/register.html", {"projects": projects, "project": None})

    group_code = (request.GET.get("group") or "").strip().upper()
    state = (request.GET.get("status") or "").strip().lower()
    if state not in drawing_status.LABELS:
        state = ""
    show_inactive = request.GET.get("inactive") == "yes"

    drawings = (Drawing.objects.filter(project=project)
                .select_related("group", "architect"))
    if not show_inactive:
        drawings = drawings.filter(is_active=True)
    if group_code:
        drawings = drawings.filter(group__code=group_code)
    drawings = list(drawings)

    rows = drawing_status.rows_for(drawings)
    if state:
        rows = [row for row in rows if row["state"] == state]

    groups = []
    for row in rows:
        if not groups or groups[-1]["group"].id != row["drawing"].group_id:
            groups.append({"group": row["drawing"].group, "rows": []})
        groups[-1]["rows"].append(row)

    return render(request, "drawings/register.html", {
        "projects": projects,
        "project": project,
        "groups": groups,
        "summary": drawing_status.summarise(rows),
        "all_groups": DrawingGroup.objects.filter(is_active=True),
        "states": drawing_status.CHOICES,
        "group_code": group_code,
        "state": state,
        "show_inactive": show_inactive,
    })


def _drawing_form_context(project, drawing=None):
    return {
        "project": project,
        "drawing": drawing,
        "groups": DrawingGroup.objects.filter(is_active=True),
        "architects": Architect.objects.filter(is_active=True),
    }


def _read_drawing_form(request, project, errors, drawing=None):
    """Validate the typed fields. Returns the cleaned values; errors go in the list."""
    number = (request.POST.get("number") or "").strip()
    title = (request.POST.get("title") or "").strip()
    group_id = (request.POST.get("group") or "").strip()
    architect_id = (request.POST.get("architect") or "").strip()

    group = DrawingGroup.objects.filter(pk=group_id, is_active=True).first() \
        if group_id.isdigit() else None
    architect = Architect.objects.filter(pk=architect_id).first() \
        if architect_id.isdigit() else None

    if not number:
        errors.append("Type the architect's drawing number — it is on the title block.")
    elif Drawing.objects.filter(project=project, number__iexact=number) \
                        .exclude(pk=drawing.pk if drawing else 0).exists():
        errors.append(f"{project.code} already has a drawing numbered {number}.")
    if not title:
        errors.append("Give the drawing its title.")
    if group is None:
        errors.append("Choose which section of the register it belongs to.")
    if architect_id and architect is None:
        errors.append("That architect is not on the list.")

    return {
        "number": number, "title": title, "group": group, "architect": architect,
        "required_by": parse_date((request.POST.get("required_by") or "").strip()),
    }


@requires("drawings.edit")
def drawing_new(request, project_id):
    """Register one drawing the project needs."""
    project = _project(project_id)
    if request.method == "POST":
        errors = []
        values = _read_drawing_form(request, project, errors)
        if errors:
            for problem in errors:
                messages.error(request, problem)
        else:
            drawing = Drawing.objects.create(project=project, created_by=request.user, **values)
            messages.success(request, f"{drawing.number} registered on {project.code}. "
                                      f"It is Required until a revision arrives.")
            return redirect("drawings_detail", project_id=project.pk, drawing_id=drawing.pk)
    return render(request, "drawings/drawing_form.html", _drawing_form_context(project))


@requires("drawings.edit")
def drawing_edit(request, project_id, drawing_id):
    """Correct the number, title, section or architect. Active is the way out — never delete."""
    project = _project(project_id)
    drawing = _drawing(project, drawing_id)
    if request.method == "POST":
        errors = []
        values = _read_drawing_form(request, project, errors, drawing)
        if errors:
            for problem in errors:
                messages.error(request, problem)
        else:
            for field, value in values.items():
                setattr(drawing, field, value)
            drawing.is_active = request.POST.get("is_active") == "on"
            drawing.save()
            messages.success(request, f"{drawing.number} saved."
                             + ("" if drawing.is_active else " It is deactivated — its revisions stay on file."))
            return redirect("drawings_detail", project_id=project.pk, drawing_id=drawing.pk)
    return render(request, "drawings/drawing_form.html", _drawing_form_context(project, drawing))


@requires("drawings.edit")
def bulk(request, project_id):
    """
    Register several drawings at once from a pasted list of "number | title".

    ⚠ ALL OR NOTHING. A list with one bad line is refused whole and the lines
      are reported by number, so the paste can be fixed and sent again rather
      than half-registered.
    """
    project = _project(project_id)
    text = ""
    if request.method == "POST":
        text = request.POST.get("lines") or ""
        group_id = (request.POST.get("group") or "").strip()
        architect_id = (request.POST.get("architect") or "").strip()
        group = DrawingGroup.objects.filter(pk=group_id, is_active=True).first() \
            if group_id.isdigit() else None
        architect = Architect.objects.filter(pk=architect_id).first() \
            if architect_id.isdigit() else None

        errors, parsed, seen = [], [], set()
        if group is None:
            errors.append("Choose which section of the register these belong to.")
        for line_no, raw in enumerate(text.splitlines(), 1):
            if not raw.strip():
                continue
            number, _sep, title = raw.partition("|")
            number, title = number.strip(), title.strip()
            if not number or not title:
                errors.append(f"Line {line_no}: write it as number | title.")
                continue
            if number.lower() in seen:
                errors.append(f"Line {line_no}: {number} appears twice in the list.")
                continue
            seen.add(number.lower())
            parsed.append((number, title))

        taken = set(Drawing.objects.filter(project=project, number__in=[n for n, _t in parsed])
                    .values_list("number", flat=True))
        taken = {number.lower() for number in taken}
        for number, _title in parsed:
            if number.lower() in taken:
                errors.append(f"{number} is already on {project.code}'s register.")
        if not parsed and not errors:
            errors.append("Paste at least one line — number | title.")

        if errors:
            for problem in errors:
                messages.error(request, problem)
        else:
            with transaction.atomic():
                Drawing.objects.bulk_create([
                    Drawing(project=project, group=group, architect=architect,
                            number=number, title=title, created_by=request.user)
                    for number, title in parsed])
            messages.success(request, f"{len(parsed)} drawing{'' if len(parsed) == 1 else 's'} "
                                      f"registered under {group.code} on {project.code}.")
            return redirect("drawings_register", project_id=project.pk)

    return render(request, "drawings/bulk.html", {
        **_drawing_form_context(project), "lines": text,
    })


# ------------------------------------------------------------------ one drawing
@requires("drawings.view")
def detail(request, project_id, drawing_id):
    """The revision history and the upload form."""
    project = _project(project_id)
    drawing = _drawing(project, drawing_id)
    revisions = list(drawing.revisions.select_related("approved_by", "uploaded_by"))
    latest = revisions[0] if revisions else None

    state = drawing_status.status_of(latest)
    return render(request, "drawings/detail.html", {
        "project": project,
        "drawing": drawing,
        "revisions": revisions,
        "latest": latest,
        "state": state,
        "state_label": drawing_status.LABELS[state],
        "pill": drawing_status.PILLS[state],
        "today": timezone.localdate(),
        "suggested_label": f"R{len(revisions)}",
    })


@require_POST
@requires("drawings.edit")
def upload(request, project_id, drawing_id):
    """
    Add a revision. Never replaces one.

    ⚠ THE EARLIER REVISION STAYS AND STAYS DOWNLOADABLE — R0 was the paper on
      site before R1 arrived, and that is what a dispute will ask about.
    """
    project = _project(project_id)
    drawing = _drawing(project, drawing_id)
    upload = request.FILES.get("file")
    label = (request.POST.get("label") or "").strip().upper()

    errors = []
    if upload is None:
        errors.append("Choose the file to upload.")
    else:
        suffix = os.path.splitext(upload.name)[1].lower()
        if suffix not in ALLOWED_SUFFIXES:
            errors.append(
                f"{upload.name} is a {suffix or 'file with no extension'}. "
                "Upload a PDF, DWG, DXF, JPG, PNG or ZIP.")
        if upload.size > MAX_BYTES:
            errors.append(f"{upload.name} is {upload.size // (1024 * 1024)} MB. "
                          f"The limit is {MAX_BYTES // (1024 * 1024)} MB.")
    if not label:
        errors.append("Type the revision label — R0, R1, as the architect marks it.")
    elif DrawingRevision.objects.filter(drawing=drawing, label__iexact=label).exists():
        # >>> ANCHOR: DRAWINGS-LABEL-UNIQUE <<<
        # ⚠ REFUSED, NOT REPLACED. Two files both called R1 on one drawing is
        #   exactly the confusion the register exists to prevent.
        errors.append(f"{drawing.number} already has a revision {label}. "
                      "A revision is never replaced — give the new file its own label.")

    received_on = parse_date((request.POST.get("received_on") or "").strip()) \
        or timezone.localdate()

    if errors:
        for problem in errors:
            messages.error(request, problem)
        return redirect("drawings_detail", project_id=project.pk, drawing_id=drawing.pk)

    was_approved = drawing.status == drawing_status.APPROVED
    DrawingRevision.objects.create(
        drawing=drawing, label=label, file=upload, original_name=upload.name,
        size_bytes=upload.size, received_on=received_on,
        note=(request.POST.get("note") or "").strip(), uploaded_by=request.user)
    messages.success(
        request,
        f"{drawing.number} {label} received."
        + (" The approved revision is superseded — this one is Received until approved."
           if was_approved else ""))
    return redirect("drawings_detail", project_id=project.pk, drawing_id=drawing.pk)


@require_POST
@requires("drawings.edit")
def approve(request, project_id, revision_id):
    """Approve one revision. Records who and when; refuses a second time."""
    project = _project(project_id)
    revision = get_object_or_404(
        DrawingRevision.objects.select_related("drawing", "approved_by"),
        pk=revision_id, drawing__project=project)
    try:
        revision.approve(request.user)
    except ValueError as refused:
        messages.error(request, str(refused))
    else:
        messages.success(request, f"{revision} approved by {_person(request.user)}.")
    return redirect("drawings_detail", project_id=project.pk, drawing_id=revision.drawing_id)


# ------------------------------------------------------------------- download
@requires("drawings.view")
def download(request, revision_id):
    """
    Hand over the file, to somebody the matrix allows.

    ⚠⚠ THE ONLY ROUTE TO A DRAWING FILE. No MEDIA_URL, nothing under the static
       tree, so a link cannot be passed to somebody who should not have it.

    ⚠ A MISSING FILE IS A 404 AND NOT A CRASH. A restore that brought back the
      rows and not the media folder must show what is missing, not take every
      screen down.
    """
    revision = get_object_or_404(
        DrawingRevision.objects.select_related("drawing"), pk=revision_id)
    try:
        handle = revision.file.open("rb")
    except (FileNotFoundError, ValueError):
        raise Http404("The file for this revision is not on the server.")
    return FileResponse(handle, as_attachment=True,
                        filename=revision.original_name or os.path.basename(revision.file.name))


# --------------------------------------------------------------------- masters
@requires("drawings.view")
def architects(request):
    """Who draws, with how many drawings each holds."""
    rows = list(Architect.objects.annotate(drawing_count=Count("drawings")))
    return render(request, "drawings/architects.html", {"rows": rows})


def _read_architect(request, errors, architect=None):
    name = (request.POST.get("name") or "").strip()
    phone = "".join(ch for ch in (request.POST.get("phone") or "") if ch.isdigit())
    if not name:
        errors.append("An architect needs a name.")
    elif Architect.objects.filter(name__iexact=name).exclude(pk=architect.pk if architect else 0).exists():
        errors.append(f"{name} is already on the list.")
    return {
        "name": name, "phone": phone,
        "firm": (request.POST.get("firm") or "").strip(),
        "email": (request.POST.get("email") or "").strip(),
    }


@requires("drawings.edit")
def architect_new(request):
    if request.method == "POST":
        errors = []
        values = _read_architect(request, errors)
        if errors:
            for problem in errors:
                messages.error(request, problem)
        else:
            architect = Architect.objects.create(**values)
            messages.success(request, f"{architect.name} added.")
            return redirect("drawings_architects")
    return render(request, "drawings/architect_form.html", {"architect": None})


@requires("drawings.edit")
def architect_edit(request, architect_id):
    architect = get_object_or_404(Architect, pk=architect_id)
    if request.method == "POST":
        errors = []
        values = _read_architect(request, errors, architect)
        if errors:
            for problem in errors:
                messages.error(request, problem)
        else:
            for field, value in values.items():
                setattr(architect, field, value)
            architect.is_active = request.POST.get("is_active") == "on"
            architect.save()
            messages.success(request, f"{architect.name} saved.")
            return redirect("drawings_architects")
    return render(request, "drawings/architect_form.html", {"architect": architect})


@requires("drawings.view")
def groups(request):
    """The register's sections, edited in place. Active is the way out — never delete."""
    rows = list(DrawingGroup.objects.annotate(drawing_count=Count("drawings")))
    return render(request, "drawings/groups.html", {"rows": rows})


@require_POST
@requires("drawings.edit")
def groups_save(request):
    """
    One form, every row, plus the blank one at the bottom.

    >>> ANCHOR: MASTER-TABS <<<
    ⚠ A ROW WITHOUT ITS `row-<id>` MARKER WAS NOT ON THE FORM, and this save has
      nothing to say about it — an unticked checkbox and a row never shown
      arrive identically otherwise. Same guard as projects/master_tabs.py.
    """
    errors, changed = [], 0
    for row in DrawingGroup.objects.all():
        if f"row-{row.id}" not in request.POST:
            continue
        code = (request.POST.get(f"code-{row.id}") or "").strip().upper()
        name = (request.POST.get(f"name-{row.id}") or "").strip()
        order = (request.POST.get(f"sort_order-{row.id}") or "").strip()
        active = request.POST.get(f"is_active-{row.id}") == "on"
        moved = []
        if code and code != row.code:
            row.code, moved = code, moved + ["code"]
        if name and name != row.name:
            row.name, moved = name, moved + ["name"]
        if order.isdigit() and int(order) != row.sort_order:
            row.sort_order, moved = int(order), moved + ["sort_order"]
        if active != row.is_active:
            row.is_active, moved = active, moved + ["is_active"]
        if not moved:
            continue
        try:
            row.full_clean()
        except ValidationError as refused:
            for field, problems in refused.message_dict.items():
                errors.append(f"{row.code}: {' '.join(problems)}")
            continue
        row.save(update_fields=moved)
        changed += 1

    new_code = (request.POST.get("new-code") or "").strip().upper()
    if new_code:
        order = (request.POST.get("new-sort_order") or "").strip()
        fresh = DrawingGroup(code=new_code, name=(request.POST.get("new-name") or "").strip(),
                             sort_order=int(order) if order.isdigit() else
                             (DrawingGroup.objects.count() + 1) * 10)
        try:
            fresh.full_clean()
            fresh.save()
            messages.success(request, f"{fresh} added.")
        except ValidationError as refused:
            for field, problems in refused.message_dict.items():
                errors.append(f"New row — {field}: {' '.join(problems)}")

    if changed:
        messages.success(request, f"{changed} row{'' if changed == 1 else 's'} saved.")
    elif not errors and not new_code:
        messages.info(request, "Nothing had changed, so nothing was saved.")
    for problem in errors:
        messages.error(request, problem)
    return redirect(reverse("drawings_groups"))
