"""
The compliance screens: what every site holds, and what it is missing.

>>> ANCHOR: COMPLIANCE-SCREENS <<<

⚠ WHO MAY DO WHAT, AND IT SUPERSEDES THE ORIGINAL MATRIX ROW.
    Saahil, after the design was drawn: *"give compliance access to project
    manager and site manager as well as the workers or labours can ask for
    proof."* A site engineer standing in front of an inspector needs the labour
    licence on their phone, and that is a READ.

        view and download   Admin · Compliance · Project manager ·
                            Site engineer · Accountant
        upload and replace  Admin · Compliance

⚠⚠ DOCUMENTS ARE SERVED THROUGH A PERMISSION-CHECKED VIEW AND NEVER FROM A URL.
    There is no MEDIA_URL and nothing under the static tree. A signed municipal
    approval readable by anybody holding the link would be the single worst
    mistake this module could make.

⚠ NOTHING IS OVERWRITTEN. Uploading again adds a version and keeps the old one
    downloadable — *"the superseded one is often the one an inspector asks
    about."*
"""
import os

from django.contrib import messages
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from accounts.perms import requires
from compliance import status as compliance_status
from compliance.models import (
    ComplianceDocument, ComplianceItem, ComplianceTitle, ComplianceType, Kind,
    ProjectCompliance, ProjectComplianceItem, applies_to, removed_item_ids,
)
from projects.models import Project

#: ⚠ WHAT MAY BE UPLOADED. A whitelist rather than a blacklist, because the
#:   interesting question is not "is this dangerous" but "is this a document
#:   somebody can open in five years".
ALLOWED_SUFFIXES = {".pdf", ".jpg", ".jpeg", ".png"}
MAX_BYTES = 10 * 1024 * 1024


def live_projects():
    """Compliance starts at Won — a quoted job has no site to comply about."""
    return Project.objects.filter(
        status__in=[Project.Status.WON, Project.Status.COMPLETED]).order_by("name")


def _items_for(type, project=None, removed=None):
    """
    ⚠ EVERY GLOBAL ITEM, PLUS THE ONES BELONGING TO THIS SITE. `project=None` on
      an item means "all projects", which is the normal case; a value means a
      condition attached to one plot and it must not appear anywhere else.

    >>> ANCHOR: COMPLIANCE-PRUNING <<<
    ⚠⚠ THE PRUNING IS APPLIED HERE AND NOWHERE ELSE, AND THAT IS DELIBERATE.
       Every screen's item list funnels through this one function — the project
       screen, the Overview and the Expiry timeline. Filtering here means a
       removed line disappears from the rows, the "needs attention" counts and
       the timeline in the same instant. Doing it on the screen instead would
       leave the Overview still counting a line the project no longer shows,
       which is the same class of fault as a chart disagreeing with its own
       numbers: everything renders, and one of them is lying.

    ⚠ `removed` IS THE BULK HAND-DOWN. The Overview walks every Won project
      against every regime, so the caller fetches the removals once per project
      and passes them in — see `removed_item_ids`. Left out, this fetches its
      own, which is right for a single call.
    """
    rows = (ComplianceItem.objects
            .filter(is_active=True, title__is_active=True, title__type=type)
            .select_related("title", "project"))
    rows = rows.filter(Q(project__isnull=True) | Q(project=project)) if project \
        else rows.filter(project__isnull=True)
    if project:
        removed = removed_item_ids(project) if removed is None else removed
        if removed:
            rows = rows.exclude(id__in=removed)
    return rows.order_by("title__sort_order", "title__name", "sort_order", "name")


def _documents_for(project, type):
    """Every document on one project under one regime, newest first, in one query."""
    return list(ComplianceDocument.objects
                .filter(project=project, item__title__type=type)
                .select_related("item", "uploaded_by")
                .order_by("-uploaded_at", "-id"))


