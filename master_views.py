"""
The master data screens: materials and vendors.

WHAT THIS FILE IS FOR
    material_list / material_form    705 rows, and one of them
    vendor_list   / vendor_form      173 rows, and one of them

WHY IT IS A SEPARATE MODULE FROM views.py
    Nothing deeper than size. views.py is the project chain — BOQ, BOM, orders —
    and was already long before this. These screens sit beside company_profile
    and rate_defaults, which are master data living in the projects app for the
    same reason: there is one urls.py and one set of templates, and splitting the
    routing would buy tidiness at the cost of a second place to look.

⚠ NOT ONE FIGURE IS CALCULATED HERE. Same rule as views.py. These screens read
  and write master records; they do not decide what any number means.

⚠ NO PERMISSION CHECK ANYWHERE IN THIS FILE, and this is the file where that
  matters most. Anyone who can reach these URLs can change the estimation rate
  that every BOQ in the company is built from. Security is its own slice.
"""
import io
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from masters import sheets
from masters.codes import next_code
from masters.imports import normalise
from accounts.perms import requires
from masters.models import (Activity, Material, MaterialGroup, UnitOfMeasure, Vendor,
                            VendorGroup, active_uom_choices)

# One page of rows. The filters are the real tool — 705 materials is not a list
# anybody scrolls, it is a list they search.
PAGE_SIZE = 100


def _decimal(raw, field, errors, default=None):
    """
    Read a typed number, or record why it could not be read.

    ⚠ UNREADABLE INPUT MUST NEVER BECOME ZERO. The BOM screen learned this the
      hard way: a rate that silently became 0 is indistinguishable from a rate
      somebody meant to be 0, and it quietly changes every estimate built on it.
    """
    text = (raw or "").strip().replace(",", "")
    if not text:
        return default
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        errors.append(f"{field}: “{raw}” is not a number, so it was left alone.")
        return default


def _groups_for(material):
    """
    The material groups to offer on the material form.

    ⚠ ACTIVE ONES, PLUS WHATEVER THIS MATERIAL ALREADY CARRIES — the same rule
      and the same reason as `_uoms_for` below. Deactivating a group must stop it
      being chosen again; it must not silently rewrite the materials already in
      it. Without the second half, opening a material whose group had since been
      retired would show the dropdown defaulting to something else, and saving
      would move the material to another group with nobody meaning to.
    """
    groups = list(MaterialGroup.objects.filter(is_active=True).order_by("code"))
    if material and material.group_id and all(g.id != material.group_id for g in groups):
        groups.append(material.group)
    return groups


def _uoms_for(material):
    """
    The units to offer on the material form.

    ⚠ ACTIVE ONES, PLUS WHATEVER THIS MATERIAL ALREADY CARRIES. Deactivating a
      unit must stop it being CHOSEN AGAIN — it must not silently rewrite the
      618 materials already using it. Without this, opening a material whose
      unit had since been deactivated would show the dropdown defaulting to
      something else, and saving would change the unit without anybody meaning
      to. Inactive means "do not offer this again", never "this is wrong".
    """
    choices = active_uom_choices()
    current = (material.uom or "").strip()
    if current and current not in {code for code, _label in choices}:
        choices.append((current, f"{current} — no longer offered"))
    return choices


# ============================================================== materials
#
# >>> ANCHOR: MATERIAL-SCREEN <<<
# The master that everything else is built on. 705 rows, and the estimation rate
# on each of them drives every BOQ in the company.


