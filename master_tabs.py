"""
The tabbed master-data screens.

>>> ANCHOR: MASTER-TABS <<<
⚠⚠ FIVE ENTRIES BEHIND THE TILE, NOT NINE, AND NOTHING OPENS DJANGO ADMIN.
   Saahil, after finding the Units of measure tile dropped him into generic
   scaffolding: "Can we not just make it one tile and then have different
   sections to navigate it? So the master data when we go inside, we do not see
   sixty eight tiles."

   Materials  → Material master · Material groups · Units of measure
   Vendors    → Vendor master · Vendor groups · Vendor rates
   Construction activities → one screen, no tabs (his call: "just the master is
                             enough, it doesn't need any tabs")

⚠ THE THREE CODE-AND-NAME TABLES SHARE ONE VIEW. Material groups, vendor groups
  and units of measure are the same shape — a short key, a name, a flag or two —
  and three near-identical views would be three places to fix the next thing.
  What differs between them is DATA, in `SIMPLE_MASTERS` below.

⚠ EVERY LIST IS EDITED IN PLACE, the same pattern the company rates screen has
  always used: one form, one Save, and a blank row at the bottom to add with.
  These tables are touched a few times a year; a list screen plus a form screen
  plus a confirm screen would be three screens earning their place on a table of
  eleven rows.

⚠ NOTHING IS EVER DELETED FROM HERE. The rule the whole app follows: nothing
  references it → a real delete is possible in Admin; something does → refuse
  and offer Deactivate. On these screens Active is the only route, because a
  group or a unit is referenced by definition.
"""
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.perms import requires
from masters.models import (Activity, Material, MaterialGroup, PanelTranslation,
                            UnitOfMeasure, Vendor, VendorGroup, VendorRate)

ZERO = Decimal("0")


# ------------------------------------------------------------------ the tabs
#
# ⚠ THE TAB STRIP IS DATA, exactly like the launchpad's tiles, and for the same
#   reason: a tab that leads to a 403 is worse than no tab. Each carries the key
#   that opens it.

MATERIAL_TABS = [
    ("material_list", "Material master", "masters.view"),
    ("material_group_list", "Material groups", "masters.view"),
    ("uom_list", "Units of measure", "masters.view"),
]

VENDOR_TABS = [
    ("vendor_list", "Vendor master", "masters.view"),
    ("vendor_group_list", "Vendor groups", "masters.view"),
    ("vendor_rate_list", "Vendor rates", "masters.view"),
]


def tabs_for(strip, here, role_can_fn):
    """Resolve a strip to (label, url, is_open), dropping what this role cannot open."""
    return [{"label": label, "url": reverse(name), "is_open": name == here}
            for name, label, key in strip if role_can_fn(key)]


# -------------------------------------------------- the three simple masters
#
# ⚠ ONE VIEW, THREE TABLES. See the note at the top of the file.

SIMPLE_MASTERS = {
    "materialgroup": {
        "model": MaterialGroup,
        "title": "Material groups",
        "strip": "materials",
        "here": "material_group_list",
        "key_label": "Code",
        "key_field": "code",
        "key_help": "Four characters, used as the middle segment of every material code",
        "blurb": "How materials are grouped — the second segment of every material code.",
        # (field, label, kind) — kind is text, flag or nothing
        #
        # ⚠⚠ `name` WAS MISSING HERE, AND THAT WAS BUG B2. MaterialGroup.name is
        #    a required field on the model, so with no input for it the blank
        #    bottom row could never validate — a group could not be created from
        #    its own screen at all, and the 25 existing names were not even
        #    visible. The only route left was Django Admin, which contradicts
        #    the decision that master data is six entries and nothing opens
        #    Admin. Vendor groups shows its name (it is that table's key field),
        #    which is what proved this an omission rather than a choice.
        "extra": [("name", "Name", "text"),
                  ("is_stock_item", "Stock tracked", "flag")],
        "usage": lambda: dict(MaterialGroup.objects.annotate(n=Count("materials"))
                              .values_list("id", "n")),
        "usage_label": "Materials",
    },
    "vendorgroup": {
        "model": VendorGroup,
        "title": "Vendor groups",
        "strip": "vendors",
        "here": "vendor_group_list",
        "key_label": "Name",
        "key_field": "name",
        "key_help": "What this vendor IS — Cement, Fabricator, Structure Engineer",
        "blurb": "What a vendor is, in the words somebody would search with. "
                 "Not the same question as which construction activity they serve.",
        "extra": [],
        "usage": lambda: dict(VendorGroup.objects.annotate(n=Count("vendors"))
                              .values_list("id", "n")),
        "usage_label": "Vendors",
    },
    "uom": {
        "model": UnitOfMeasure,
        "title": "Units of measure",
        "strip": "materials",
        "here": "uom_list",
        "key_label": "Code",
        "key_field": "code",
        "key_help": 'What is stored on the material and printed on a document — "Bag", "Cum"',
        "blurb": "The vocabulary a material's unit has to come from, and the other "
                 "spellings a spreadsheet might use for it.",
        "extra": [("name", "Spelt out", "text"),
                  ("aliases", "Other spellings", "text")],
        # ⚠ COUNTED BY TEXT, NOT BY A FOREIGN KEY. `Material.uom` stores the code
        #   as a string — see UOM-MASTER. That is also why a code cannot be
        #   renamed once anything carries it.
        "usage": lambda: {u.id: u.in_use for u in UnitOfMeasure.objects.all()},
        "usage_label": "Materials",
    },
}