def _types_for(project):
    """The regimes that apply to this project, each with its rows and summary."""
    # ⚠ ONCE PER PROJECT, NOT ONCE PER REGIME — ANCHOR: COMPLIANCE-PRUNING. The
    #   Overview loops this over every Won project, so a lookup inside the regime
    #   loop would multiply by the number of types.
    removed = removed_item_ids(project)
    out = []
    for type in ComplianceType.objects.filter(is_active=True):
        if not applies_to(project, type):
            continue
        rows = compliance_status.rows_for(project,
                                          list(_items_for(type, project, removed=removed)),
                                          _documents_for(project, type))
        out.append({"type": type, "rows": rows, "summary": compliance_status.summarise(rows)})
    return out


# ---------------------------------------------------------------- the overview
@requires("compliance.view")
def overview(request):
    """
    Every Won project against every regime — where the gaps are.

    ⚠ THE NUMBER THAT LEADS IS "NEEDS ATTENTION", NOT "PERCENT COMPLETE". A
      project at 94% with an expired fire NOC is not 94% fine.
    """
    rows = []
    for project in live_projects():
        regimes = _types_for(project)
        rows.append({
            "project": project,
            "regimes": regimes,
            "attention": sum(regime["summary"]["attention"] for regime in regimes),
            "held": sum(regime["summary"]["held"] for regime in regimes),
            "total": sum(regime["summary"]["total"] for regime in regimes),
        })
    for row in rows:
        row["percent"] = int(round(row["held"] * 100 / row["total"])) if row["total"] else 0

    return render(request, "compliance/overview.html", {
        "rows": sorted(rows, key=lambda row: -row["attention"]),
        "attention": sum(row["attention"] for row in rows),
        "types": ComplianceType.objects.filter(is_active=True),
    })


# ------------------------------------------------------------- one project
@requires("compliance.view")
def project_screen(request, project_id=None):
    """One site's whole file: every title, every item, and the paper behind it."""
    projects = list(live_projects())
    project = (Project.objects.filter(pk=project_id).first() if project_id
               else (projects[0] if projects else None))
    if project is None:
        return render(request, "compliance/project.html", {"projects": projects, "project": None})

    regimes = _types_for(project)

    # ⚠ THE OPTIONAL REGIMES ARE OFFERED EVEN WHEN TURNED OFF, so somebody can
    #   turn RERA on later without hunting for where that lives.
    optional = []
    for type in ComplianceType.objects.filter(is_active=True, applies_to_every_project=False):
        row = ProjectCompliance.objects.filter(project=project, type=type).first()
        optional.append({"type": type, "applicable": bool(row and row.applicable),
                         "decided": row is not None})

    # >>> ANCHOR: COMPLIANCE-PRUNING <<<
    # What this project has removed, so it can be put back. Fetched with the item
    # and its title, because the picker prints both.
    put_back = list(ProjectComplianceItem.objects
                    .filter(project=project)
                    .select_related("item", "item__title", "item__title__type", "removed_by"))

    return render(request, "compliance/project.html", {
        "projects": projects,
        "project": project,
        "regimes": regimes,
        "optional": optional,
        "put_back": put_back,
        "today": timezone.localdate(),
    })


# --------------------------------------------------- pruning a project's lines
#
# >>> ANCHOR: COMPLIANCE-PRUNING <<<
# ⚠ `compliance.master`, NOT `compliance.upload`. Pruning changes what a project
#   is JUDGED AGAINST — it moves the denominator on the Overview — so it belongs
#   with the people who own the checklist rather than everyone who can file a
#   certificate. Claude's assumption in the review, not overruled. One line in
#   the matrix to widen if that turns out wrong in use.