def _filtered_materials(request):
    """
    The materials this request is asking for, and which filters were applied.

    >>> ANCHOR: MASTER-EXPORT-FOLLOWS-FILTERS <<<
    ⚠ ONE IMPLEMENTATION, SHARED BY THE SCREEN AND THE EXPORT. Saahil asked to
      download a few materials rather than all 705, and the four filters on the
      list are already that selection — so the export reads them from the same
      function the table does. Two copies would drift, and the first symptom
      would be a spreadsheet that quietly disagrees with the screen it was
      downloaded from.

    Returns a queryset, or a plain list once the search box narrows it in
    Python. Both are fine: everything downstream only iterates.
    """
    rows = (Material.objects
            .select_related("group", "home_activity", "also_used_in")
            .order_by("code"))

    applied = {}

    group_code = (request.GET.get("group") or "").strip()
    if group_code:
        rows = rows.filter(group__code=group_code)
        applied["group"] = group_code

    activity = (request.GET.get("activity") or "").strip()
    if activity:
        # ⚠ EITHER COLUMN COUNTS. A material bought under two trades must appear
        #   when you filter on either of them — that is the whole point of the
        #   second column. No distinct() needed: two columns on one row cannot
        #   produce two rows, which a join could.
        rows = rows.filter(Q(home_activity__abbreviation=activity)
                           | Q(also_used_in__abbreviation=activity))
        applied["activity"] = activity

    show = (request.GET.get("show") or "active").strip()
    if show == "active":
        rows = rows.filter(is_active=True)
    elif show == "inactive":
        rows = rows.filter(is_active=False)
    applied["show"] = show

    query = (request.GET.get("q") or "").strip()
    if query:
        # Normalised matching cannot be done in SQL, so this narrows in the
        # database first and then filters what is left in Python. On 705 rows
        # that is nothing; it would need rethinking at fifty thousand.
        needle = normalise(query)
        rows = [m for m in rows
                if needle in normalise(m.code) or needle in normalise(m.name)
                or needle in normalise(m.specification) or needle in normalise(m.search_aliases)]
        applied["q"] = query

    return rows, applied


@requires("masters.view")
def material_list(request):
    """
    Every material, searched rather than scrolled.

    ⚠ THE SEARCH USES masters.imports.normalise, THE SAME FUNCTION THE IMPORT
      USES TO SPOT DUPLICATES. If searching and de-duplicating normalised
      differently you would get duplicates that the search box cannot find,
      which is the worst of both worlds. 78 of the 705 write their size
      inconsistently, so this is not hypothetical.
    """
    rows, applied = _filtered_materials(request)

    page = Paginator(rows, PAGE_SIZE).get_page(request.GET.get("page"))

    return render(request, "projects/material_list.html", {
        "page_obj": page,
        "rows": page.object_list,
        "matched": page.paginator.count,
        "applied": applied,
        "groups": MaterialGroup.objects.order_by("code"),
        "activities": Activity.objects.filter(is_active=True).order_by("sort_order", "name"),
        "querystring": request.GET.urlencode(),
        # The download button says how many it will fetch, so nobody presses it
        # expecting a template. Hard-coding 705 would go stale the first time
        # somebody adds one.
        "total_materials": Material.objects.count(),
        # ⚠ THE BUTTON STATES WHAT IT WILL DOWNLOAD, and that is the whole of the
        #   safeguard: the export follows the filters silently otherwise, and a
        #   spreadsheet of 40 rows when you expected 705 looks like data loss.
        "filtered": bool(applied.get("q") or applied.get("group")
                         or applied.get("activity") or applied.get("show") != "active"),
    })