def _decimal(raw, field, errors, default=None):
    """
    ⚠ UNREADABLE INPUT NEVER BECOMES ZERO, and the wording matches every other
      screen — "could not be read". A rate that silently became 0 is
      indistinguishable from a rate somebody meant to be 0, and this one is what
      every future estimate starts from.
    """
    text = (raw or "").strip().replace(",", "")
    if not text:
        return default
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        errors.append(f"{field} could not be read as a number, so it was left as it was.")
        return default


def _simple_master(request, which):
    spec = SIMPLE_MASTERS[which]
    model = spec["model"]
    rows = list(model.objects.order_by(spec["key_field"]))
    usage = spec["usage"]()

    # ⚠ THE CELL VALUES ARE RESOLVED HERE, NOT IN THE TEMPLATE. Reaching a field
    #   by name from markup needs a custom filter, and arithmetic-by-template is
    #   exactly what this codebase does not do. One dict per row instead.
    return render(request, "projects/simple_master.html", {
        "spec": spec,
        "which": which,
        "save_url": spec["here"].replace("_list", "_save"),
        "rows": [{
            "row": r,
            "used": usage.get(r.id, 0),
            "key": getattr(r, spec["key_field"]),
            "cells": [{"field": f, "label": l, "kind": k, "value": getattr(r, f)}
                      for f, l, k in spec["extra"]],
        } for r in rows],
        "strip": spec["strip"],
        "here": spec["here"],
    })