@require_POST
@requires("compliance.master")
def remove_item(request, project_id, item_id):
    """
    Take one checklist line off one project.

    ⚠⚠ REFUSED WHILE THE LINE HOLDS DOCUMENTS, and the message says how many.
       Removal is for lines that were never applicable to this site, which is
       Saahil's actual case — a lake NOC on a plot with no lake. A line somebody
       has already filed paper against is a different situation entirely, and
       hiding it would orphan the evidence trail this module exists to keep.

    ⚠ THE MASTER IS NOT TOUCHED, and neither is any other project. That is the
      whole point: deactivating in the master was already possible and is what
      removed the line from all fifteen sites at once.
    """
    project = get_object_or_404(Project, pk=project_id)
    item = get_object_or_404(ComplianceItem, pk=item_id)

    held = ComplianceDocument.objects.filter(project=project, item=item).count()
    if held:
        messages.error(
            request,
            f"{item.name} holds {held} document{'' if held == 1 else 's'} on {project.code}, "
            f"so it cannot be removed. Removing it would hide filed paper. If the line is "
            f"genuinely not applicable here, the documents belong somewhere else first.")
        return redirect("compliance_project", project_id=project.pk)

    _row, created = ProjectComplianceItem.objects.get_or_create(
        project=project, item=item,
        defaults={"removed_by": request.user,
                  "reason": (request.POST.get("reason") or "").strip()[:200]})
    if created:
        messages.success(
            request,
            f"{item.name} removed from {project.code}. It is untouched on every other project, "
            f"and can be put back at any time.")
    return redirect("compliance_project", project_id=project.pk)


@require_POST
@requires("compliance.master")
def restore_item(request, project_id, item_id):
    """Put a removed line back on this project. Deleting the row IS the restore."""
    project = get_object_or_404(Project, pk=project_id)
    item = get_object_or_404(ComplianceItem, pk=item_id)

    deleted, _ = ProjectComplianceItem.objects.filter(project=project, item=item).delete()
    if deleted:
        messages.success(request, f"{item.name} is back on {project.code}.")
    return redirect("compliance_project", project_id=project.pk)


@require_POST
@requires("compliance.upload")
def set_applicability(request, project_id):
    """Tick or untick an optional regime for one project."""
    project = get_object_or_404(Project, pk=project_id)
    type = get_object_or_404(ComplianceType, pk=request.POST.get("type") or 0)
    applicable = request.POST.get("applicable") == "yes"

    ProjectCompliance.objects.update_or_create(
        project=project, type=type,
        defaults={"applicable": applicable, "decided_by": request.user})
    messages.success(
        request,
        f"{type.name} {'applies to' if applicable else 'does not apply to'} {project.code}.")
    return redirect("compliance_project", project_id=project.pk)


# ------------------------------------------------------------------- upload
@require_POST
@requires("compliance.upload")
def upload(request, project_id, item_id):
    """
    Add a document. Never replaces one.

    ⚠ THE PREVIOUS VERSION IS KEPT AND STAYS DOWNLOADABLE. This is an evidence
      trail somebody may be asked to produce years after the fact.
    """
    project = get_object_or_404(Project, pk=project_id)
    item = get_object_or_404(ComplianceItem.objects.select_related("title__type"), pk=item_id)
    upload = request.FILES.get("file")

    errors = []
    if upload is None:
        errors.append("Choose a file to upload.")
    else:
        suffix = os.path.splitext(upload.name)[1].lower()
        if suffix not in ALLOWED_SUFFIXES:
            errors.append(
                f"{upload.name} is a {suffix or 'file with no extension'}. "
                "Upload a PDF, a JPG or a PNG — something anybody can open in five years.")
        if upload.size > MAX_BYTES:
            errors.append(f"{upload.name} is {upload.size // (1024 * 1024)} MB. "
                          f"The limit is {MAX_BYTES // (1024 * 1024)} MB — scan it smaller.")

    expires_on = parse_date((request.POST.get("expires_on") or "").strip())
    if item.kind == "valid" and expires_on is None:
        # ⚠ REFUSED RATHER THAN SAVED BLANK. An expiry nobody typed is a document
        #   that will never appear on the timeline, and the real failure this
        #   module exists to prevent is one that quietly lapsed.
        errors.append(f"{item.name} has a validity. Type the date it expires — "
                      "it is on the document, and nothing here reads it for you.")

    if errors:
        for message in errors:
            messages.error(request, message)
        return redirect("compliance_project", project_id=project.pk)

    document = ComplianceDocument.objects.create(
        project=project, item=item, file=upload, original_name=upload.name,
        size_bytes=upload.size,
        reference=(request.POST.get("reference") or "").strip(),
        issued_on=parse_date((request.POST.get("issued_on") or "").strip()),
        expires_on=expires_on,
        note=(request.POST.get("note") or "").strip(),
        uploaded_by=request.user)

    held = ComplianceDocument.objects.filter(project=project, item=item).count()
    messages.success(
        request,
        f"{item.name} uploaded for {project.code}."
        + (f" The previous {held - 1} version{'s' if held > 2 else ''} "
           "kept and still downloadable." if held > 1 else ""))
    return redirect("compliance_project", project_id=project.pk)