@requires("masters.edit")
def material_form(request, material_id=None):
    """
    Create a material, or change one. The same screen does both.

    ⚠ THE CODE IS NEVER TYPED. On a new material there is no code box; it is
      generated from the home activity and the group when you press Create —
      ACTIVITY-GROUP-SERIAL, e.g. PLM-PL3-014. On an existing material it is
      shown and cannot be changed, because purchase orders point at it.

    ⚠ AND IT IS NEVER REGENERATED. Move a material to a different trade and it
      keeps the code it was born with, so an old code may name an activity it no
      longer belongs to. That is deliberate: a code printed on a purchase order
      must never stop resolving, and nothing in the system parses one.
    """
    material = get_object_or_404(Material, pk=material_id) if material_id else Material()

    if request.method == "POST":
        errors = []
        material.name = (request.POST.get("name") or "").strip()
        material.specification = (request.POST.get("specification") or "").strip()
        material.uom = (request.POST.get("uom") or "").strip()
        material.hsn_code = (request.POST.get("hsn_code") or "").strip()
        material.search_aliases = (request.POST.get("search_aliases") or "").strip()
        material.is_common = request.POST.get("is_common") == "on"
        material.is_active = request.POST.get("is_active") == "on"
        material.estimation_rate = _decimal(request.POST.get("estimation_rate"),
                                            "Estimation rate", errors,
                                            material.estimation_rate or Decimal("0"))
        material.gst_percent = _decimal(request.POST.get("gst_percent"), "GST %", errors,
                                        material.gst_percent or Decimal("18"))
        material.reorder_level = _decimal(request.POST.get("reorder_level"), "Reorder level",
                                          errors, material.reorder_level)
        material.current_stock = _decimal(request.POST.get("current_stock"), "Current stock",
                                          errors, material.current_stock or Decimal("0"))

        group_id = (request.POST.get("group") or "").strip()
        material.group = MaterialGroup.objects.filter(pk=group_id).first() if group_id else None
        home_id = (request.POST.get("home_activity") or "").strip()
        material.home_activity = Activity.objects.filter(pk=home_id).first() if home_id else None
        second_id = (request.POST.get("also_used_in") or "").strip()
        material.also_used_in = (Activity.objects.filter(pk=second_id).first()
                                 if second_id else None)

        if not material.name:
            errors.append("A material needs a name.")
        if not material.group:
            errors.append("Pick a group — it is part of the code.")
        if not material.home_activity:
            errors.append("Pick a home activity. Every material belongs to one construction activity.")
        try:
            material.clean()
        except ValidationError as refusal:
            errors.extend(m for msgs in refusal.message_dict.values() for m in msgs)

        if errors:
            for line in errors:
                messages.error(request, line)
        else:
            if not material.pk:
                material.code = next_code(material.home_activity, material.group)
            material.save()
            messages.success(
                request,
                f"{material.code} saved."
                if material_id else
                f"{material.code} created. The code is assigned once and never changes.")
            return redirect("material_list")

    return render(request, "projects/material_form.html", {
        "material": material,
        "groups": _groups_for(material),
        "activities": Activity.objects.filter(is_active=True).order_by("sort_order", "name"),
        # ⚠ ACTIVE UNITS ONLY — but see below: the one this material already
        #   carries is added back even if it has been deactivated since.
        "uoms": _uoms_for(material),
    })


# ================================================================ vendors
#
# >>> ANCHOR: VENDOR-SCREEN <<<
# 173 rows. The GSTIN on each of them decides whether a purchase order can be
# approved at all.


def _filtered_vendors(request):
    """
    The vendors this request is asking for, and which filters were applied.
    Shared by the screen and the export — see MASTER-EXPORT-FOLLOWS-FILTERS.
    """
    rows = (Vendor.objects
            .select_related("group", "activity_1", "activity_2")
            .order_by("name"))

    applied = {}

    group_id = (request.GET.get("group") or "").strip()
    if group_id.isdigit():
        rows = rows.filter(group_id=int(group_id))
        applied["group"] = int(group_id)

    activity = (request.GET.get("activity") or "").strip()
    if activity:
        rows = rows.filter(Q(activity_1__abbreviation=activity)
                           | Q(activity_2__abbreviation=activity))
        applied["activity"] = activity

    doc_type = (request.GET.get("type") or "").strip()
    if doc_type in ("PO", "WO"):
        rows = rows.filter(default_document_type=doc_type)
        applied["type"] = doc_type

    # ⚠ A vendor without a GSTIN cannot have a purchase order approved. Better
    #   found on this screen than by somebody trying to approve one.
    if request.GET.get("nogst") == "1":
        rows = rows.filter(gst_number="", is_unregistered=False)
        applied["nogst"] = "1"

    show = (request.GET.get("show") or "active").strip()
    if show == "active":
        rows = rows.filter(is_active=True)
    elif show == "inactive":
        rows = rows.filter(is_active=False)
    applied["show"] = show

    query = (request.GET.get("q") or "").strip()
    if query:
        rows = rows.filter(Q(code__icontains=query) | Q(name__icontains=query)
                           | Q(contact_person__icontains=query) | Q(phone__icontains=query)
                           | Q(group__name__icontains=query))
        applied["q"] = query

    return rows, applied