def _simple_master_save(request, which):
    """
    ⚠ full_clean() ON EVERY ROW, not just save(). The guards that matter on these
      tables live in clean() — a unit's code locking once materials carry it, a
      near-duplicate being refused — and save() alone walks straight past them.
    """
    spec = SIMPLE_MASTERS[which]
    model = spec["model"]
    errors, changed = [], 0

    for row in model.objects.all():
        # >>> ANCHOR: MASTER-TABS <<<
        # ⚠⚠ NO MARKER, NO OPINION — and this guard is the whole of bug B1.
        #    An unticked checkbox is not submitted at all, so "the user cleared
        #    this" and "this row was never on the form" arrive at the server
        #    identically. Without a marker the loop read every row in the table
        #    and set is_active from a key that was never going to be there, so
        #    any row missing from the submitted form went quietly inactive.
        #
        #    It is not hypothetical and it is not rare: two tabs open, or a row
        #    added in one window while another still shows the older form. It
        #    bit Saahil live — TRP went inactive while a different row was being
        #    edited. The workaround was already visible in an older test, which
        #    posts is_active="on" for a row it only wants left alone and says in
        #    a comment why. That was the fault being papered over in the test
        #    instead of fixed here.
        #
        #    The template now renders a hidden row-<id> beside every row it
        #    draws. A row without one was not on the form, so this save has
        #    nothing to say about it.
        if f"row-{row.id}" not in request.POST:
            continue

        moved = []
        for field in [spec["key_field"]] + [f for f, _l, _k in spec["extra"]]:
            key = f"{field}-{row.id}"
            if key not in request.POST:
                continue
            kind = next((k for f, _l, k in spec["extra"] if f == field), "text")
            value = (request.POST.get(key) or "").strip()
            if getattr(row, field) != value:
                setattr(row, field, value)
                moved.append(field)
        for field, _label, kind in spec["extra"]:
            if kind == "flag":
                value = request.POST.get(f"{field}-{row.id}") == "on"
                if getattr(row, field) != value:
                    setattr(row, field, value)
                    moved.append(field)
        if hasattr(row, "is_active"):
            value = request.POST.get(f"is_active-{row.id}") == "on"
            if row.is_active != value:
                row.is_active = value
                moved.append("is_active")
        if not moved:
            continue
        try:
            row.full_clean()
        except ValidationError as refused:
            for field, problems in refused.message_dict.items():
                errors.append(f"{row}: {' '.join(problems)}")
            continue
        row.save(update_fields=moved)
        changed += 1

    # The blank row at the bottom.
    new_key = (request.POST.get(f"new-{spec['key_field']}") or "").strip()
    if new_key:
        fresh = model(**{spec["key_field"]: new_key})
        for field, _label, kind in spec["extra"]:
            if kind == "flag":
                setattr(fresh, field, request.POST.get(f"new-{field}") == "on")
            else:
                setattr(fresh, field, (request.POST.get(f"new-{field}") or "").strip())
        try:
            fresh.full_clean()
            fresh.save()
            messages.success(request, f"{fresh} added.")
        except ValidationError as refused:
            for field, problems in refused.message_dict.items():
                errors.append(f"New row — {field}: {' '.join(problems)}")

    if changed:
        messages.success(request, f"{changed} row{'' if changed == 1 else 's'} saved.")
    elif not errors and not new_key:
        messages.info(request, "Nothing had changed, so nothing was saved.")
    for problem in errors:
        messages.error(request, problem)
    return redirect(reverse(spec["here"]))


@requires("masters.view")
def material_group_list(request):
    return _simple_master(request, "materialgroup")


@require_POST
@requires("masters.edit")
def material_group_save(request):
    return _simple_master_save(request, "materialgroup")


@requires("masters.view")
def vendor_group_list(request):
    return _simple_master(request, "vendorgroup")


@require_POST
@requires("masters.edit")
def vendor_group_save(request):
    return _simple_master_save(request, "vendorgroup")


@requires("masters.view")
def uom_list(request):
    return _simple_master(request, "uom")


@require_POST
@requires("masters.edit")
def uom_save(request):
    return _simple_master_save(request, "uom")


# ------------------------------------------------------------- vendor rates
#
# ⚠ READ AND SEARCH, NOT BULK EDIT. A vendor rate is what one supplier last
#   quoted for one material; it is set on the BOM at the moment of buying, where
#   the person knows what they were told on the telephone. A screen that let
#   somebody retype four hundred of them would be a screen for inventing prices.


@requires("masters.view")
def vendor_rate_list(request):
    # ⚠ THE SOURCE ORDER IS FOUR JOINS DEEP and it is printed on every row, so it
    #   is selected here rather than found again per row — ANCHOR: BOM-CALC-BULK's
    #   lesson, on a smaller screen.
    rows = (VendorRate.objects
            .select_related("vendor", "material", "material__group",
                            "source_po_line__purchase_order",
                            "source_po_line__purchase_order__project")
            .order_by("material__code", "-is_preferred", "rate"))

    applied = {}
    vendor_id = (request.GET.get("vendor") or "").strip()
    if vendor_id.isdigit():
        rows = rows.filter(vendor_id=int(vendor_id))
        applied["vendor"] = int(vendor_id)

    query = (request.GET.get("q") or "").strip()
    if query:
        rows = rows.filter(Q(material__code__icontains=query)
                           | Q(material__name__icontains=query)
                           | Q(vendor__name__icontains=query))
        applied["q"] = query

    rows = list(rows[:500])
    return render(request, "projects/vendor_rates.html", {
        "rows": rows,
        "applied": applied,
        "vendors": Vendor.objects.filter(is_active=True).order_by("name"),
        "total": VendorRate.objects.count(),
        "strip": "vendors",
        "here": "vendor_rate_list",
    })