# ----------------------------------------------------------------- download
@requires("compliance.view")
def download(request, document_id):
    """
    Hand over the file, to somebody the matrix allows.

    ⚠⚠ THIS VIEW IS THE ONLY ROUTE TO A COMPLIANCE DOCUMENT. There is no
      MEDIA_URL and nothing is served from the static tree, so a link cannot be
      passed to somebody who should not have it.

    ⚠ A MISSING FILE IS A 404 AND NOT A CRASH. Files live outside the database;
      a restore that brought back the rows and not the media folder would
      otherwise take every screen down rather than showing what is missing —
      which is exactly the scenario `OPEN-BEFORE-GO-LIVE.md` warns about.
    """
    document = get_object_or_404(
        ComplianceDocument.objects.select_related("project", "item"), pk=document_id)
    try:
        handle = document.file.open("rb")
    except (FileNotFoundError, ValueError):
        raise Http404("The file for this document is not on the server.")

    return FileResponse(handle, as_attachment=True,
                        filename=document.original_name or os.path.basename(document.file.name))


# ------------------------------------------------------- correcting a typing
@require_POST
@requires("compliance.upload")
def correct(request, document_id):
    """
    Fix a reference or a date that was typed wrongly. THE FILE IS NOT TOUCHED.

    ⚠ THIS IS THE ANSWER TO "HOW DO I CHANGE AN APPROVAL". Two different things
      get confused under that question and they have different answers:

        the PAPER is wrong or superseded  →  Replace. A new version, and the old
                                             one stays downloadable.
        the TYPING is wrong              →  this. The document is right; the
                                             expiry or reference beside it is not.

      Re-uploading the same paper to fix a typo would leave two identical
      documents on file and make the version history a lie.
    """
    document = get_object_or_404(
        ComplianceDocument.objects.select_related("project", "item"), pk=document_id)

    was = (document.reference, document.expires_on)
    document.reference = (request.POST.get("reference") or "").strip()
    document.issued_on = parse_date((request.POST.get("issued_on") or "").strip())
    expires_on = parse_date((request.POST.get("expires_on") or "").strip())

    if document.item.kind == Kind.VALID and expires_on is None:
        messages.error(request, f"{document.item.name} has a validity — it needs an expiry date.")
        return redirect("compliance_project", project_id=document.project_id)

    document.expires_on = expires_on
    document.note = (request.POST.get("note") or "").strip()
    document.corrected_at = timezone.now()
    document.corrected_by = request.user
    document.save(update_fields=["reference", "issued_on", "expires_on", "note",
                                 "corrected_at", "corrected_by"])

    changed = []
    if was[0] != document.reference:
        changed.append(f"reference {was[0] or '—'} → {document.reference or '—'}")
    if was[1] != document.expires_on:
        changed.append(f"expiry {was[1] or '—'} → {document.expires_on or '—'}")
    messages.success(
        request,
        f"{document.item.name} corrected" + (f" — {', '.join(changed)}." if changed else "."))
    return redirect("compliance_project", project_id=document.project_id)