@requires("masters.view")
def vendor_list(request):
    """Every vendor, with the two things most often missing: a GSTIN and a group."""
    rows, applied = _filtered_vendors(request)

    page = Paginator(rows, PAGE_SIZE).get_page(request.GET.get("page"))

    return render(request, "projects/vendor_list.html", {
        "page_obj": page,
        "rows": page.object_list,
        "matched": page.paginator.count,
        "applied": applied,
        "groups": VendorGroup.objects.filter(is_active=True).order_by("name"),
        "activities": Activity.objects.filter(is_active=True).order_by("sort_order", "name"),
        "querystring": request.GET.urlencode(),
        "missing_gstin": Vendor.objects.filter(gst_number="", is_unregistered=False,
                                               is_active=True).count(),
        "total_vendors": Vendor.objects.count(),
        # See the note on the material list — the button says what it will fetch.
        "filtered": bool(applied.get("q") or applied.get("group") or applied.get("activity")
                         or applied.get("type") or applied.get("nogst")
                         or applied.get("show") != "active"),
    })


@requires("masters.edit")
def vendor_form(request, vendor_id=None):
    """
    Create a vendor, or change one.

    ⚠ IDENTITY IS THE PHONE NUMBER, NOT THE NAME. Two vendors may legitimately
      share a name; nothing about the same number twice is legitimate. That rule
      came out of the import and it holds here.

    ⚠ WHATSAPP FILLS ITSELF ONLY WHEN BLANK — see Vendor.save(). Deriving it on
      every save silently threw away numbers typed by hand, which is wrong for
      the vendors whose main line is an 1800 number.
    """
    vendor = get_object_or_404(Vendor, pk=vendor_id) if vendor_id else Vendor()

    if request.method == "POST":
        errors = []
        for field in ("name", "contact_person", "phone", "whatsapp_number", "secondary_contact",
                      "secondary_phone", "email", "gst_number", "address", "payment_terms"):
            setattr(vendor, field, (request.POST.get(field) or "").strip())
        vendor.is_unregistered = request.POST.get("is_unregistered") == "on"
        vendor.is_active = request.POST.get("is_active") == "on"
        vendor.default_document_type = (request.POST.get("default_document_type") or "PO").strip()

        group_id = (request.POST.get("group") or "").strip()
        vendor.group = VendorGroup.objects.filter(pk=group_id).first() if group_id else None
        for slot in ("activity_1", "activity_2"):
            raw = (request.POST.get(slot) or "").strip()
            setattr(vendor, slot, Activity.objects.filter(pk=raw).first() if raw else None)

        if not vendor.name:
            errors.append("A vendor needs a name.")
        if not vendor.phone:
            errors.append("A phone number is how a vendor is identified — two vendors may share "
                          "a name, but not a number.")
        if vendor.activity_2 and vendor.activity_2_id == vendor.activity_1_id:
            errors.append("The second activity repeats the first. Leave it blank unless they "
                          "genuinely serve two construction activities.")
        if vendor.gst_number and vendor.is_unregistered:
            errors.append("A vendor cannot be unregistered and have a GSTIN. Clear one of them.")

        if errors:
            for line in errors:
                messages.error(request, line)
        else:
            try:
                vendor.full_clean(exclude=["code"])
            except ValidationError as refusal:
                for messages_for_field in refusal.message_dict.values():
                    for line in messages_for_field:
                        messages.error(request, line)
            else:
                if not vendor.pk:
                    last = Vendor.objects.order_by("-code").values_list("code", flat=True).first()
                    number = int(last.split("-")[-1]) + 1 if last and last.split("-")[-1].isdigit() else 1
                    vendor.code = f"VEN-{number:03d}"
                vendor.save()
                messages.success(request, f"{vendor.code} — {vendor.name} saved.")
                return redirect("vendor_list")

    return render(request, "projects/vendor_form.html", {
        "vendor": vendor,
        "groups": VendorGroup.objects.filter(is_active=True).order_by("name"),
        "activities": Activity.objects.filter(is_active=True).order_by("sort_order", "name"),
    })


# ==================================================== the Excel round trip
#
# >>> ANCHOR: MASTER-EXCEL <<<
# Download a master, correct it in Excel, upload it back.
#
# ⚠⚠ THE PROPERTY, AND IT IS A TEST: download the file, change nothing, upload
#    it → 0 created, N skipped, 0 errors. If a round trip alters one record that
#    is a bug. Everything in masters/sheets.py serves that one sentence.
#
# ⚠ THE CODE IS THE KEY, NOT A DATABASE ID. Code filled in means update that
#   record; code blank means it is new and a code is generated on import. So one
#   file does download, correction and fresh additions, and nobody ever sees a
#   number that means nothing to them.
#
# ⚠ THERE IS NO DELETE. A spreadsheet is the wrong instrument for destroying
#   data — a row deleted by accident is invisible, and the file is edited by
#   whoever has it open. Active = No already takes a record out of every picker
#   while every historical document still resolves.