# ------------------------------------------------ the ⓘ panels, in Gujarati
#
# >>> ANCHOR: INFO-PANELS <<<
# ⚠⚠ GUJARATI ONLY, AND ONE PANEL AT A TIME. The English lives in code, ships
#    with the app and is what the tests check; this screen writes the other
#    language beside it. Saahil's idea, and a better one than the plan it
#    replaced: their own people correct the translation on screen rather than
#    checking a document that somebody then has to paste back.
#
# ⚠⚠ STRUCTURE IS NOT EDITABLE, ANYWHERE, BY ANYBODY. No adding a step, no
#    deleting one, no reordering. His words: "Structure should never be editable
#    in reality, especially by a user." A panel whose steps can be rearranged
#    drifts from the screen it describes, and nothing would notice.
#
# ⚠ ONE PANEL PER SCREEN LOAD, not all 37. A hundred and fifty-seven textareas
#   on one page is a screen nobody finishes and a POST nobody can review.


@requires("help.edit")
def panel_text(request, key=None):
    """Write the Gujarati for one panel's steps."""
    from projects.help_panels import PANELS

    keys = sorted(PANELS)
    key = key if key in PANELS else (request.GET.get("panel") or keys[0])
    if key not in PANELS:
        key = keys[0]
    panel = PANELS[key]

    written = {row.step_label: row for row in
               PanelTranslation.objects.filter(panel_key=key).select_related("updated_by")}

    rows = []
    for entry in panel["steps"]:
        row = written.get(entry["label"])
        rows.append({
            "step": entry,
            "gujarati": row.gujarati if row else "",
            "updated_by": row.updated_by if row else None,
            "updated_at": row.updated_at if row else None,
            # ⚠⚠ THE DRIFT FLAG. A translation is written against a particular
            #   English instruction; when that instruction changes, the Gujarati
            #   describes something that no longer exists and nobody reading only
            #   Gujarati could ever find out. The row keeps what it was written
            #   from, and this is the comparison.
            "stale": bool(row and row.gujarati
                          and row.source_english
                          and row.source_english != entry["text"]),
            "was": row.source_english if row else "",
            # ⚠⚠ NOBODY HAS CHECKED THIS ONE. A row seeded by
            #   `seed_panel_translations` is Claude's first draft and carries no
            #   author; a row saved from this screen always carries the person
            #   who saved it. So "written by a person" is a fact the table
            #   already holds, and the reader of this screen should see it —
            #   the same rule as the compliance checklist saying on screen that
            #   its content is a first draft.
            "draft": bool(row and row.gujarati and row.updated_by_id is None),
        })

    return render(request, "projects/panel_text.html", {
        "panels": [(k, PANELS[k]["title"]) for k in keys],
        "key": key,
        "panel": panel,
        "rows": rows,
        "written": sum(1 for r in rows if r["gujarati"]),
        "stale": sum(1 for r in rows if r["stale"]),
        "drafts": sum(1 for r in rows if r["draft"]),
        "strip": None,
    })


@require_POST
@requires("help.edit")
def panel_text_save(request, key):
    """
    Save one panel's translations.

    ⚠ SAVING RECORDS THE ENGLISH IT WAS WRITTEN AGAINST, which is the whole of
      the staleness mechanism. Nothing else on the screen can set it, so it
      cannot be got wrong.

    ⚠ AN EMPTIED BOX DELETES THE ROW rather than storing an empty string. The
      step falls back to having no translation, exactly as before anybody typed —
      and the language toggle disappears from that panel, because it can no
      longer show a complete one.
    """
    from projects.help_panels import PANELS

    panel = PANELS.get(key)
    if not panel:
        raise Http404("No such panel")

    changed = 0
    for entry in panel["steps"]:
        typed = (request.POST.get(f"gu-{entry['label']}") or "").strip()
        existing = PanelTranslation.objects.filter(panel_key=key,
                                                   step_label=entry["label"]).first()
        if not typed:
            if existing:
                existing.delete()
                changed += 1
            continue
        if existing and existing.gujarati == typed and existing.source_english == entry["text"]:
            continue
        PanelTranslation.objects.update_or_create(
            panel_key=key, step_label=entry["label"],
            defaults={"gujarati": typed, "source_english": entry["text"],
                      "updated_by": request.user})
        changed += 1

    messages.success(
        request,
        f"{panel['title']} — {changed} step{'' if changed == 1 else 's'} saved."
        if changed else f"{panel['title']} — nothing changed.")
    return redirect(f"{reverse('panel_text')}?panel={key}")