# ------------------------------------------------------------ the timeline
@requires("compliance.view")
def timeline(request):
    """
    Everything with a validity, across every project, in date order.

    ⚠ EXPIRED FIRST AND NEVER DROPPED. A list that only looked forward would hide
      the exact failure this module exists to prevent — *"the real failure is not
      a missing document, it is one that quietly lapsed"*.

    ⚠ ONLY THE CURRENT VERSION OF EACH LINE COUNTS. An old certificate that
      expired last year is not a problem if a new one replaced it, and listing it
      would bury the ones that matter.
    """
    today = timezone.localdate()
    rows = []
    for project in live_projects():
        # ⚠ ANCHOR: COMPLIANCE-PRUNING — once per project, outside the regime loop.
        removed = removed_item_ids(project)
        for type in ComplianceType.objects.filter(is_active=True):
            if not applies_to(project, type):
                continue
            for row in compliance_status.rows_for(
                    project, list(_items_for(type, project, removed=removed)),
                    _documents_for(project, type)):
                if row["latest"] and row["latest"].expires_on:
                    rows.append({**row, "project": project, "type": type,
                                 "expires_on": row["latest"].expires_on})

    rows.sort(key=lambda row: row["expires_on"])
    return render(request, "compliance/timeline.html", {
        "rows": rows,
        "today": today,
        "expired": [row for row in rows if row["state"] == compliance_status.EXPIRED],
        "expiring": [row for row in rows if row["state"] == compliance_status.EXPIRING],
        "window": compliance_status.EXPIRING_WITHIN_DAYS,
    })


# ------------------------------------------------------- the checklist master
#
# >>> ANCHOR: COMPLIANCE-MASTER <<<
#
# ⚠ THE TEMPLATE, NOT A PROJECT. Saahil: *"do this similar to task master, not
#     the same, similar."* Titles and line items are written ONCE here and appear
#     on every project of that type — which is the whole reason a master exists.
#     Documents are never uploaded here.
#
# ⚠ THE DIALOG STATES THE BLAST RADIUS BEFORE SAVING, and that is the deliberate
#     difference from the task master. A task belongs to one site; a checklist
#     item lands on all of them at once, and *"this will appear as Missing on 2
#     Won projects"* is the sentence that stops somebody adding a line casually.

@requires("compliance.master")
def master(request):
    """The checklist behind every project — types, titles and line items."""
    code = (request.GET.get("type") or "").strip()
    types = list(ComplianceType.objects.filter(is_active=True))
    type = next((row for row in types if row.code == code), types[0] if types else None)

    titles = []
    if type:
        for title in type.titles.filter(is_active=True):
            titles.append({
                "title": title,
                "items": list(title.items.filter(is_active=True).select_related("project")),
            })

    return render(request, "compliance/master.html", {
        "types": types,
        "type": type,
        "titles": titles,
        "kinds": Kind.choices,
        "projects": live_projects(),
        # How many projects a global item would land on — the blast radius.
        "reach": sum(1 for project in live_projects() if type and applies_to(project, type)),
    })


@require_POST
@requires("compliance.master")
def master_title(request):
    """Add or rename a title."""
    type = get_object_or_404(ComplianceType, pk=request.POST.get("type") or 0)
    name = (request.POST.get("name") or "").strip()
    title_id = request.POST.get("title")

    if not name:
        messages.error(request, "A title needs a name — it is the sub-header documents sit under.")
    elif ComplianceTitle.objects.filter(type=type, name__iexact=name) \
                                .exclude(pk=title_id or 0).exists():
        messages.error(request, f"{type.code} already has a title called {name}.")
    elif title_id:
        title = get_object_or_404(ComplianceTitle, pk=title_id)
        title.name = name
        title.save(update_fields=["name"])
        messages.success(request, f"Renamed to {name}.")
    else:
        ComplianceTitle.objects.create(
            type=type, name=name,
            sort_order=(type.titles.count() + 1) * 10)
        messages.success(request, f"{name} added to {type.code}.")
    return redirect(f"{reverse('compliance_master')}?type={type.code}")