def _spreadsheet(book, filename):
    stream = io.BytesIO()
    book.save(stream)
    stream.seek(0)
    response = HttpResponse(
        stream.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _report_to_messages(request, report):
    """
    Say what happened, in the words the import command already uses.

    ⚠ THE SUMMARY LINE IS THE TESTABLE ONE — "0 created, 0 updated, 705
      unchanged, 0 errors" is what a round trip that changed nothing must print.

    >>> ANCHOR: IMPORT-REPORT <<<
    ⚠⚠ `touched`, NOT `created` — bug C5. Updates used to be filed as creations,
       so a round trip that edited one vendor announced "1 created" above a
       per-row line that correctly said "updated: payment_terms". The summary
       contradicted the detail underneath it.
    """
    messages.success(request, report.summary())
    touched = report.touched
    for identifier, detail in touched[:15]:
        messages.info(request, f"{identifier} — {detail}")
    if len(touched) > 15:
        messages.info(request, f"…and {len(touched) - 15} more changed.")
    for row_number, problem in report.errors[:25]:
        messages.error(request, f"Row {row_number}: {problem}")
    if len(report.errors) > 25:
        messages.error(request, f"…and {len(report.errors) - 25} more rows were refused.")


@require_POST
@requires("masters.view")
def material_export(request):
    """
    What the screen was showing, as a spreadsheet.

    ⚠ THE FILTERS COME THROUGH THE QUERY STRING, which the button carries in its
      formaction — so "what I am looking at" needs no second copy of the
      filtering. Unfiltered, this is still the whole master.
    """
    rows, _applied = _filtered_materials(request)
    stamp = timezone.localdate().isoformat()
    return _spreadsheet(sheets.material_workbook(rows=rows), f"Materials_{stamp}.xlsx")


@require_POST
@requires("masters.view")
def material_template(request):
    """
    ⚠ THE SAME SHEET WITH NOTHING IN IT. Saahil: "I dont feel a need to download
      all materials as well, there should be one more button for download
      template for them to add." Downloading 705 rows to add three is the wrong
      shape, and scrolling past somebody else's data to type is how mistakes
      happen. Same headings, same notes, same dropdowns, same Reference sheet.
    """
    return _spreadsheet(sheets.material_workbook(blank=True), "Materials_template.xlsx")


@require_POST
@requires("masters.import")
def material_import(request):
    uploaded = request.FILES.get("file")
    if not uploaded:
        messages.error(request, "No file was chosen.")
        return redirect("material_list")
    try:
        report = sheets.read_materials(uploaded)
    except Exception as refusal:                       # a corrupt or wrong file
        messages.error(request, f"That file could not be read as a material sheet — {refusal}. "
                                f"Nothing was changed.")
        return redirect("material_list")
    _report_to_messages(request, report)
    return redirect("material_list")


@require_POST
@requires("masters.view")
def vendor_export(request):
    """What the screen was showing — see material_export."""
    rows, _applied = _filtered_vendors(request)
    stamp = timezone.localdate().isoformat()
    return _spreadsheet(sheets.vendor_workbook(rows=rows), f"Vendors_{stamp}.xlsx")


@require_POST
@requires("masters.view")
def vendor_template(request):
    """A blank vendor sheet to add on — see material_template."""
    return _spreadsheet(sheets.vendor_workbook(blank=True), "Vendors_template.xlsx")


@require_POST
@requires("masters.import")
def vendor_import(request):
    uploaded = request.FILES.get("file")
    if not uploaded:
        messages.error(request, "No file was chosen.")
        return redirect("vendor_list")
    try:
        report = sheets.read_vendors(uploaded)
    except Exception as refusal:
        messages.error(request, f"That file could not be read as a vendor sheet — {refusal}. "
                                f"Nothing was changed.")
        return redirect("vendor_list")
    _report_to_messages(request, report)
    return redirect("vendor_list")