# --------------------------------------------- the construction activity master
#
# >>> ANCHOR: ACTIVITY-MASTER <<<
# ⚠⚠ THIS ABSORBED THE "COMPANY RATES" SCREEN. The company's default ₹/sqft was
#    never company data — it is a column on the activity. Saahil, when the
#    restructure was described to him: "Those rates are related to concerned
#    activity. Are they not? So already we are maintaining the rates in
#    construction activity, then why is it coming in company profile?"
#
# ⚠ THE NAME IS EDITABLE HERE AND THE MODEL REFUSES A RENAME ONCE AN ESTIMATE
#   HAS COPIED IT — see ANCHOR: ACTIVITY-RENAME-BLOCKED. It is deliberately not
#   hidden: hiding the field was the OLD protection, and it protected nothing,
#   because Django Admin renamed activities happily. A visible field that
#   refuses, and says why, teaches the rule. An absent field teaches nothing.
#
# ⚠ THE ABBREVIATION IS SHOWN AND NEVER EDITABLE. It is the first segment of
#   every material code created under this activity — PLM in PLM-PL3-014 — and
#   codes are never regenerated.


@requires("masters.view")
def activity_master(request):
    from projects.models import EstimateLine

    activities = list(Activity.objects.annotate(links=Count("material_links"))
                      .order_by("sort_order", "name"))

    # ⚠ ONE GROUPED QUERY, NOT ONE PER ROW. `estimates_using_the_name` is fine
    #   for a single activity in the model's own guard; asking it eighteen times
    #   while drawing a table is the shape of bugs 9 and 10.
    counts = dict(EstimateLine.objects.values_list("name")
                  .annotate(n=Count("id")).values_list("name", "n"))

    rows = [{
        "activity": a,
        "links": a.links,
        # How many estimate lines would be orphaned by a rename. Drives the lock
        # beside the name, so the model's refusal is never a surprise.
        "locked": counts.get(a.name, 0),
    } for a in activities]

    return render(request, "projects/activity_master.html", {"rows": rows})


@require_POST
@requires("masters.edit")
def activity_master_save(request):
    errors, changed = [], 0

    for activity in Activity.objects.all():
        moved = []
        name = (request.POST.get(f"name-{activity.id}") or "").strip()
        if name and name != activity.name:
            activity.name = name
            moved.append("name")
        for field, key in (("rate", "rate"), ("gst_percent", "gst")):
            raw = request.POST.get(f"{key}-{activity.id}")
            if raw is None:
                continue
            value = _decimal(raw, f"{activity.abbreviation} {key}", errors)
            if value is not None and getattr(activity, field) != value:
                setattr(activity, field, value)
                moved.append(field)
        basis = (request.POST.get(f"basis-{activity.id}") or "").strip()
        if basis != activity.basis:
            activity.basis = basis
            moved.append("basis")
        wanted = request.POST.get(f"active-{activity.id}") == "on"
        if activity.is_active != wanted:
            activity.is_active = wanted
            moved.append("is_active")

        if not moved:
            continue
        try:
            activity.full_clean()
        except ValidationError as refused:
            for _field, problems in refused.message_dict.items():
                errors.append(" ".join(problems))
            continue
        activity.save(update_fields=moved + ["updated_at"])
        changed += 1

    if changed:
        messages.success(request, f"{changed} construction activit"
                                  f"{'y' if changed == 1 else 'ies'} saved. Existing projects keep "
                                  f"the rates they copied.")
    elif not errors:
        messages.info(request, "Nothing had changed, so nothing was saved.")
    for problem in errors:
        messages.error(request, problem)
    return redirect(reverse("activity_master"))


# ------------------------------------------------------------- the tab shells


@requires("masters.view")
def materials_home(request):
    """The Materials tile — its first tab is the master itself."""
    return redirect(reverse("material_list"))


@requires("masters.view")
def vendors_home(request):
    """The Vendors tile — its first tab is the master itself."""
    return redirect(reverse("vendor_list"))