@require_POST
@requires("compliance.master")
def master_item(request):
    """Add or edit a line item — the thing a document is held against."""
    title = get_object_or_404(ComplianceTitle.objects.select_related("type"),
                              pk=request.POST.get("title") or 0)
    item_id = request.POST.get("item")
    item = ComplianceItem.objects.filter(pk=item_id).first() if item_id else None

    name = (request.POST.get("name") or "").strip()
    kind = (request.POST.get("kind") or Kind.ONE).strip()
    project_id = (request.POST.get("project") or "").strip()
    project = Project.objects.filter(pk=project_id).first() if project_id else None
    validity = (request.POST.get("validity_days") or "").strip()

    if not name:
        messages.error(request, "Say what the line item is.")
    elif kind not in dict(Kind.choices):
        messages.error(request, "Choose how it behaves over time.")
    else:
        # ⚠ A VALIDITY ITEM WITH NO TYPICAL VALIDITY IS FINE. It simply means the
        #   upload form has nothing to suggest and the date is typed from scratch.
        try:
            validity_days = int(validity) if validity else None
        except ValueError:
            validity_days = None

        if item:
            item.name, item.kind, item.project = name, kind, project
            item.validity_days = validity_days
            item.is_compulsory = request.POST.get("compulsory") != "no"
            item.title = title
            item.save()
            messages.success(request, f"{name} saved.")
        else:
            ComplianceItem.objects.create(
                title=title, name=name, kind=kind, project=project,
                validity_days=validity_days,
                is_compulsory=request.POST.get("compulsory") != "no",
                sort_order=(title.items.count() + 1) * 10)
            where = project.code if project else "every project"
            messages.success(request, f"{name} added — it appears on {where} as Missing now.")
    return redirect(f"{reverse('compliance_master')}?type={title.type.code}")


@require_POST
@requires("compliance.master")
def master_deactivate(request, item_id):
    """
    Take a line off every future checklist.

    ⚠ THE DOCUMENTS STAY. There is no delete here or anywhere in this system —
      an item nobody needs any more is not the same as an item that never
      existed, and the paper filed against it may be asked for years later.
    """
    item = get_object_or_404(ComplianceItem.objects.select_related("title__type"), pk=item_id)
    held = item.documents.count()
    item.is_active = False
    item.save(update_fields=["is_active"])
    messages.success(
        request,
        f"{item.name} deactivated." +
        (f" {held} document{'s' if held != 1 else ''} kept and still downloadable." if held else ""))
    return redirect(f"{reverse('compliance_master')}?type={item.title.type.code}")


@require_POST
@requires("compliance.master")
def master_type(request):
    """
    A new regime.

    ⚠ ONE CHOICE IS THE WHOLE DIFFERENCE BETWEEN AMC AND RERA — compulsory
      everywhere, or ticked per project. A fire-department regime or a lender's
      covenant pack needs nothing else.
    """
    code = (request.POST.get("code") or "").strip().upper()
    name = (request.POST.get("name") or "").strip()

    if not code:
        messages.error(request, "A short code is needed — it is what the picker shows.")
    elif ComplianceType.objects.filter(code__iexact=code).exists():
        messages.error(request, f"{code} already exists.")
    else:
        every = request.POST.get("every") == "yes"
        ComplianceType.objects.create(
            code=code, name=name or code, applies_to_every_project=every,
            note="Compulsory on every project." if every else "Ticked per project.",
            sort_order=ComplianceType.objects.count() * 10)
        messages.success(request, f"{code} added. It is empty — give it a title, then line items.")
    return redirect(f"{reverse('compliance_master')}?type={code}")
