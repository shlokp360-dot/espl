"""
The screens. Slice 4 = the BOM screen, built from BOM_Prototype.html.

WHAT THIS FILE IS FOR
    project_list      every project, and whether it has an estimate and a BOM
    bom_screen        the grid itself — one tab per activity
    bom_save          writes back the columns a human types
    bom_add_lines     puts searched materials onto the current activity
    bom_remove_line   takes one off
    bom_post_pos      hands the BOM to po_service and reports what it made
    bom_generate      creates the BOM for a project that has none yet

WHAT DEPENDS ON IT
    Nothing yet — this is the top of the stack. The Excel export (slice 6) will
    read the same bom_calc functions these views read, not these views.

⚠ NOT ONE NUMBER IS CALCULATED HERE.
    Every figure on the screen comes from bom_calc. The prototype computed
    "quantity to order" in three separate places and they could drift; the whole
    point of bom_calc is that there is exactly one. A view that worked out a
    total "just for the footer" would quietly become the fourth.

    Views may PARSE what a human typed and DECIDE what to show. They may not
    decide what a number means.

⚠ THERE IS NO PERMISSION CHECK ANYWHERE IN THIS FILE.
    Anyone who can reach the URL can edit any BOM and raise purchase orders on
    any project. That is a known, deliberate gap — security is its own slice and
    has not been done. Fine on a laptop. NOT fine on a server.

WHY THE SCREEN RELOADS INSTEAD OF RECALCULATING AS YOU TYPE
    The prototype recalculated in JavaScript, which meant the rules existed in
    JavaScript too. Doing that here would put a second copy of bom_calc in the
    browser, and the two would disagree the first time either changed. So: you
    type, you press Save, the server recalculates, the page comes back correct.
    Slower by a second; impossible to get wrong.
"""
import datetime
import io
import zipfile
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from accounts import perms
from accounts.models import role_of
from accounts.perms import requires, requires_any
from masters.imports import normalise
from masters.models import CompanyProfile, DocumentType, Material, MaterialGroup, Vendor
from . import bom_calc, hub, po_service
from .bom_models import Bom, BomLine, PurchaseOrder, PurchaseOrderLine
from .models import Activity, Estimate, EstimateLine, Project

# ⚠ MOVING A DOCUMENT ALONG IS THREE DIFFERENT PERMISSIONS, not one.
#   The matrix hands approve, deliver and pay to different people deliberately,
#   and both the single-document button row and the register's bulk box read
#   this one mapping — so the two can never disagree about who may do what.
TRANSITION_PERMS = {
    PurchaseOrder.Status.APPROVED: "po.approve",
    PurchaseOrder.Status.DELIVERED: "po.deliver",
    PurchaseOrder.Status.PAID: "po.pay",
}

ZERO = Decimal("0")

# The material search returns at most this many rows. The prototype used 60 and
# it was never the limit that got in the way — the filters were. A longer list
# is not more useful, it is just more scrolling.
SEARCH_LIMIT = 60

# Below this the search box shows nothing rather than the whole master. Typing
# one letter would return four hundred rows, which is not a search result.
MIN_SEARCH_LENGTH = 2


# ---------------------------------------------------------------- small tools

def _decimal_or_error(raw, field, problems, allow_blank=False):
    """
    Turn typed text into a Decimal, or record a problem and change nothing.

    Blank means zero for most columns, but for the order-quantity override it
    means "no override, use the suggestion" — hence allow_blank, which returns
    None so the caller can tell the two apart.

    ⚠ Deliberately NOT silent. The prototype turned anything unparseable into
    zero, so a fat-fingered "12OO" became a planned quantity of nothing and the
    line quietly stopped being ordered. Here the row keeps its old value and the
    screen says which cell it could not read.
    """
    text = (raw or "").strip().replace(",", "")
    if text == "":
        return None if allow_blank else ZERO
    try:
        value = Decimal(text)
    except InvalidOperation:
        problems.append(f'"{raw}" is not a number, so {field} was left as it was.')
        return "skip"
    if value < ZERO:
        problems.append(f"{field} cannot be negative, so it was left as it was.")
        return "skip"
    return value


def _resolve_vendor(raw, problems, line_label):
    """
    Turn what was typed in the vendor box into a Vendor, or None to clear it.

    Accepts the code, the name, or the "VEN-020 · Sambhav Hardware" text the
    dropdown fills in. Code is tried first because it is the unambiguous one —
    ⚠ vendor NAMES are not unique in the real file and never were. Identity is
    the phone number; the code stands in for it on screen.

    Anything unrecognised is reported and the line keeps the vendor it had.
    """
    text = (raw or "").strip()
    if text == "":
        return None
    code = text.split("·")[0].strip()
    vendor = Vendor.objects.filter(code__iexact=code).first()
    if vendor is None:
        vendor = Vendor.objects.filter(name__iexact=text).first()
    if vendor is None:
        problems.append(f'No vendor matches "{text}" on {line_label}, so it was left as it was.')
        return "skip"
    return vendor


def _activity_for(bom, requested):
    """
    Which tab is open. The one asked for, else the first that has lines, else
    the first on the estimate. Never blows up on a BOM with nothing in it yet.
    """
    tabs = _tab_activities(bom)
    if requested:
        for activity in tabs:
            if activity.abbreviation == requested:
                return activity
    return tabs[0] if tabs else None


def _tab_activities(bom):
    """
    The tabs across the top: every activity on this project's estimate, PLUS any
    that already has BOM lines.

    The union matters in both directions. An estimate activity with no lines yet
    needs a tab or you could never add the first material to it. And a BOM line
    under an activity that was later removed from the estimate must stay
    visible — its reserve reads zero, which is the honest answer, rather than
    the line disappearing along with the money spent on it.
    """
    names = set()
    if hasattr(bom.project, "estimate"):
        names = {line.name for line in bom.project.estimate.lines.all()}

    with_lines = set(bom.lines.values_list("activity_id", flat=True))
    return list(Activity.objects.filter(Q(name__in=names) | Q(id__in=with_lines)).distinct())


def _search_materials(activity, query, group_code, scope):
    """
    The "add materials" search.

    >>> ANCHOR: BOM-MATERIAL-FILTER <<<
    Which materials an activity offers comes from the material's OWN COLUMNS —
    `home_activity` and `also_used_in` — never from reading the first three
    letters of a code. A material keeps its original code when it is
    reclassified, so the code names where it was born, not where it can be used.

    ⚠⚠ THIS QUERY WAS LEFT READING THE DEAD LINK TABLE AFTER SLICE 8, AND IT WAS
      A LIVE BUG FOR A DAY.

      Slice 8 moved a material's trade onto the material itself and deleted
      nothing, so `activity_links` still held its 705 original rows and this
      screen went on working — for the materials that existed before. Every
      material created afterwards, through the new Material screen or the Excel
      upload, has a real home activity and NO link row, so it scored zero hits
      here and was invisible to the one screen that needs it. Switching the
      search to "all activities" found it, which is why it could have gone
      unnoticed for a long time.

      367 tests passed throughout. None of them created a material the way the
      app creates one and then looked for it. There is now one that does.

    ⚠ EITHER COLUMN COUNTS, and no distinct() is needed — two columns on one row
      cannot produce two rows, which the old join could.

    Common materials appear under every activity whatever their home — wall
    plugs and fevicol are bought by every trade.

    Text matching uses masters.imports.normalise, the SAME function the import
    uses to spot duplicates. If search and dedupe normalised differently you
    would get duplicates the search box cannot find, which is the worst of both
    worlds; 78 of the 721 materials write their size inconsistently, so this is
    not hypothetical.
    """
    candidates = Material.objects.filter(is_active=True).select_related("group")

    if scope != "all" and activity is not None:
        candidates = candidates.filter(
            Q(home_activity=activity) | Q(also_used_in=activity) | Q(is_common=True)
        )

    if group_code:
        candidates = candidates.filter(group__code=group_code)

    text = (query or "").strip()
    if len(text) < MIN_SEARCH_LENGTH:
        # No query: show what the filters alone select, so an activity with few
        # materials can be browsed rather than guessed at.
        return list(candidates.order_by("code")[:SEARCH_LIMIT]), candidates.count()

    needle = normalise(text)
    hits = [
        material for material in candidates.order_by("code")
        if needle in normalise(material.code)
        or needle in normalise(material.name)
        or needle in normalise(material.specification)
        or needle in normalise(material.group.code)
        or needle in normalise(material.group.name)
        or needle in normalise(material.search_aliases)
    ]
    return hits[:SEARCH_LIMIT], len(hits)


# --------------------------------------------------------------------- screens

# ================================================================= the launchpad
#
# >>> ANCHOR: LAUNCHPAD <<<
# The home screen, and the only screen that is about the system rather than
# about a job.
#
# ⚠ THIS TOOK "/" AND THE PROJECT LIST MOVED TO "/projects/".
#   Saahil's instruction was a launchpad "so the admin sees 4-5 tiles … it gives
#   a view to the user holistically". A launchpad you have to find from a header
#   link is a launchpad nobody opens, so it has to be what the address gives you.
#
#   The cost, recorded: anybody with "/" bookmarked now lands one click away
#   from the project list. That is the whole cost, and it is paid once.


def launchpad(request):
    """
    The tiles. Every decision about which tiles and what they say lives in
    hub.py — this view exists only to hand them to a template.

    ⚠ THE ROLE IS PASSED NOW, AND THAT IS THE WHOLE OF THE CHANGE. The comment
      that used to sit here promised "this becomes tiles_for(request.user.role)
      and nothing else on this screen changes." It did, and nothing did.

    ⚠ NO @requires. Everybody who is signed in has a launchpad; what differs is
      how many tiles are on it. A role with nothing to open would see an empty
      one — which is honest, and is exactly what a Compliance user sees until
      their module is built.
    """
    role = role_of(request.user)
    tiles = hub.tiles_for(role)
    from projects.home import home_for
    return render(request, "projects/launchpad.html", {
        "tiles": tiles,
        "home": home_for(role, request.user),
        # ⚠ The standing note about greyed tiles disappears when there are none.
        #   Both modules that sat greyed have been built; a note explaining an
        #   absent thing is exactly the kind of yellow box that trains people to
        #   stop reading yellow boxes.
        "anything_coming": any(not tile["live"] for tile in tiles),
    })


@requires("masters.view")
def master_data(request):
    """
    The second level behind the Master data tile — what Admin holds, and what
    already has a screen of its own.

    ⚠ Company profile and Company rates are HERE and no longer in the header.
      Saahil: "Have Company Data under master data itself."
    """
    entries = hub.master_data_for(role_of(request.user))
    return render(request, "projects/master_data.html", {"entries": entries})


@requires("projects.view")
def project_list(request):
    """
    Every project, with enough on each row to know what state it is in.

    ⚠ THE DEFAULT VIEW IS "ONGOING", NOT EVERYTHING.
    A project can never be deleted once anything has been delivered — a receipt
    protects its PO line, which protects the order, which protects the project.
    So the list would otherwise grow forever and the jobs that matter today
    would be buried among jobs finished three years ago.

    Nothing is hidden and nothing is destroyed: every filter is on screen with
    its own count, so a project that is not in view is visibly somewhere else
    rather than mysteriously gone. That is the whole difference between
    filtering and deleting.
    """
    counts = {
        "ongoing": Project.objects.filter(status__in=Project.ONGOING).count(),
        "completed": Project.objects.filter(status=Project.Status.COMPLETED).count(),
        "lost": Project.objects.filter(status=Project.Status.LOST).count(),
    }
    counts["all"] = sum(counts.values())

    show = request.GET.get("show", "ongoing")
    if show == "completed":
        projects = Project.objects.filter(status=Project.Status.COMPLETED)
    elif show == "lost":
        projects = Project.objects.filter(status=Project.Status.LOST)
    elif show == "all":
        projects = Project.objects.all()
    else:
        show = "ongoing"                        # anything unrecognised falls back
        projects = Project.objects.filter(status__in=Project.ONGOING)

    # ⚠ TWO GROUPED COUNTS, NOT TWO QUERIES PER ROW.
    #   This loop used to call bom.lines.count() and project.purchase_orders
    #   .count() on every project, which measured 69 queries for 13 projects and
    #   would have been over 500 at a hundred. Found by building a volume estate
    #   and looking, not by reading — the screen was perfectly fast on the four
    #   projects anybody had.
    #
    #   ⚠ distinct=True IS LOAD-BEARING. Two Counts across two different joins in
    #   one query multiply each other's rows; without it a project with 400 BOM
    #   lines and 3 orders reports 1,200 lines.
    #   ⚠ AND THE TEMPLATE ASKED TOO. It printed `row.estimate.lines.count`
    #   twice per row — once for the number, once for the pluralisation — which
    #   was 26 more queries on top of a select for each estimate's lines.
    #
    # ⚠⚠ THREE SEPARATE GROUPED COUNTS, NOT THREE ANNOTATIONS ON ONE QUERY.
    #   Annotating all three with Count(..., distinct=True) got this to 17
    #   queries and made it FIVE TIMES SLOWER — 598ms against 37 — because three
    #   Counts across three joins build a cartesian product, and a project with
    #   6,400 BOM lines multiplies it by every estimate line and every order.
    #   distinct=True keeps the answer right and the intermediate result
    #   enormous.
    #
    #   Fewer queries is not the same as faster, and the only way to know which
    #   you have is to measure both.
    #   ⚠ AND prefetch estimate__lines, because the template prints
    #   `estimate.composite_rate` — a property that sums that estimate's lines.
    #   Without it that is one more query per row, which is how a screen ends up
    #   at 69 queries while every individual piece of it looks reasonable.
    projects = list(projects.select_related("estimate", "bom")
                    .prefetch_related("estimate__lines"))
    ids = [p.id for p in projects]
    lines = dict(BomLine.objects.filter(bom__project_id__in=ids)
                 .values_list("bom__project_id").annotate(n=Count("id")))
    orders = dict(PurchaseOrder.objects.filter(project_id__in=ids)
                  .values_list("project_id").annotate(n=Count("id")))
    activities = dict(EstimateLine.objects.filter(estimate__project_id__in=ids)
                      .values_list("estimate__project_id").annotate(n=Count("id")))

    rows = []
    for project in projects:
        rows.append({
            "project": project,
            "estimate": getattr(project, "estimate", None),
            "bom": getattr(project, "bom", None),
            "line_count": lines.get(project.id, 0),
            "po_count": orders.get(project.id, 0),
            "activity_count": activities.get(project.id, 0),
        })

    filters = [
        ("ongoing", "Ongoing", counts["ongoing"], "Draft, Quoted and Won — everything still live"),
        ("completed", "Completed", counts["completed"], "Finished. Kept in full, just out of the way"),
        ("lost", "Lost", counts["lost"], "Quoted and not won"),
        ("all", "All projects", counts["all"], "Everything, including finished and lost"),
    ]
    return render(request, "projects/project_list.html",
                  {"rows": rows, "filters": filters, "show": show, "counts": counts})


@requires("bom.view")
def bom_screen(request, project_id):
    """
    The grid. One tab per activity, one row per material, every figure from
    bom_calc.

    ⚠ QUERY COUNT. Approved, in-draft and received are summed from the purchase
    orders for each line, which is three queries per row — the deliberate price
    of the BOM storing no second copy of them (see bom_models.py). At the sizes
    seen so far that is not noticeable. It has NOT been measured against a
    project with hundreds of lines, and it is the first thing to look at if the
    screen ever feels slow.
    """
    project = get_object_or_404(Project, pk=project_id)
    bom = getattr(project, "bom", None)
    if bom is None:
        return render(request, "projects/bom_missing.html", {
            "project": project,
            "estimate": getattr(project, "estimate", None),
        })

    activities = _tab_activities(bom)
    activity = _activity_for(bom, request.GET.get("activity"))

    totals, rows, conflicts = None, [], []
    if activity is not None:
        # activity_totals already worked out every row on its way to the totals.
        # Reading them back is what guarantees the footer agrees with the column
        # above it — they are literally the same numbers, not two calculations
        # that happen to match.
        totals = bom_calc.activity_totals(bom, activity)
        rows = totals["figures"]

        # >>> ANCHOR: DRAFT-CONFLICT <<<
        # Drafts that no longer agree with the plan behind them. Worked out
        # fresh on every load rather than remembered from the moment somebody
        # changed something — a warning that only fires on one code path is a
        # warning that will be walked around.
        found = bom_calc.bulk_draft_conflicts(totals["lines"])
        by_id = {line.id: line for line in totals["lines"]}
        conflicts = [{"line": by_id[line_id], **detail}
                     for line_id, detail in sorted(found.items())]

        # Hang each conflict on its own row as well, so a flag appears against
        # the material rather than only in a block at the top. At three to four
        # hundred lines an activity, a paragraph per conflict would bury the
        # grid it is trying to warn about — the same "design for the real size"
        # rule that governs the queries.
        for row in rows:
            row["conflict"] = found.get(row["line"].id)

        # ⚠ THE SAME MATERIAL HOLDING STOCK ON MORE THAN ONE LINE.
        #   Not a bug and not blocked: per-line stock is an allocation, so two
        #   lines of 100 mean 200 bags split between two trades. But it is
        #   indistinguishable from one pile of 100 typed twice, and only the
        #   person knows which they meant. So the flag says where else the
        #   material carries stock and what it adds up to, and leaves it to them.
        echoes = bom_calc.bulk_stock_echoes(totals["lines"])
        for row in rows:
            row["stock_echo"] = echoes.get(row["line"].id)

    # Each tab carries its own line count, so you can see where the work is
    # without opening every one of them.
    #
    # Counted in ONE grouped query rather than one per tab. With all 18
    # activities in use that was 18 queries before the grid had even started —
    # measured, not guessed.
    counts = dict(bom.lines.values_list("activity_id").annotate(n=Count("id")))
    tabs = [{"activity": a,
             "count": counts.get(a.id, 0),
             "is_open": activity is not None and a.id == activity.id}
            for a in activities]

    # Just how many drafts are outstanding, for a link in the toolbar. The list
    # of them lives on the purchase-order screen now — the stand-in panel that
    # used to be here has gone, because two screens listing the same drafts would
    # eventually disagree about them.
    #
    # ⚠ A COUNT, NOT A CALCULATION. Working out what discarding each draft would
    # do costs about as much as drawing the grid itself, and almost nobody who
    # opens this page is about to discard anything. Measured: 137 queries with
    # that here, 35 without.
    draft_count = project.purchase_orders.filter(status=PurchaseOrder.Status.DRAFT).count()

    scope = request.GET.get("scope", "activity")
    query = request.GET.get("q", "")
    group_code = request.GET.get("group", "")
    hits, hit_count = _search_materials(activity, query, group_code, scope)
    on_sheet = set(bom.lines.filter(activity=activity).values_list("material_id", flat=True)) if activity else set()

    return render(request, "projects/bom.html", {
        "project": project,
        "bom": bom,
        "tabs": tabs,
        "draft_count": draft_count,
        "conflicts": conflicts,
        "activity": activity,
        "totals": totals,
        "rows": rows,
        "vendors": Vendor.objects.filter(is_active=True).order_by("code"),
        "groups": MaterialGroup.objects.all().order_by("code"),
        "hits": hits,
        "hit_count": hit_count,
        "on_sheet": on_sheet,
        "query": query,
        "group_code": group_code,
        "scope": scope,
        "search_limit": SEARCH_LIMIT,
        # >>> ANCHOR: BOM-STOCK-ONLY <<<
        # ⚠ TWO SEPARATE ANSWERS, because a site engineer holds the second and
        #   not the first. `may_edit` decides whether the row is typeable at
        #   all; `may_stock` decides the two stock cells on their own. The
        #   template only HIDES on these — the refusal that counts is in
        #   _apply_edits, field by field.
        "may_edit": perms.can(request.user, "bom.edit"),
        "may_stock": perms.can(request.user, "bom.stock"),
    })


# ======================================================== the stock-only screen
#
# >>> ANCHOR: BOM-STOCK-ONLY <<<
# What a site engineer sees instead of the bill of materials.
#
# ⚠⚠ THIS SCREEN EXISTS BECAUSE THE FIRST ANSWER WAS WRONG. Saahil asked for the
#   engineer to maintain stock on the BOM. Doing that literally meant giving
#   them `bom.view` — the whole buying grid, read-only: order quantities,
#   vendors, vendor rates, PO values, variance. That was put to him and he chose
#   the narrower screen: "your suggestion of having only a BOM stock view is
#   good."
#
# ⚠ SO THERE IS NO MONEY ON THIS PAGE AT ALL. Not greyed, not read-only — not
#   fetched. Code, material, unit, stock, threshold and the low flag.
#
# ⚠ IT SHARES `_apply_edits` WITH THE BOM, and that is deliberate: two save
#   paths writing the same two columns would eventually disagree about what a
#   blank means. The field-by-field permission check inside it is what makes
#   this screen safe rather than merely narrow — a template hides nothing from a
#   stale page or a crafted POST.


@requires("bom.stock")
def stock_screen(request, project_id):
    """
    Site stock, one construction activity at a time.

    ⚠ EVERY LINE IS LISTED, INCLUDING THE ONES THAT HOLD NO STOCK. A screen that
      showed only what is on site cannot be used to record what has just
      arrived, which is the whole job.
    """
    project = get_object_or_404(Project, pk=project_id)
    bom = getattr(project, "bom", None)
    if bom is None:
        return render(request, "projects/bom_missing.html", {
            "project": project,
            "estimate": getattr(project, "estimate", None),
        })

    activities = _tab_activities(bom)
    activity = _activity_for(bom, request.GET.get("activity"))

    rows, low = [], 0
    if activity is not None:
        # ⚠ NOT bom_calc.figures_for. That asks the database for approved,
        #   in-draft and received quantities and for committed money — three
        #   questions per line, for figures this screen does not print. The two
        #   columns here are on the line itself.
        lines = (bom.lines.filter(activity=activity)
                 .select_related("material", "material__group")
                 .order_by("sort_order", "id"))
        for line in lines:
            below = bom_calc.is_below_threshold(line)
            low += 1 if below else 0
            rows.append({
                "line": line,
                "stocked": line.material.group.is_stock_item,
                "below_threshold": below,
            })

    # ⚠ ONE GROUPED QUERY, not one per tab — the same measured decision as the
    #   BOM screen above. Eighteen activities meant eighteen queries before the
    #   page had started drawing.
    counts = dict(bom.lines.values_list("activity_id").annotate(n=Count("id")))
    tabs = [{"activity": a, "count": counts.get(a.id, 0),
             "is_open": activity is not None and a.id == activity.id}
            for a in activities]

    return render(request, "projects/stock.html", {
        "project": project,
        "bom": bom,
        "tabs": tabs,
        "activity": activity,
        "rows": rows,
        "low": low,
    })


@require_POST
@requires("bom.stock")
def stock_save(request, project_id):
    """
    Save the stock figures and come back to the same tab.

    ⚠ THE SAME `_apply_edits` THE BOM USES. It writes stock and the threshold and
      refuses everything else for somebody holding only `bom.stock`, so this view
      adds no rule of its own — it only decides where to return to. A second
      implementation is how the two screens would start disagreeing about what a
      blank cell means.
    """
    project = get_object_or_404(Project, pk=project_id)
    bom = get_object_or_404(Bom, project=project)
    activity = _activity_for(bom, request.POST.get("activity"))

    saved, problems = _apply_edits(request, bom, activity)
    if saved:
        messages.success(request, f"Stock updated on {saved} line{'' if saved == 1 else 's'}.")
    else:
        messages.info(request, "Nothing had changed, so nothing was saved.")
    for problem in problems:
        messages.warning(request, problem)

    url = reverse("stock_screen", args=[project.id])
    return redirect(f"{url}?activity={activity.abbreviation}" if activity else url)


# --------------------------------------------------------------------- actions

def _back(project, activity):
    """Return to the tab you were on, so saving does not lose your place."""
    url = reverse("bom_screen", args=[project.id])
    return redirect(f"{url}?activity={activity.abbreviation}" if activity else url)


def _apply_edits(request, bom, activity):
    """
    Write back the columns a human types: planned, stock, threshold, the order
    override, vendor, vendor rate, the planning rate and remark.

    ⚠ CALLED BY EVERY BUTTON ON THE GRID, not just Save.
    The whole grid is one HTML form, so pressing Post POs or removing a line
    submits what you have typed along with it. If only Save read those values,
    typing 40 into Order Qty and pressing Post POs would silently post the OLD
    number — the screen would say one thing and the purchase order another.
    So: every button saves first, then does its own job.

    Rows on other tabs are untouched, because they were not on the page.

    ⚠ NOTHING ELSE IS WRITTEN. Approved, in draft and received are not stored on
    a BOM line at all; they are summed from the purchase orders. There is
    nothing here to keep in step with anything.

    Returns (rows actually changed, list of problems phrased for the user).

    Only rows whose values really moved are written. A page with fifty rows on
    it posts fifty rows every time, and saying "saved 50 lines" when one cell
    was touched trains people to stop reading the message.

    >>> ANCHOR: BOM-STOCK-ONLY <<<
    ⚠⚠ SOMEBODY HOLDING ONLY `bom.stock` WRITES STOCK AND THE THRESHOLD, AND
       NOTHING ELSE. Saahil put the site engineer on this screen to keep the
       stock figure honest — "they are not allowed to change anything else or
       place an order, but they can just maintain the stock".

       The refusal is HERE, on the server, not in the template. The grid is one
       form and every button posts the whole of it, so a hidden input is not a
       permission — it is a suggestion. A crafted POST, or a stale page rendered
       before somebody's role changed, would otherwise walk straight through.

    ⚠ STOCK IS LOAD-BEARING, NOT A NOTE. `suggested_order_qty` subtracts it, so
      this is a person changing what the system advises buying. That is the
      point of letting them do it, and the reason it is a named key rather than
      a relaxation of bom.edit.
    """
    problems, changed_rows = [], 0

    # ⚠ TWO SEPARATE QUESTIONS, NOT A LADDER. Somebody may hold bom.stock and
    #   not bom.edit (the site engineer), or bom.edit and not bom.stock (nobody
    #   today, and the code does not assume it stays that way).
    may_edit = perms.can(request.user, "bom.edit")
    may_stock = perms.can(request.user, "bom.stock")
    STOCK_FIELDS = {"stock_qty", "min_qty"}

    def permitted(field):
        if field in STOCK_FIELDS:
            return may_stock or may_edit
        return may_edit

    for line in bom.lines.filter(activity=activity).select_related("material", "vendor"):
        label = line.material.code
        changed = []

        def apply(field, value):
            """
            Set the field only if it is different, and remember that it was.

            ⚠ AND ONLY IF THIS PERSON MAY WRITE IT — see BOM-STOCK-ONLY. A field
              they may not touch is dropped silently rather than reported: they
              never saw the input, so a message about it would describe a screen
              they were not looking at.
            """
            if not permitted(field):
                return
            if getattr(line, field) != value:
                setattr(line, field, value)
                changed.append(field)

        for field, column, caption in (("planned_qty", "plan", "planned quantity"),
                                       ("stock_qty", "stock", "stock"),
                                       ("min_qty", "min", "threshold")):
            key = f"{column}-{line.id}"
            if key not in request.POST:
                continue
            value = _decimal_or_error(request.POST.get(key), f"{caption} on {label}", problems)
            if value != "skip":
                apply(field, value)

        if f"ord-{line.id}" in request.POST:
            # Blank is meaningful here: it means "no override, use the
            # suggestion", which is not the same as ordering zero.
            value = _decimal_or_error(request.POST.get(f"ord-{line.id}"),
                                      f"order quantity on {label}", problems, allow_blank=True)
            if value != "skip":
                apply("order_qty_override", value)

        if f"vrate-{line.id}" in request.POST:
            raw = (request.POST.get(f"vrate-{line.id}") or "").strip()
            if raw == "":
                apply("vendor_rate", None)              # falls back to the planning rate
            else:
                value = _decimal_or_error(raw, f"vendor rate on {label}", problems)
                if value != "skip":
                    apply("vendor_rate", value)

        # The planning rate. Blank is meaningful and is NOT zero: it means "no
        # override, use the material master's estimation rate", which is what
        # every line did before this column existed. Same shape as vendor_rate
        # above, for the same reason.
        if f"prate-{line.id}" in request.POST:
            raw = (request.POST.get(f"prate-{line.id}") or "").strip()
            if raw == "":
                apply("planned_rate", None)
            else:
                value = _decimal_or_error(raw, f"plan rate on {label}", problems)
                if value != "skip":
                    apply("planned_rate", value)

        if f"vendor-{line.id}" in request.POST:
            vendor = _resolve_vendor(request.POST.get(f"vendor-{line.id}"), problems, label)
            if vendor != "skip":
                apply("vendor", vendor)

        if f"remark-{line.id}" in request.POST:
            apply("remark", (request.POST.get(f"remark-{line.id}") or "").strip()[:200])

        if changed:
            line.save(update_fields=changed + ["updated_at"])
            changed_rows += 1

    return changed_rows, problems


@require_POST
# ⚠ EITHER KEY OPENS THE DOOR; _apply_edits decides what actually gets written.
#   A site engineer holds bom.stock only, and their POST carries the whole grid
#   because the grid is one form. See ANCHOR: BOM-STOCK-ONLY.
@requires_any("bom.edit", "bom.stock")
def bom_save(request, project_id):
    """The Save button. Writes what was typed and comes straight back."""
    project = get_object_or_404(Project, pk=project_id)
    bom = get_object_or_404(Bom, project=project)
    activity = _activity_for(bom, request.POST.get("activity"))

    saved, problems = _apply_edits(request, bom, activity)
    if saved:
        messages.success(request, f"Saved {saved} line{'' if saved == 1 else 's'} on {activity.name}. "
                                  f"No purchase orders were raised — use Post POs for that.")
    else:
        messages.info(request, "Nothing had changed, so nothing was saved.")
    for problem in problems:
        messages.warning(request, problem)

    return _back(project, activity)


@require_POST
@requires("bom.edit")
def bom_add_lines(request, project_id):
    """
    Put the ticked materials onto the activity whose tab is open.

    They arrive with everything blank and ready to type. Adding a material that
    is already on the activity is ALLOWED — cement legitimately appears twice
    under RCC, "footing & plinth" and "slab pour 2" — so this warns and adds
    rather than refusing. The remark column is what tells them apart.
    """
    project = get_object_or_404(Project, pk=project_id)
    bom = get_object_or_404(Bom, project=project)
    activity = _activity_for(bom, request.POST.get("activity"))
    if activity is None:
        messages.error(request, "Pick an activity first.")
        return _back(project, activity)

    ids = request.POST.getlist("material")
    if not ids:
        messages.info(request, "Nothing was ticked, so nothing was added.")
        return _back(project, activity)

    existing = set(bom.lines.filter(activity=activity).values_list("material_id", flat=True))
    added, repeats = 0, []
    last = bom.lines.filter(activity=activity).count()

    for material in Material.objects.filter(id__in=ids, is_active=True):
        last += 1
        BomLine.objects.create(bom=bom, activity=activity, material=material, sort_order=last)
        added += 1
        if material.id in existing:
            repeats.append(material.code)

    messages.success(request, f"Added {added} material{'' if added == 1 else 's'} to {activity.name}. "
                              f"Type quantities, then Save.")
    if repeats:
        messages.warning(request, f"{', '.join(repeats)} was already on this activity and is now on it "
                                  f"twice. That is allowed — use the Remark column to say which is which.")
    return _back(project, activity)


@require_POST
@requires("bom.edit")
def bom_remove_line(request, project_id, line_id):
    """
    Take a material off the BOM.

    The delete rule, same as everywhere else: nothing references it, so it goes.
    A line that is already on a purchase order does NOT go — the order is a
    record of something that was actually bought, and the line is what it points
    at. Blocked with the reason, never silently.
    """
    project = get_object_or_404(Project, pk=project_id)
    bom = get_object_or_404(Bom, project=project)
    line = get_object_or_404(BomLine, pk=line_id, bom=bom)
    activity = line.activity

    # The remove button is inside the grid form, so anything typed elsewhere on
    # the page came with it. Save that first — losing an hour of typing because
    # you deleted one row would be an unpleasant surprise.
    _, problems = _apply_edits(request, bom, activity)
    for problem in problems:
        messages.warning(request, problem)
    line.refresh_from_db()

    orders = sorted({po_line.purchase_order.number for po_line in line.po_lines.select_related("purchase_order")})
    if orders:
        messages.error(request, f"{line.material.code} cannot be removed — it is on "
                                f"{', '.join(orders)}. Delete the draft order first, or leave the line "
                                f"in place: it is what those orders point at.")
    else:
        code = line.material.code
        line.delete()
        messages.success(request, f"{code} removed from {activity.name}.")
    return _back(project, activity)


@require_POST
@requires("bom.post")
def bom_post_pos(request, project_id):
    """
    The Post POs button. Saves what was typed, then shows the preview.

    ⚠ IT NO LONGER CREATES ANYTHING. Saahil's call, 9 Aug 2026: at sixteen
    activities of three to four hundred materials, a button that silently
    creates a dozen documents is not a button anyone should trust. So this
    behaves like SAP's Check — work everything out, show it, decide.
    """
    project = get_object_or_404(Project, pk=project_id)
    bom = get_object_or_404(Bom, project=project)
    activity = _activity_for(bom, request.POST.get("activity"))

    saved, problems = _apply_edits(request, bom, activity)
    for problem in problems:
        messages.warning(request, problem)
    if saved:
        messages.info(request, f"{saved} edited line{'' if saved == 1 else 's'} saved.")

    url = reverse("po_preview", args=[project.id])
    return redirect(f"{url}?activity={activity.abbreviation}" if activity else url)


@requires("bom.post")
def po_preview(request, project_id):
    """
    Everything that would be created, before anything is.

    >>> ANCHOR: PO-PREVIEW <<<
    ⚠ COVERS THE WHOLE BOM, NOT THE OPEN TAB. One vendor supplies several
    trades — Sambhav Hardware sells cement, wire and window sections — and that
    is one order, one delivery, one bill. Previewing per tab would split it into
    three. The tick boxes are how you narrow it instead.

    Writes nothing. Everything on this page is worked out fresh each time it
    loads, so it cannot show a stale plan.
    """
    project = get_object_or_404(Project, pk=project_id)
    bom = get_object_or_404(Bom, project=project)
    activity = _activity_for(bom, request.GET.get("activity"))

    groups, skipped = po_service.preview_purchase_orders(bom)
    return render(request, "projects/po_preview.html", {
        "project": project,
        "activity": activity,
        "groups": groups,
        "skipped": skipped,
        "line_count": sum(len(group["lines"]) for group in groups),
        "grand_total": sum((group["total"] for group in groups), ZERO),
        "any_blocked": any(group["blocked"] for group in groups),
    })


@require_POST
@requires("bom.post")
def po_create(request, project_id):
    """
    Create the purchase orders that were ticked on the preview. The only place
    an order comes into existence.
    """
    project = get_object_or_404(Project, pk=project_id)
    bom = get_object_or_404(Bom, project=project)
    activity = _activity_for(bom, request.POST.get("activity"))

    ticked = {int(value) for value in request.POST.getlist("vendor") if value.isdigit()}
    if not ticked:
        messages.info(request, "No vendors were ticked, so nothing was created.")
        return redirect(f"{reverse('po_preview', args=[project.id])}"
                        f"?activity={activity.abbreviation if activity else ''}")

    try:
        orders = po_service.generate_purchase_orders(
            bom, user=request.user if request.user.is_authenticated else None,
            vendor_ids=ticked)
    except po_service.POError as refusal:
        # >>> ANCHOR: DISCONTINUED-BLOCK <<<
        # Nothing was raised, and the message names every line to fix. POError
        # messages are already written for the person reading them.
        messages.error(request, str(refusal))
        return redirect(f"{reverse('po_preview', args=[project.id])}"
                        f"?activity={activity.abbreviation if activity else ''}")

    if not orders:
        messages.info(request, "Nothing to create — those vendors have no typed quantities.")
    else:
        listed = ", ".join(f"{o.number} · {o.vendor.name}" for o in orders)
        messages.success(request, f"{len(orders)} purchase order{'' if len(orders) == 1 else 's'} "
                                  f"created: {listed}. The order quantities have been used up, so "
                                  f"the boxes are empty again — nothing can be ordered twice by "
                                  f"pressing the button again.")
    return _back(project, activity)


@requires("po.discard")
def po_discard_confirm(request, project_id, po_id):
    """
    The warning before a draft is thrown away — with figures, not "are you sure?".

    ⚠ THIS PAGE IS THE POINT OF THE WHOLE FEATURE. Discarding is safe, because
    the quantity was only ever recorded on these PO lines. But it is not
    invisible: those quantities come straight back under To Order, and the
    activity's PO-value-now goes up by exactly that much. Saahil asked for the
    warning to name the figure that moves.

    A page rather than a browser confirm() box, for two reasons: the numbers fit
    and can be read properly, and the calculation only happens for the person
    who actually clicked Discard rather than for everyone who opens the BOM.
    """
    project = get_object_or_404(Project, pk=project_id)
    order = get_object_or_404(PurchaseOrder, pk=po_id, project=project)
    return render(request, "projects/po_discard_confirm.html", {
        "project": project,
        "order": order,
        "activity": request.GET.get("activity", ""),
        "effects": bom_calc.discard_effect(order) if order.is_editable else [],
        "basic": sum((line.basic for line in order.lines.all()), ZERO),
    })


@require_POST
@requires("po.discard")
def po_discard(request, project_id, po_id):
    """
    Throw away the draft, then say what that actually changed.

    The effect is worked out BEFORE the delete, because afterwards the order is
    gone and there is nothing left to describe. It is calculated again here
    rather than trusted from the confirmation page: a figure posted back from a
    browser is a figure someone could have edited, and in the seconds between
    the two pages somebody else may have changed the BOM.
    """
    project = get_object_or_404(Project, pk=project_id)
    order = get_object_or_404(PurchaseOrder, pk=po_id, project=project)
    activity = _activity_for(getattr(project, "bom", None), request.POST.get("activity")) \
        if hasattr(project, "bom") else None

    effects = bom_calc.discard_effect(order)
    try:
        number = po_service.delete_draft(order)
    except po_service.POError as refusal:
        messages.error(request, str(refusal))
        return _back(project, activity)

    # Same digit grouping as the screens — ₹6,00,000, not ₹600,000.
    from .templatetags.inr import qty as fmt_qty, rupees

    lines = []
    for effect in effects:
        returned = ", ".join(
            f"{item['line'].material.code} {fmt_qty(item['returning'])} "
            f"{item['line'].material.uom} (still to buy "
            f"{fmt_qty(item['still_to_buy_before'])} → {fmt_qty(item['still_to_buy_after'])})"
            for item in effect["lines"])
        lines.append(f"    {effect['activity'].name}: {returned}"
                     f"\n        ₹{rupees(effect['value_cancelled'])} of draft orders cancelled")
    messages.warning(request, f"{number} discarded. Nothing is on order for these materials now:\n"
                              + "\n".join(lines)
                              + "\n    They are back under 'still to buy'. Type a quantity again "
                                "if you want to re-order them — nothing is ordered automatically."
                              + "\n    Planned, approved and received are untouched.")
    return _back(project, activity)


# ============================================================ purchase orders
#
# >>> ANCHOR: PO-SCREEN <<<
# The three-level drill-down from BOM_Prototype.html, which IS the agreed
# design: Vendors -> that vendor's documents -> one document.
#
# VENDOR-FIRST, not a flat list of orders. Saahil's call, over the recommended
# flat list, and the reason is how the work actually happens: you deal with a
# vendor, not with a document number. Everything owed to Sambhav Hardware sits
# in one place, whether it is one order or nine.
#
# PER PROJECT. These live under /projects/<id>/ like the BOM, because a project
# is what somebody is working on. "What have we ever bought from this vendor,
# across every project?" is a real question and a different screen; it is not
# this one.
#
# ⚠ EVERY MONEY FIGURE COMES FROM PurchaseOrder.totals(). Not from a sum written
#   here, and not from the database adding it up. The same function draws the
#   list, the detail screen and the PDF, so a vendor's row can never disagree
#   with the order you open from it — which is exactly the class of bug that
#   made bom_calc a single file in the first place.

# ⚠ NOT A STATUS AND DELIBERATELY NOT ONE. See the note in _visible_orders: this
#   is a saved question — approved or delivered, and not yet paid. Kept as a
#   constant so the view and the template cannot disagree about the spelling.
UNPAID = "unpaid"


def _visible_orders(project, request):
    """
    This project's documents, narrowed by whatever the person filtered on.

    Three filters, all optional and all combinable: document type, activity, and
    a text search. The search covers vendor code, vendor name, vendor category
    and the document number — the four things somebody actually knows when they
    go looking, agreed with Saahil and lifted from the prototype.

    ⚠ `lines` IS PREFETCHED AND MUST STAY THAT WAY. totals() walks them, so
      without this the screen asks the database once per order — the shape that
      cost nine seconds on the BOM before it was fixed. Prefetched, it is two
      queries whether there are three orders or three hundred.
    """
    # ⚠ `vendor__categories` IS NOT OPTIONAL, and it is not obvious.
    #   The vendor list prints each supplier's trade categories, which reads
    #   vendor.categories.all() once per row. Measured on stress data: 5 vendors
    #   cost 10 queries, 20 cost 25, 50 cost 55 — one per vendor, climbing
    #   forever. Exactly the shape of bugs 9 and 10, and invisible on the two
    #   vendors a test fixture has.
    orders = (project.purchase_orders
              .select_related("vendor")
              .prefetch_related("lines", "vendor__categories")
              .order_by("-raised_on", "-id"))

    doc_type = request.GET.get("type", "")
    if doc_type in DocumentType.values:
        orders = orders.filter(document_type=doc_type)

    # >>> ANCHOR: PO-STATUS-FILTER <<<
    # ⚠ THE CROSS-PROJECT REGISTER ALREADY HAD THIS; THESE TWO SCREENS DID NOT.
    #   Saahil: "when I open the PO, it showed a lot of drafts, approved, paid…
    #   there should be an option for the user to filter the PO based on the
    #   status." He was on the per-project screen, where the only filters were
    #   type, activity and a search box.
    #
    # ⚠ "unpaid" IS NOT A STATUS, it is a QUESTION — everything that has been
    #   committed and not yet settled. It is the one people actually ask, and
    #   expressing it as a status would have meant inventing a sixth state that
    #   the document does not have.
    status = (request.GET.get("status") or "").strip()
    if status == UNPAID:
        orders = orders.filter(status__in=[PurchaseOrder.Status.APPROVED,
                                           PurchaseOrder.Status.DELIVERED])
    elif status in PurchaseOrder.Status.values:
        orders = orders.filter(status=status)
    else:
        status = ""

    # Free, because every line already carries the BOM line it came from, and
    # that carries the activity. No new field, no mapping table.
    activity = request.GET.get("activity", "")
    if activity:
        orders = orders.filter(lines__bom_line__activity__abbreviation=activity).distinct()

    query = (request.GET.get("q") or "").strip()
    if query:
        orders = orders.filter(
            Q(vendor__code__icontains=query)
            | Q(vendor__name__icontains=query)
            | Q(vendor__categories__category__icontains=query)
            | Q(number__icontains=query)
        ).distinct()

    return orders, {"type": doc_type, "activity": activity, "q": query, "status": status}


def _filter_options(project):
    """The activities and document types actually present, so no filter is empty."""
    activities = (Activity.objects
                  .filter(bom_lines__po_lines__purchase_order__project=project)
                  .distinct().order_by("sort_order", "name"))
    types = set(project.purchase_orders.values_list("document_type", flat=True))
    return activities, types


def _status_options(project):
    """
    The statuses this project's documents are actually in, plus the unpaid
    shortcut when there is anything for it to find.

    ⚠ AN EMPTY FILTER OPTION IS A PROMISE THE SCREEN CANNOT KEEP — the same rule
      the register's dropdowns already follow.
    """
    present = set(project.purchase_orders.values_list("status", flat=True))
    options = [(value, label) for value, label in PurchaseOrder.Status.choices
               if value in present]
    if present & {PurchaseOrder.Status.APPROVED, PurchaseOrder.Status.DELIVERED}:
        options.append((UNPAID, "Not paid yet"))
    return options


@requires("po.view")
def po_screen(request, project_id):
    """
    LEVEL 1 — the vendors this project has ordered from.

    One row per vendor: how many documents, how many still draft, and what they
    add up to. The GSTIN is shown here rather than buried, because a missing one
    blocks approval and is better discovered before somebody tries.
    """
    project = get_object_or_404(Project, pk=project_id)
    orders, applied = _visible_orders(project, request)

    grouped = {}
    for order in orders:
        row = grouped.setdefault(order.vendor_id, {
            "vendor": order.vendor,
            "orders": 0,
            "drafts": 0,
            "awaiting": 0,
            "value": ZERO,
        })
        totals = order.totals()
        row["orders"] += 1
        row["value"] += totals["order_value"]
        if order.status == PurchaseOrder.Status.DRAFT:
            row["drafts"] += 1
        elif order.status == PurchaseOrder.Status.APPROVED:
            row["awaiting"] += 1

    rows = sorted(grouped.values(), key=lambda r: r["vendor"].code)
    activities, types = _filter_options(project)

    return render(request, "projects/po_vendors.html", {
        "project": project,
        "rows": rows,
        "applied": applied,
        "activities": activities,
        "types": types,
        "statuses": _status_options(project),
        "order_count": sum(r["orders"] for r in rows),
        "draft_count": sum(r["drafts"] for r in rows),
        "total_value": sum((r["value"] for r in rows), ZERO),
    })


@requires("po.view")
def po_vendor(request, project_id, vendor_id):
    """
    LEVEL 2 — every document this project has raised to one vendor.

    The same filters stay applied, so narrowing to Work Orders on level 1 and
    then opening a vendor shows their work orders, not everything.
    """
    project = get_object_or_404(Project, pk=project_id)
    vendor = get_object_or_404(Vendor, pk=vendor_id)
    orders, applied = _visible_orders(project, request)

    rows = [{"order": order, "totals": order.totals()}
            for order in orders.filter(vendor=vendor)]
    activities, types = _filter_options(project)

    return render(request, "projects/po_vendor.html", {
        "project": project,
        "vendor": vendor,
        "rows": rows,
        "applied": applied,
        "activities": activities,
        "types": types,
        "statuses": _status_options(project),
        "total_value": sum((r["totals"]["order_value"] for r in rows), ZERO),
    })


@requires("po.view")
def po_detail(request, project_id, po_id):
    """
    LEVEL 3 — one document: its header, its lines, and the totals ladder.

    ⚠ THE ACTIVITY IS SHOWN ON EVERY LINE, and it is not decoration. One order
      spans activities — Sambhav Hardware supplies cement, wire and window
      sections, and that is one order, one delivery, one bill. Without the
      activity column nobody can tell why those three are on the same document.
    """
    project = get_object_or_404(Project, pk=project_id)
    order = get_object_or_404(
        PurchaseOrder.objects.select_related("vendor", "project"), pk=po_id, project=project)

    lines = list(order.lines
                 .select_related("bom_line__material", "bom_line__activity")
                 .order_by("bom_line__activity__sort_order", "id"))

    return render(request, "projects/po_detail.html", {
        "project": project,
        "order": order,
        "lines": lines,
        "totals": order.totals(),
        "company": CompanyProfile.get_solo(),
        # The order's own address once it has one; the project's site until then.
        # Approval freezes a copy onto the order, so an issued document never
        # follows the project around afterwards.
        "ship_to": order.delivery_address or project.site_address,
        # Gujarat vendor -> CGST + SGST, anyone else -> IGST. Derived silently
        # from the two GSTINs; there is no switch for it anywhere, and a Gujarat
        # vendor never sees an IGST row.
        "interstate": _is_interstate(order),
        "editable": order.is_editable,
        # >>> ANCHOR: PO-DOORWAY <<<
        # ⚠ WHICH DOOR SOMEBODY CAME THROUGH, and it changes what the screen
        #   offers. From the Purchase orders tile this is one document to
        #   review, so there are no project tabs and the crumb goes back to the
        #   register. From Projects → a project → Purchase orders the chain is
        #   the point and the tabs stay.
        #
        # ⚠ A QUERY PARAMETER, NOT THE REFERER. A referer is absent on a
        #   bookmark, stripped by some setups and trivially wrong; the link that
        #   sends you here says where you came from, and nothing else does.
        "standalone": request.GET.get("from") == "register",
    })


def _is_interstate(order):
    """
    Whether this order attracts IGST instead of CGST + SGST.

    ⚠ DO NOT DELETE THIS BRANCH because every current vendor is in Gujarat. It
      costs nothing to keep and it never shows unless it is genuinely correct.
      Without it an out-of-state purchase — Schindler and TKE are both in the
      vendor master, and lifts are a BOQ trade — would print CGST + SGST on an
      interstate supply. That is a real tax error, on a document already sent,
      that the vendor's own invoice would then contradict.
    """
    if order.vendor.is_unregistered:
        return False
    ours = CompanyProfile.get_solo().gst_number
    theirs = order.vendor_gstin or order.vendor.gst_number
    if not ours or not theirs:
        return False
    return ours[:2] != theirs[:2]


@require_POST
@requires("po.edit_draft")
def po_save(request, project_id, po_id):
    """
    Save everything typed on a draft document, in one pass.

    Same principle as the BOM grid: the page is one form, so whichever button is
    pressed, what was typed is written first and then that button does its own
    job. Otherwise Approve could commit yesterday's quantities while the screen
    showed today's.
    """
    project = get_object_or_404(Project, pk=project_id)
    order = get_object_or_404(PurchaseOrder, pk=po_id, project=project)
    saved, problems = _apply_po_edits(request, order)

    if problems:
        for problem in problems:
            messages.warning(request, problem)
    elif saved:
        messages.success(request, f"{order.number} saved. It is still a draft — nothing has been "
                                  f"sent to {order.vendor.name}.")
    else:
        messages.info(request, "Nothing had changed, so nothing was saved.")
    return redirect(reverse("po_detail", args=[project.id, order.id]))


def _apply_po_edits(request, order):
    """
    Write back the document and its lines. Returns (rows changed, problems).

    ⚠ EDITING A DRAFT MOVES THE BOM, and that is the point rather than a side
      effect. "In Draft" on a BOM line IS the sum of that material's draft lines,
      so cutting one from 300 to 200 puts 100 back under "still to buy" the
      moment this saves. Nothing has to be kept in step because nothing is
      stored twice.
    """
    if not order.is_editable:
        return 0, [f"{order.number} is {order.get_status_display()} and locked. "
                   f"Nothing on an approved document can be changed."]

    problems, changed = [], 0

    def number(key, caption, blank_ok=False):
        """Read one typed figure, or report it. Unreadable input never becomes 0."""
        if key not in request.POST:
            return None
        raw = (request.POST.get(key) or "").strip().replace(",", "")
        if raw == "":
            return ZERO if blank_ok else None
        try:
            return Decimal(raw)
        except (InvalidOperation, ValueError):
            problems.append(f"{caption} could not be read as a number, so it was left as it was.")
            return None

    for line in order.lines.select_related("bom_line__material"):
        label = line.bom_line.material.code
        fields = {}

        # >>> ANCHOR: LUMPSUM <<<
        # A typed VALUE fills in the quantity — Saahil's call, and it removes the
        # special case rather than creating one: after this the line is
        # qty x rate like every other, so no flag and no second formula.
        #
        # ⚠ The quantity is rounded to 3dp, so qty x rate will not come back to
        #   exactly what was typed. ₹50,000 at ₹1,854.91 gives 26.955 Trip and
        #   ₹49,999.10. The screen redisplays the real figure rather than the
        #   typed one, because a document that quietly disagrees with itself is
        #   worse than one that shows a ninety-paise difference.
        value = number(f"value-{line.id}", f"value on {label}")
        if value is not None and value > ZERO:
            rate = number(f"rate-{line.id}", f"rate on {label}") or line.rate
            if rate > ZERO:
                fields["quantity"] = (value / rate).quantize(Decimal("0.001"))

        if "quantity" not in fields:
            quantity = number(f"qty-{line.id}", f"quantity on {label}")
            if quantity is not None:
                fields["quantity"] = quantity

        for key, field, caption in (("rate", "rate", "rate"),
                                    ("gst", "gst_percent", "GST%"),
                                    ("disc", "discount_pct", "discount")):
            typed = number(f"{key}-{line.id}", f"{caption} on {label}", blank_ok=True)
            if typed is not None:
                fields[field] = typed

        if f"ref-{line.id}" in request.POST:
            fields["reference"] = (request.POST.get(f"ref-{line.id}") or "").strip()

        # Only write when something actually moved, so "saved 12 lines" never
        # appears because twelve rows were posted back unchanged.
        moved = {name: v for name, v in fields.items() if getattr(line, name) != v}
        if moved:
            try:
                po_service.update_draft_line(line, **moved)
                changed += 1
            except po_service.POError as refusal:
                problems.append(str(refusal))

    document = {}
    for key, field, caption in (("deduction", "deduction_pct", "deduction %"),
                                ("tds", "tds_pct", "TDS %")):
        typed = number(key, caption, blank_ok=True)
        if typed is not None and getattr(order, field) != typed:
            document[field] = typed
    for key, field in (("tds_section", "tds_section"), ("terms", "terms"),
                       ("delivery_address", "delivery_address")):
        if key in request.POST:
            typed = (request.POST.get(key) or "").strip()
            if getattr(order, field) != typed:
                document[field] = typed
    if "required_by" in request.POST:
        typed = (request.POST.get("required_by") or "").strip() or None
        if str(order.required_by or "") != (typed or ""):
            document["required_by"] = typed

    # >>> ANCHOR: WO-TERMS <<< — only a work order's form carries this input.
    #   Retention and DLP have no input since 11 Sep 2026 (retention is
    #   switched off); the mobilisation advance is the one term still typed.
    if order.document_type == DocumentType.WO:
        typed = number("mobilisation_advance", "mobilisation advance", blank_ok=True)
        if typed is not None and order.mobilisation_advance != typed:
            document["mobilisation_advance"] = typed

    if document:
        try:
            po_service.update_draft_document(order, **document)
            changed += 1
        except po_service.POError as refusal:
            problems.append(str(refusal))

    return changed, problems


@require_POST
@requires("po.edit_draft")
def po_line_remove(request, project_id, po_id, line_id):
    """
    Take one line off a draft — leaving the rest of the order intact.

    ⚠ This is the remedy behind the vendor-swap warning that comes next: when a
      BOM line's vendor changes while it sits on a draft with five other
      materials, the answer is to lift out THAT line, not to throw away five
      innocent ones. Removing the last line deletes the order, because an order
      with no lines is not a document.
    """
    project = get_object_or_404(Project, pk=project_id)
    order = get_object_or_404(PurchaseOrder, pk=po_id, project=project)
    line = get_object_or_404(order.lines, pk=line_id)
    material = line.bom_line.material.code
    number = order.number

    _apply_po_edits(request, order)           # keep what was typed elsewhere
    try:
        survivor = po_service.remove_draft_line(line)
    except po_service.POError as refusal:
        messages.error(request, str(refusal))
        return redirect(reverse("po_detail", args=[project.id, order.id]))

    if survivor is None:
        messages.warning(request, f"{material} removed, and {number} deleted with it — it was the "
                                  f"only line on the order. The quantity is back under "
                                  f"'still to buy' on the BOM.")
        return redirect(reverse("po_screen", args=[project.id]))

    messages.success(request, f"{material} removed from {number}. Its quantity is back under "
                              f"'still to buy'; the rest of the order is untouched.")
    return redirect(reverse("po_detail", args=[project.id, order.id]))


@requires("po.view")
def po_pdf(request, project_id, po_id):
    """
    The document as a PDF, for sending to the vendor.

    >>> ANCHOR: PO-PDF <<<
    ⚠ APPROVED ONWARDS ONLY. Saahil's rule. Approved, Delivered/Completed and
      Paid produce a file; a DRAFT never does — it is refused with a reason
      rather than quietly handed over. A draft that reaches a vendor as a PDF is
      indistinguishable from an order, and nothing in the document itself would
      tell them otherwise.

      The DRAFT watermark stays in the template regardless, because the download
      button is not the only way paper appears: anybody can print the screen, and
      that cannot be prevented. Two defences for two different holes.

    ⚠ WEASYPRINT IS IMPORTED INSIDE THIS FUNCTION, NOT AT THE TOP OF THE FILE.
      It needs native libraries and takes minutes to build, which is exactly why
      CI installs only Django, python-dotenv and openpyxl. A module-level import
      would make every test run on GitHub fail at import time on a library it
      does not have and does not need. It is only ever loaded by somebody who has
      actually asked for a PDF.
    """
    project = get_object_or_404(Project, pk=project_id)
    order = get_object_or_404(
        PurchaseOrder.objects.select_related("vendor", "project"), pk=po_id, project=project)

    if order.status == PurchaseOrder.Status.DRAFT:
        messages.warning(
            request,
            f"{order.number} is still a draft, so there is nothing to download. A draft commits "
            f"nothing and can still change — approve it first, and it locks at the same moment it "
            f"becomes a document you can send.")
        return redirect(reverse("po_detail", args=[project.id, order.id]))

    lines = list(order.lines
                 .select_related("bom_line__material")
                 .order_by("bom_line__activity__sort_order", "id"))

    html = render_to_string("projects/po_pdf.html", {
        "project": project,
        "order": order,
        "lines": lines,
        "totals": order.totals(),
        "company": CompanyProfile.get_solo(),
        "ship_to": order.delivery_address or project.site_address,
        "interstate": _is_interstate(order),
        # Nothing to watermark: a draft never gets this far. The template keeps
        # the machinery for the printed-from-screen case.
        "watermark": "",
    }, request=request)

    from weasyprint import HTML          # see the note above — deliberately here

    pdf = HTML(string=html, base_url=request.build_absolute_uri("/")).write_pdf()
    # A filename somebody can find again in a folder of two hundred: the number
    # first, because that is what everything else refers to.
    vendor = slugify(order.vendor.name).replace("-", "_") or "vendor"
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{order.number}_{vendor}.pdf"'
    return response


@require_POST
@requires("projects.edit")
def project_status(request, project_id):
    """
    Change a project's status from the BOQ screen.

    >>> ANCHOR: PROJECT-STATUS <<<
    ⚠ THIS IS THE CONTROL THAT LOCKS AN ESTIMATE, and until now it existed only
      on the project edit form. Saahil went looking for it on the BOQ — "I could
      not see a button to change the approval status from draft to quote to won?
      where is that?" — which is the right place to look, because the estimate it
      locks is on that screen.

    ⚠ NOTHING NEW IS PERMITTED HERE. Setting Won still locks the estimate,
      Admin included, and the only way back is Quoted — which leaves a visible
      trace where a silent Admin edit would not. This view moves the same
      decision to a better place; it does not soften it.
    """
    project = get_object_or_404(Project, pk=project_id)
    wanted = (request.POST.get("status") or "").strip()

    if wanted not in Project.Status.values:
        messages.error(request, "That is not a status a project can be in.")
        return redirect("boq_screen", project_id=project.id)

    if wanted == project.status:
        messages.info(request, f"{project.code} is already {project.get_status_display()}.")
        return redirect("boq_screen", project_id=project.id)

    was = project.get_status_display()
    project.status = wanted
    project.save(update_fields=["status"])

    # ⚠ ASK THE ESTIMATE, not a second list kept here. Estimate.EDITABLE_WHILE is
    #   the one place that decides what locks a BOQ; a copy of it in this view
    #   would be a second implementation of the rule and would eventually differ.
    if wanted not in Estimate.EDITABLE_WHILE:
        messages.success(
            request,
            f"{project.code} moved from {was} to {project.get_status_display()}. "
            f"⚠ The estimate is now LOCKED and cannot be edited by anyone, Admin included — the "
            f"reserve each activity is measured against is a live link to these rates. To correct "
            f"one, set the project back to Quoted, fix it, and set this again.")
    else:
        messages.success(request, f"{project.code} moved from {was} to "
                                  f"{project.get_status_display()}. The estimate is editable again.")
    return redirect("boq_screen", project_id=project.id)


@requires("projects.edit")
def project_form(request, project_id=None):
    """
    Create a project, or change one. The same screen does both.

    >>> ANCHOR: PROJECT-SCREEN <<<
    Until now this was Django Admin only, so every job started in generic
    scaffolding and moved to real screens at step 3. Saahil found that himself
    by looking for a Create Project button and not finding one.

    ⚠ THE CODE IS NEVER TYPED. It is shown once the project exists and is
      read-only forever after — a purchase order, a BOM and a receipt all point
      at it, so a code that changed underneath them would stop being an identity.

    ⚠ ADMIN STILL WORKS, deliberately. Saahil's call: "admin can see all". It is
      the back door for the day something needs correcting that these screens do
      not cover. The consequence is that anything which must happen on save has
      to live on the MODEL or in a shared function, not in this view — otherwise
      the two paths drift. Code generation lives in Project.save() for exactly
      that reason.
    """
    project = get_object_or_404(Project, pk=project_id) if project_id else None
    fields = ("name", "location", "bua_sqft", "floors", "status",
              "billing_address", "site_address")

    if request.method == "POST":
        project = project or Project()
        for field in fields:
            if field in request.POST:
                setattr(project, field, (request.POST.get(field) or "").strip())

        # BUA is the one figure the whole estimate multiplies by, so an
        # unreadable one must never quietly become zero.
        raw = (request.POST.get("bua_sqft") or "").strip().replace(",", "")
        try:
            project.bua_sqft = Decimal(raw) if raw else None
        except (InvalidOperation, ValueError):
            messages.error(request, f"'{raw}' is not a number I can read as a built-up area. "
                                    f"Nothing was saved.")
            return render(request, "projects/project_form.html",
                          {"project": project, "statuses": Project.Status.choices})

        try:
            project.full_clean(exclude=["code"] if not project.code else None)
        except ValidationError as invalid:
            for field, problems in invalid.message_dict.items():
                messages.error(request, f"{field.replace('_', ' ')}: {' '.join(problems)}")
            return render(request, "projects/project_form.html",
                          {"project": project, "statuses": Project.Status.choices})

        created = project.pk is None
        project.save()                      # save() assigns the code on creation
        messages.success(
            request,
            f"{project.code} — {project.name} {'created' if created else 'saved'}."
            + (" Set its BOQ rates next." if created else ""))
        # Straight to the BOQ on creation — the next thing anybody wants is the
        # estimate, and landing back on the list was a dead end. Editing an
        # existing project returns to the list, because that is where you came
        # from.
        return redirect(reverse("boq_screen", args=[project.id]) if created
                        else reverse("project_list"))

    return render(request, "projects/project_form.html", {
        "project": project,
        "statuses": Project.Status.choices,
    })


# ==================================================================== the BOQ
#
# >>> ANCHOR: BOQ-SCREEN <<<
# Step 2 of the process, and until slice 6 it existed only in Django Admin.
#
# WHAT IT IS: a flat ₹/sqft quote. Each activity carries a rate, the amount is
# rate × built-up area, and the total is a composite ₹/sqft. It produces MONEY
# BY TRADE, never quantities — the admin types planned quantities on the BOM.
#
# ⚠ AND THE MONEY IS NOT JUST A QUOTE. Each activity's amount becomes that
#   activity's RESERVE on the BOM — the budget every purchase is measured
#   against. That is the whole reason the two are linked, and it is why this
#   screen locks the moment the project is Won.


@requires("boq.view")
def boq_screen(request, project_id):
    """
    The estimate: which activities this project quotes for, and at what rate.

    ⚠ NOT ONE FIGURE IS CALCULATED HERE. Every total is a property on Estimate,
      so the screen, Admin and any future export read identical numbers.
    """
    project = get_object_or_404(Project, pk=project_id)
    estimate, _ = Estimate.objects.get_or_create(project=project)
    estimate.project = project          # already fetched; do not go back for it

    # ⚠ boq_rows, not estimate.lines.all(). Every figure on a line walks back to
    #   the estimate and the project, and `share` asks for the composite rate,
    #   which re-queries every line. Eighteen trades cost 38 extra queries before
    #   this existed — see the note in bom_calc.boq_rows.
    lines = bom_calc.boq_rows(estimate)
    chosen = {line.name for line in lines}
    # Activities available to add — the master, less what is already on. COM is
    # deliberately included: it has no reserve, so spend landing there is spend
    # that was never quoted, which is a useful signal rather than an error.
    available = [a for a in Activity.objects.filter(is_active=True).order_by("sort_order", "name")
                 if a.name not in chosen]

    return render(request, "projects/boq.html", {
        "project": project,
        "estimate": estimate,
        "lines": lines,
        "available": available,
        "editable": estimate.is_editable,
        "locked_reason": estimate.locked_reason,
        "has_bom": hasattr(project, "bom"),
        # For the status control in the header — see project_status.
        "statuses": Project.Status.choices,
    })


@requires("boq.view")
def boq_pdf(request, project_id):
    """
    The estimate as a PDF, for sending to the client or a portal.

    >>> ANCHOR: BOQ-PDF <<<
    ⚠⚠ QUOTED ONWARDS ONLY, AND THAT IS THE POINT OF IT. Saahil's words: "once
       they quote it, they download it, and then they upload it onto a portal."
       A DRAFT is refused with a reason rather than quietly handed over — the
       same rule, and the same reasoning, as the purchase order PDF. A draft
       estimate is a number still being argued about; on paper, in somebody
       else's inbox, it is indistinguishable from a quotation.

    ⚠ NOT ONE FIGURE IS CALCULATED HERE, and none in the template either. Every
      total is a property on `Estimate` and every row comes from
      `bom_calc.boq_rows`, so the screen, the PDF and Admin cannot disagree.
      That is the whole reason this is safe to add: there is no second
      implementation of the arithmetic to drift.

    ⚠ WEASYPRINT IS IMPORTED INSIDE THIS FUNCTION — see po_pdf. CI installs
      only Django, python-dotenv and openpyxl, so a module-level import would
      fail every test run on a library it does not have and does not need.
    """
    project = get_object_or_404(Project, pk=project_id)
    estimate = get_object_or_404(Estimate, project=project)

    if project.status == Project.Status.DRAFT:
        messages.warning(
            request,
            f"{project.code} is still a Draft, so there is nothing to send. Move it to Quoted "
            f"and the estimate becomes a document you can download — which is the point at "
            f"which the figures stop being a working note and start being an offer.")
        return redirect(reverse("boq_screen", args=[project.id]))

    lines = bom_calc.boq_rows(estimate)

    html = render_to_string("projects/boq_pdf.html", {
        "project": project,
        "estimate": estimate,
        "lines": lines,
        "company": CompanyProfile.get_solo(),
        # ⚠ A project can override the letterhead's address; the PO does the
        #   same thing and reads the same way round.
        "bill_to": project.billing_address,
    }, request=request)

    from weasyprint import HTML          # see the note above — deliberately here

    pdf = HTML(string=html, base_url=request.build_absolute_uri("/")).write_pdf()
    name = slugify(project.name).replace("-", "_") or "project"
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{project.code}_{name}_estimate.pdf"'
    return response


@require_POST
@requires("boq.edit")
def boq_save(request, project_id):
    """
    Write back the rates, then say what that did to the budgets underneath.

    ⚠ THE WHOLE FORM SAVES ON EVERY BUTTON, same as the BOM grid — otherwise
      pressing Generate BOM could build against figures that are not the ones on
      screen.
    """
    project = get_object_or_404(Project, pk=project_id)
    estimate = get_object_or_404(Estimate, project=project)

    if not estimate.is_editable:
        messages.error(request, estimate.locked_reason)
        return redirect(reverse("boq_screen", args=[project.id]))

    # >>> ANCHOR: BOM-CALC-RESERVE <<<
    # Read before writing, keyed on name because that is what the reserve
    # matches on. bom_calc.reserve_changes() turns this into the warning.
    before = {line.name: line.rate for line in estimate.lines.all()}
    problems, changed = [], 0

    def number(key, caption):
        raw = (request.POST.get(key) or "").strip().replace(",", "")
        if raw == "":
            return None
        try:
            return Decimal(raw)
        except (InvalidOperation, ValueError):
            problems.append(f"{caption} could not be read as a number, so it was left alone.")
            return None

    for line in estimate.lines.all():
        moved = {}
        rate = number(f"rate-{line.id}", f"rate for {line.name}")
        if rate is not None and rate != line.rate:
            moved["rate"] = rate
        gst = number(f"gst-{line.id}", f"GST% for {line.name}")
        if gst is not None and gst != line.gst_percent:
            moved["gst_percent"] = gst
        if moved:
            for field, value in moved.items():
                setattr(line, field, value)
            line.save(update_fields=list(moved) + [])
            changed += 1

    for key, field, caption in (("contingency", "contingency_percent", "contingency %"),
                                ("design_fee", "design_fee_percent", "design fee %"),
                                ("gst", "gst_percent", "GST %")):
        value = number(key, caption)
        if value is not None and getattr(estimate, field) != value:
            setattr(estimate, field, value)
            changed += 1
    estimate.saved_at = timezone.now()
    estimate.save()

    for problem in problems:
        messages.warning(request, problem)

    # ⚠ ONE IMPLEMENTATION, shared with Admin. See bom_calc.reserve_changes.
    for change in bom_calc.reserve_changes(project, before):
        messages.warning(request, "⚠ BOM budget changed — "
                                  + bom_calc.describe_reserve_change(change))

    if changed and not problems:
        messages.success(request, f"{project.code} estimate saved. Composite rate is now "
                                  f"₹{estimate.composite_rate}/sqft.")
    elif not changed:
        messages.info(request, "Nothing had changed, so nothing was saved.")
    return redirect(reverse("boq_screen", args=[project.id]))


@require_POST
@requires("boq.edit")
def boq_add_activity(request, project_id):
    """
    Put an activity onto this project's estimate, at the company's default rate.

    ⚠ PICKED FROM THE MASTER, NEVER TYPED. There is no free-text parameter on a
      project: a material cannot link to text that exists on one project only,
      so the BOM under such a parameter would start empty and the whole
      activity-filtered material search would not work there.
    """
    project = get_object_or_404(Project, pk=project_id)
    estimate = get_object_or_404(Estimate, project=project)
    if not estimate.is_editable:
        messages.error(request, estimate.locked_reason)
        return redirect(reverse("boq_screen", args=[project.id]))

    # ⚠ MANY AT ONCE, like the material picker on the BOM. Saahil's point: a
    #   quote covers a dozen trades, and adding them one page-reload at a time is
    #   twelve round trips to do one job. Ticking is how the BOM already works,
    #   so it is also the interaction people have already learnt here.
    wanted = request.POST.getlist("activity")
    if not wanted:
        messages.info(request, "Nothing was ticked, so nothing was added.")
        return redirect(reverse("boq_screen", args=[project.id]))

    already = set(estimate.lines.values_list("name", flat=True))
    added, skipped = [], []
    for activity in Activity.objects.filter(pk__in=wanted).order_by("sort_order", "name"):
        if activity.name in already:
            skipped.append(activity.name)
            continue
        EstimateLine.objects.create(
            estimate=estimate, name=activity.name, rate=activity.rate,
            gst_percent=activity.gst_percent, basis=activity.basis,
            sort_order=activity.sort_order)
        added.append(activity)

    if added:
        composite = sum((a.rate for a in added), ZERO)
        messages.success(
            request,
            f"{len(added)} construction activit{'y' if len(added) == 1 else 'ies'} added at the company "
            f"rates, "
            f"₹{composite}/sqft between them. Change any rate here and it applies to this "
            f"project only — the master is untouched.")
    if skipped:
        messages.info(request, f"Already on this estimate, so left alone: {', '.join(skipped)}.")
    return redirect(reverse("boq_screen", args=[project.id]))


@require_POST
@requires("boq.edit")
def boq_remove_activity(request, project_id, line_id):
    """
    Take an activity off this estimate.

    >>> ANCHOR: BOQ-REMOVE <<<
    ⚠ BLOCKED WHILE THE BOM HAS LINES UNDER IT. Saahil's call, 10 Aug.

      Removing the estimate line does not delete anything on the BOM — it takes
      the activity's RESERVE to zero, leaving those materials planned against a
      budget of nothing. That reads as "spend that was never quoted", which is a
      real signal, but arriving at it by accident is not what anybody meant.

      So it refuses, and names what is in the way. Clearing the BOM lines first
      is a deliberate act; this is not.
    """
    project = get_object_or_404(Project, pk=project_id)
    estimate = get_object_or_404(Estimate, project=project)
    line = get_object_or_404(EstimateLine, pk=line_id, estimate=estimate)

    if not estimate.is_editable:
        messages.error(request, estimate.locked_reason)
        return redirect(reverse("boq_screen", args=[project.id]))

    bom = getattr(project, "bom", None)
    activity = Activity.objects.filter(name=line.name).first()
    if bom is not None and activity is not None:
        planned = list(bom.lines.filter(activity=activity)
                       .select_related("material")[:6])
        count = bom.lines.filter(activity=activity).count()
        if count:
            names = ", ".join(l.material.code for l in planned)
            more = f" and {count - len(planned)} more" if count > len(planned) else ""
            messages.error(
                request,
                f"BOM lines exist under {line.name}, so it cannot be removed from the estimate. "
                f"{count} material{'' if count == 1 else 's'} are planned against it — "
                f"{names}{more}. Removing it would take their budget to zero and leave them "
                f"planned against nothing. Clear those BOM lines first if you really mean to.")
            return redirect(reverse("boq_screen", args=[project.id]))

    name = line.name
    line.delete()
    messages.success(request, f"{name} removed from the estimate. It is excluded from this quote; "
                              f"the activity master is untouched.")
    return redirect(reverse("boq_screen", args=[project.id]))


@requires("company.manage")
def rate_defaults(request):
    """
    ⚠ THIS SCREEN HAS MOVED — see ANCHOR: ACTIVITY-MASTER.

      The company's ₹/sqft per construction activity was never company data; it
      is a column on the activity, and it is now edited on the activity master
      beside the name, the GST and the active flag. Saahil, when the restructure
      was put to him: "Those rates are related to concerned activity. Are they
      not? So already we are maintaining the rates in construction activity,
      then why is it coming in company profile?"

    ⚠ THE ADDRESS IS KEPT AND REDIRECTS, rather than being deleted. Somebody has
      this bookmarked and the old screen was linked from the master data page
      for months; a 404 teaches them nothing, and a redirect lands them exactly
      where the same numbers now live.
    """
    return redirect(reverse("activity_master"))

@requires("company.manage")
def company_profile(request):
    """
    Us — the name, address and GSTIN printed at the top of every document.

    ⚠ OUR GSTIN IS NOT DECORATION. Its first two digits are half of the
      CGST+SGST vs IGST decision; the vendor's are the other half. Leave it blank
      and every document says so rather than guessing.

    One row, pinned to pk=1 by the model. There is no "add another".
    """
    company = CompanyProfile.get_solo()
    fields = ("name", "address", "gst_number", "email", "phone", "po_terms", "wo_terms")

    if request.method == "POST":
        for field in fields:
            if field in request.POST:
                setattr(company, field, (request.POST.get(field) or "").strip())
        try:
            company.full_clean()
        except ValidationError as invalid:
            for field, problems in invalid.message_dict.items():
                messages.error(request, f"{field}: {' '.join(problems)}")
            return render(request, "projects/company_profile.html", {"company": company})
        # save() derives `state` from the GSTIN — see masters.CompanyProfile.
        company.save()
        messages.success(request, "Company profile saved. Every document raised from now on prints "
                                  "these details; documents already approved keep what they were "
                                  "issued with.")
        return redirect(reverse("company_profile"))

    return render(request, "projects/company_profile.html", {"company": company})


# >>> ANCHOR: DRAFT-CONFLICT <<<
# There was a bom_detach_line view here, reached from a banner above the BOM
# grid. Saahil removed the banner — the red flag against the Vendor box already
# says which line is in trouble, and its tooltip says why, so a summary row was
# screen furniture on a page that will carry three to four hundred lines.
#
# The remedy did not go with it. The flag is now a LINK to the document that
# disagrees, and removing a line there is po_line_remove -> remove_draft_line:
# the identical operation. Two views doing the same thing is how they drift, so
# this one is gone rather than left behind "just in case".


@require_POST
@requires("po.view")
def po_advance(request, project_id, po_id):
    """
    Move a document one step along: Approve, then Delivered, then Paid.

    ⚠ APPROVE IS THE POINT OF NO RETURN. It locks the document permanently, and
      the confirmation says so in those words. Everything before it is
      disposable; nothing after it can be edited by anyone.

    ⚠ DELIVERED MEANS RECEIVED AND ACCEPTED, all of it. Saahil's rule: bad goods
      are settled with the vendor before anyone touches this screen. So a
      part-delivered order stays Approved until the rest arrives — which does
      mean "received" reads zero in the meantime, and that is accepted.
    """
    project = get_object_or_404(Project, pk=project_id)
    order = get_object_or_404(PurchaseOrder, pk=po_id, project=project)
    target = request.POST.get("to", "")

    # ⚠ THREE PERMISSIONS BEHIND ONE BUTTON ROW, so the decorator on this view
    #   cannot be the whole story — it only says "may open a document". Approve
    #   commits money, Paid releases it, Delivered records that goods arrived,
    #   and the matrix gives those three to different people on purpose: a
    #   Purchase manager delivers but does not approve; an Accountant pays but
    #   does not deliver; a Site engineer does neither except Delivered.
    needed = TRANSITION_PERMS.get(target)
    if needed and not perms.can(request.user, needed):
        return HttpResponseForbidden(
            "Your role does not include this step. Ask an Admin if you think it should.")

    try:
        if target == PurchaseOrder.Status.APPROVED:
            _apply_po_edits(request, order)   # never approve what is not on screen
            order.refresh_from_db()
            po_service.approve(order, user=request.user,
                               gstin=(request.POST.get("gstin") or "").strip() or None)
            messages.success(
                request,
                f"{order.number} approved and locked. Nothing on it can be changed now. "
                f"Its quantities have moved from In Draft to Approved on the BOM.")
        elif target == PurchaseOrder.Status.DELIVERED:
            po_service.mark_delivered(order, user=request.user)
            word = "completed" if order.document_type == DocumentType.WO else "delivered"
            messages.success(request, f"{order.number} marked {word}. Received quantities are "
                                      f"recorded against the BOM.")
        elif target == PurchaseOrder.Status.PAID:
            po_service.mark_paid(order, user=request.user)
            messages.success(request, f"{order.number} marked paid.")
        else:
            messages.error(request, "That is not a status this document can move to.")
    except po_service.POError as refusal:
        messages.error(request, str(refusal))

    # ⚠ ANCHOR: PO-REGISTER-STEP — a step taken from the register goes back to
    #   the register, with its filters, so a run of approvals stays on one screen.
    if request.POST.get("back") == "register":
        query = request.POST.get("q", "")
        return redirect(reverse("po_register") + (f"?{query}" if query else ""))
    return redirect(reverse("po_detail", args=[project.id, order.id]))


@require_POST
@requires("bom.generate")
def bom_generate(request, project_id):
    """
    Create the BOM for a project that does not have one.

    The gate is commercial, not editorial: you do not plan purchases for work
    nobody has agreed to pay for. So it needs an estimate, and it warns — but
    does not refuse — when the project is not Won.
    """
    project = get_object_or_404(Project, pk=project_id)
    if hasattr(project, "bom"):
        messages.info(request, f"{project.code} already has a BOM.")
        return redirect("bom_screen", project_id=project.id)
    if not hasattr(project, "estimate"):
        messages.error(request, f"{project.code} has no estimate yet. The BOM is planned against the "
                                f"activities on the estimate, so there is nothing to build it from.")
        return redirect("project_list")

    Bom.objects.create(project=project,
                       generated_by=request.user if request.user.is_authenticated else None)
    messages.success(request, f"BOM created for {project.code}. Add materials to each activity.")
    if project.status != Project.Status.WON:
        messages.warning(request, f"{project.code} is {project.get_status_display()}, not Won. "
                                  f"Planning purchases against work that has not been agreed is allowed, "
                                  f"but worth knowing.")
    return redirect("bom_screen", project_id=project.id)


# ====================================== the cross-project document register
#
# >>> ANCHOR: PO-REGISTER <<<
# Every purchase order and work order on every project, at one address.
#
# ⚠ THIS DOES NOT REPLACE THE PER-PROJECT PO SCREEN, AND MUST NOT.
#   Saahil corrected this explicitly: "BOM should also be able to navigate and
#   check out POs, as they will be created from there. The global PO list is to
#   view POs in a cleaner way so they dont have to always travel through
#   projects."
#
#   So documents are reachable two ways and both stay. Through the project when
#   you are working — creation still happens only from the BOM, and that path is
#   untouched. Through this screen when you are looking.
#
# ⚠ THIS SCREEN CREATES NOTHING AND APPROVES NOTHING.
#   It filters, it downloads, and it advances documents that are ALREADY
#   approved. Bulk approve was asked about and refused: approval locks a
#   document permanently, hard-blocks without a GSTIN, and there are still no
#   permissions — so a button that locks forty documents across every project,
#   clickable by anyone who knows the address, is the largest thing that could
#   be built wrong today. Approving stays on the document, where the totals
#   ladder is in front of you.
#
# ⚠⚠ AND THIS SCREEN IS WHY SECURITY IS NOW URGENT.
#   Until now a PO screen only ever showed one project. This one shows every
#   project to anyone who opens the URL, and every bulk action acts across all
#   of them. Not a reason to avoid building it — a reason that permissions must
#   land before anybody but Saahil opens the app.

# WeasyPrint runs inside the request and is slow. Beyond this many documents a
# zip would hold the browser with no way to tell whether it is working or dead,
# so it is refused with a message telling you to narrow the filter. Saahil
# rejected a low cap — rightly, he wants to choose what to download — so this
# sits well above ordinary use rather than getting in the way of it.
ZIP_LIMIT = 200

# One page of documents. The filters are the real tool; the pages just stop the
# HTML growing without limit as years of orders accumulate.
REGISTER_PAGE_SIZE = 100


def _month_bounds(value):
    """
    Turn "2026-08" from a <input type="month"> into a date, or None.

    ⚠ Returns the FIRST of the month. The caller decides whether that is a lower
      bound (this month onwards) or, after rolling forward one month, an
      exclusive upper bound — which is how "up to and including August" is
      expressed without caring how many days August has.
    """
    try:
        year, month = str(value).split("-")
        return datetime.date(int(year), int(month), 1)
    except (ValueError, AttributeError, TypeError):
        return None


def _next_month(day):
    """The first of the following month. Used as an exclusive upper bound."""
    return datetime.date(day.year + (day.month == 12), (day.month % 12) + 1, 1)


def _register_orders(request):
    """
    Every document, narrowed by whatever was filtered on.

    ⚠ ONE IMPLEMENTATION, USED BY ALL FOUR VIEWS — the list, the Excel export,
      the zip and the bulk advance. The same reason totals() is written once:
      an export that quietly disagreed with the screen it was exported from
      would be worse than no export at all.

    The filters, and why each is the shape it is:

      project, vendor   dropdowns. Saahil's call, and the right one — nobody
                        types a project code they can pick from a list.
      activity          a two-hop join, PO line -> BOM line -> activity, so it
                        means "documents containing at least one line in this
                        trade". The document still opens showing all its lines.
                        ⚠ NEEDS distinct(), or a document with four lines in
                        one activity appears four times.
      month from / to   a RANGE rather than an operator box. Saahil's
                        simplification of a before/after/between dropdown, and
                        it is better: leaving `from` empty means "before", and
                        leaving `to` empty means "after", so one pair of inputs
                        does what three controls would have.
      status, type      plain dropdowns.
      q                 the document number.

    ⚠ `lines` IS PREFETCHED AND MUST STAY THAT WAY. totals() walks them, so
      without it the page asks the database once per document.
    """
    orders = (PurchaseOrder.objects
              .select_related("vendor", "project")
              .prefetch_related("lines")
              .order_by("-raised_on", "-id"))

    applied = {}

    project_id = (request.GET.get("project") or "").strip()
    if project_id.isdigit():
        orders = orders.filter(project_id=int(project_id))
        applied["project"] = int(project_id)

    vendor_id = (request.GET.get("vendor") or "").strip()
    if vendor_id.isdigit():
        orders = orders.filter(vendor_id=int(vendor_id))
        applied["vendor"] = int(vendor_id)

    activity = (request.GET.get("activity") or "").strip()
    if activity:
        orders = orders.filter(lines__bom_line__activity__abbreviation=activity).distinct()
        applied["activity"] = activity

    status = (request.GET.get("status") or "").strip()
    if status in PurchaseOrder.Status.values:
        orders = orders.filter(status=status)
        applied["status"] = status

    doc_type = (request.GET.get("type") or "").strip()
    if doc_type in DocumentType.values:
        orders = orders.filter(document_type=doc_type)
        applied["type"] = doc_type

    month_from = _month_bounds(request.GET.get("from"))
    if month_from:
        orders = orders.filter(raised_on__gte=month_from)
        applied["from"] = request.GET.get("from")

    month_to = _month_bounds(request.GET.get("to"))
    if month_to:
        # Exclusive upper bound on the FIRST of the next month, so "to August"
        # includes every day of August without counting them.
        orders = orders.filter(raised_on__lt=_next_month(month_to))
        applied["to"] = request.GET.get("to")

    query = (request.GET.get("q") or "").strip()
    if query:
        orders = orders.filter(number__icontains=query)
        applied["q"] = query

    return orders, applied


def _register_options():
    """
    What goes in the dropdowns.

    ⚠ ONLY PROJECTS AND VENDORS THAT ACTUALLY HAVE DOCUMENTS, and only
      activities that actually appear on one. The existing per-project filter
      bar already works this way and the note there says why: "an empty filter
      option is a promise the screen cannot keep."

    ⚠ AND THEY COME FROM EVERY DOCUMENT, NOT THE CURRENT PAGE. Saahil asked for
      exactly this — the filters must search "from the whole relevant lot". A
      dropdown built from one page would only offer the vendors who happened to
      appear on it, which is the classic version of this bug: the filter can
      only find what you can already see.
    """
    projects = (Project.objects
                .filter(purchase_orders__isnull=False)
                .distinct().order_by("code"))
    vendors = (Vendor.objects
               .filter(purchase_orders__isnull=False)
               .distinct().order_by("name"))
    activities = (Activity.objects
                  .filter(bom_lines__po_lines__isnull=False)
                  .distinct().order_by("sort_order", "name"))
    return projects, vendors, activities


def _register_selection(request):
    """
    Which documents an action applies to: the ticked ones, or the whole filtered
    set when nothing is ticked.

    ⚠ Saahil's rule for the downloads — "User should choose what selection
      criteria do they wish to download, can be all, can be specific." Ticking
      nothing means "everything these filters found", which is what the screen
      says it will do above the buttons.

    The filters arrive on the query string even though the form POSTs, so this
    reuses _register_orders unchanged rather than keeping a second copy of the
    filtering that could drift from the first.
    """
    orders, _ = _register_orders(request)
    ids = [i for i in request.POST.getlist("ids") if i.isdigit()]
    if ids:
        orders = orders.filter(id__in=[int(i) for i in ids])
    return orders


@requires("register.view")
def po_register(request):
    """
    LEVEL 0 — every document on every project.

    Document-level rows, not line-level. Line-level would make the activity
    filter literal and is closer to what SAP does, but one project holds
    thousands of BOM lines and a list of every PO line across every project is
    not something a person reads.
    """
    orders, applied = _register_orders(request)
    projects, vendors, activities = _register_options()

    # ⚠ ONE COUNT, NOT TWO. The paginator has already counted the matches to work
    #   out how many pages there are; asking the queryset separately ran the same
    #   COUNT a second time on every page load. Found by measuring, not reading.
    paginator = Paginator(orders, REGISTER_PAGE_SIZE)
    page = paginator.get_page(request.GET.get("page"))
    matched = paginator.count

    rows = [{"order": order, "totals": order.totals(), "step": _next_step(request.user, order)}
            for order in page.object_list]

    # ⚠ THE FOOTER TOTALS THIS PAGE, AND SAYS SO ON THE SCREEN.
    #   order_value comes out of totals(), which walks a document's lines in
    #   Python — so totalling the whole filtered set would mean loading every
    #   line of every matching document on every page load. The Excel export
    #   carries the full set and its own total; that is the right place for it.
    page_value = sum((row["totals"]["order_value"] for row in rows), ZERO)

    return render(request, "projects/po_register.html", {
        "rows": rows,
        "page_obj": page,
        "applied": applied,
        "matched": matched,
        "page_value": page_value,
        "projects": projects,
        "vendors": vendors,
        "activities": activities,
        "statuses": PurchaseOrder.Status.choices,
        "querystring": request.GET.urlencode(),
        "zip_limit": ZIP_LIMIT,
    })


# >>> ANCHOR: PO-REGISTER-STEP <<<
# The one next step a document can take, as a button on its register row.
#
# ⚠ ONE DOCUMENT AT A TIME, THROUGH po_advance, SO EVERY RULE STILL HOLDS. The
#   register's bulk box deliberately never approves (see po_register_advance);
#   this button does, because it acts on ONE row whose totals are printed beside
#   it, and the approval itself still runs po_service.approve — the GSTIN block
#   refuses exactly as it does on the document screen, and the refusal comes
#   back as a message on this page. A WO with RA bills is refused by the same
#   guard as always. Nothing is bypassed; only the walk to the document is.
_STEP_WORD = {
    PurchaseOrder.Status.APPROVED: "Approve",
    PurchaseOrder.Status.DELIVERED: "Mark delivered",
    PurchaseOrder.Status.PAID: "Mark paid",
}


def _next_step(user, order):
    """(target status, button label) when this person may take it, else None."""
    target = order.next_status
    if target is None:
        return None
    if not perms.can(user, TRANSITION_PERMS[target]):
        return None
    label = _STEP_WORD[target]
    if target == PurchaseOrder.Status.DELIVERED and order.document_type == DocumentType.WO:
        label = "Mark completed"
    return {"to": target, "label": label}


def _register_redirect(request):
    """Back to the register with the filters still applied."""
    query = request.GET.urlencode()
    return redirect(f"{reverse('po_register')}{'?' + query if query else ''}")


@require_POST
@requires("register.export")
def po_register_excel(request):
    """
    The filtered documents as a spreadsheet — the file that goes to the
    accountant.

    ⚠ A REGISTER, NOT A DOCUMENT. One row per order with the money columns; it
      does not try to reproduce what the PDF prints. Two different jobs, and a
      spreadsheet that half-imitated a purchase order would do neither.
    """
    # openpyxl is a real dependency and CI installs it, so this could sit at the
    # top of the file. It is here only because one view in this module needs it.
    # That is NOT the reason WeasyPrint is imported inside its view — that one is
    # necessity, because CI deliberately does not install it.
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    orders = (_register_selection(request)
              .prefetch_related("lines__bom_line__material", "lines__bom_line__activity"))

    book = Workbook()
    sheet = book.active
    sheet.title = "Purchase order lines"

    # ⚠ ONE ROW PER LINE, NOT PER DOCUMENT. Saahil asked for it that way — "the
    #   download document into excel from PO should also have line items as well
    #   for easy tracking".
    #
    # >>> ANCHOR: PO-LINE-SHARES <<<
    # ⚠⚠ EVERY MONEY COLUMN ON THIS SHEET CAN BE SUMMED. That is the invariant,
    #    and it was not true until 16 Aug 2026. Four columns used to REPEAT the
    #    document-level figure on each line, so a four-line order printed its TDS
    #    four times and the accountant's SUM gave four times the real TDS. The
    #    heading said "(repeats)" and that was judged enough. It was not: this
    #    file's whole job is to be filtered and pushed into Tally, and a column
    #    that must not be added is a trap in a file built for adding.
    #
    # ⚠ SO THE DOCUMENT AMOUNTS ARE NOW APPORTIONED ACROSS THE LINES, exactly —
    #   see `PurchaseOrder.line_shares()`. The percentages still repeat, because
    #   a rate is not an amount and nobody sums a percentage.
    headings = [
        "Document", "Type", "Status", "Raised", "Approved", "Paid",
        "Project", "Project name", "Vendor", "Vendor GSTIN",
        "Construction activity", "Material code", "Material", "Specification", "UOM",
        "Qty", "Rate", "Value", "Line disc %", "Basic", "GST %", "GST", "Line total",
        # Document RATES. These repeat, and that is correct — a percentage is not
        # a quantity of money and adding a column of them is meaningless anyway.
        "Deduction %", "TDS %",
        # Document AMOUNTS, apportioned. Each of these columns adds up to the
        # document's own figure, to the paisa, for one order or for the whole file.
        "Line deduction", "Line round off", "Line TDS",
        "Line order value", "Line net payable",
    ]
    sheet.append(headings)
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F3864")
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    # The apportioned columns get their own colour, so a reader can see at a
    # glance which figures came from the document rather than from the line.
    #
    # ⚠ COMPUTED FROM `headings`, NOT HARD-CODED LETTERS. This used to be the
    #   literal string "WXYZ", which only meant "the last four columns" while
    #   the sheet happened to have exactly 26 of them. Adding "Project name"
    #   shifted every column after it by one and would have silently painted
    #   the wrong four. Bug 29's shape: a unit change (a column position) is not
    #   a cosmetic one.
    from openpyxl.utils import get_column_letter
    first_share = headings.index("Line deduction")
    for offset in range(first_share, len(headings)):
        sheet[f"{get_column_letter(offset + 1)}1"].fill = PatternFill("solid", fgColor="8A6D1F")

    line_rows = 0
    for order in orders:
        # ⚠ ONE CALL PER DOCUMENT, NOT PER LINE. `line_shares()` runs the whole
        #   ladder and the apportionment together; asking it again inside the
        #   loop would repeat that work for every row of a long order.
        for share in order.line_shares():
            line = share["line"]
            line_rows += 1
            material = line.bom_line.material
            sheet.append([
                order.number,
                order.get_document_type_display(),
                # status_word, not the raw status: a work order reads "Completed"
                # where a purchase order reads "Delivered".
                order.status_word,
                order.raised_on,
                order.approved_at.date() if order.approved_at else None,
                order.paid_at.date() if order.paid_at else None,
                order.project.code,
                order.project.name,
                order.vendor.name,
                order.vendor_gstin or order.vendor.gst_number or "",
                line.bom_line.activity.name,
                material.code,
                material.name,
                material.specification,
                material.uom,
                # ⚠ Every one of these is a property on PurchaseOrderLine, not
                #   arithmetic written here. `basic`, `taxable`, `gst_amount` and
                #   `total` are what the document screen and the PDF print, so an
                #   export cannot disagree with the document it came from.
                float(line.quantity),
                float(line.rate),
                float(line.basic),
                float(line.discount_pct),
                float(line.taxable),
                float(line.gst_percent),
                float(line.gst_amount),
                float(line.total),
                float(order.deduction_pct),
                float(order.tds_pct),
                float(share["deduction"]),
                float(share["round_off"]),
                float(share["tds"]),
                float(share["order_value"]),
                float(share["net_payable"]),
            ])

    # ⚠⚠ WIDTHS AND THE NUMBER-FORMAT RANGE ARE KEYED OFF `headings`, NOT COUNTED
    #    BY HAND. They were hand-counted, and they had already drifted: the tuple
    #    held 26 widths for 27 columns, and the format ran 15–26 when the money
    #    starts at 16 — so UOM was being given Indian digit grouping and the last
    #    money column got neither a width nor a format. Nobody would ever have
    #    seen it, because a spreadsheet with a narrow column still opens. Same
    #    lesson as the fill above, one column later.
    widths = {
        "Document": 15, "Type": 15, "Status": 12, "Raised": 11, "Approved": 11,
        "Paid": 11, "Project": 13, "Project name": 30, "Vendor": 17,
        "Vendor GSTIN": 22, "Construction activity": 15, "Material code": 30,
        "Material": 22, "Specification": 9, "UOM": 10,
    }
    for index, heading in enumerate(headings, start=1):
        letter = sheet.cell(row=1, column=index).column_letter
        sheet.column_dimensions[letter].width = widths.get(heading, 14)

    money_from = headings.index("Qty") + 1
    for row in sheet.iter_rows(min_row=2, min_col=money_from, max_col=len(headings)):
        for cell in row:
            cell.number_format = "#,##,##0.00"      # Indian grouping, as everywhere else
    sheet.freeze_panes = "B2"

    stream = io.BytesIO()
    book.save(stream)
    stream.seek(0)

    stamp = timezone.localdate().isoformat()
    response = HttpResponse(
        stream.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="PurchaseOrders_{stamp}.xlsx"'
    return response


@require_POST
@requires("register.export")
def po_register_zip(request):
    """
    The selected documents as one zip of individual PDFs.

    ⚠ A ZIP OF SEPARATE FILES, NEVER ONE MERGED PDF, AND THIS IS NOT A
      PREFERENCE. The printed document is signed off and carries a running
      "Page X of Y" footer PER DOCUMENT. Merging fifty orders into one file
      makes that numbering continuous across all of them, so either the footer
      starts lying or the template has to change — and the template is not being
      reopened. Separate files keep every document byte-identical to the one you
      download from its own screen.

    ⚠ APPROVED ONWARDS ONLY, and drafts are SKIPPED WITH A COUNT rather than
      silently dropped. A zip that quietly contains fewer files than you
      selected is a zip you cannot trust. Same rule as the single download: a
      draft that reaches a vendor as a PDF is indistinguishable from an order.
    """
    orders = list(_register_selection(request)
                  .select_related("vendor", "project")
                  .order_by("number"))

    sendable = [o for o in orders if o.status != PurchaseOrder.Status.DRAFT]
    skipped = len(orders) - len(sendable)

    if not sendable:
        messages.warning(
            request,
            "Nothing there can be downloaded. " +
            (f"All {skipped} of those documents are still drafts, and a draft has no PDF — "
             f"approve one and it locks at the same moment it becomes something you can send."
             if skipped else "No documents matched."))
        return _register_redirect(request)

    if len(sendable) > ZIP_LIMIT:
        messages.error(
            request,
            f"That is {len(sendable)} documents, and this builds each PDF one at a time — above "
            f"{ZIP_LIMIT} the browser would sit there with no way to tell whether it was working "
            f"or had died. Narrow it with the filters, by month or by project, and download it in "
            f"parts.")
        return _register_redirect(request)

    from weasyprint import HTML          # see po_pdf — deliberately not at module level

    company = CompanyProfile.get_solo()
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as bundle:
        for order in sendable:
            lines = list(order.lines
                         .select_related("bom_line__material")
                         .order_by("bom_line__activity__sort_order", "id"))
            html = render_to_string("projects/po_pdf.html", {
                "project": order.project,
                "order": order,
                "lines": lines,
                "totals": order.totals(),
                "company": company,
                "ship_to": order.delivery_address or order.project.site_address,
                "interstate": _is_interstate(order),
                "watermark": "",
            }, request=request)
            pdf = HTML(string=html, base_url=request.build_absolute_uri("/")).write_pdf()
            # The same name the single download gives, so a file pulled from a
            # zip and one downloaded on its own are indistinguishable in a
            # folder. The number already carries the project.
            vendor = slugify(order.vendor.name).replace("-", "_") or "vendor"
            bundle.writestr(f"{order.number}_{vendor}.pdf", pdf)

    stream.seek(0)
    if skipped:
        messages.info(request, f"{len(sendable)} downloaded. {skipped} still in draft and skipped — "
                               f"a draft has no PDF until it is approved.")

    stamp = timezone.localdate().isoformat()
    response = HttpResponse(stream.read(), content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="PurchaseOrders_{stamp}.zip"'
    return response


@require_POST
@requires("register.view")
def po_register_advance(request):
    """
    Move several documents one step along — Delivered/Completed, or Paid.

    ⚠ THERE IS NO BULK APPROVE HERE AND THERE MUST NOT BE. Approval locks a
      document permanently and hard-blocks without a GSTIN; it belongs on the
      document screen with the totals in front of you. Delivered and Paid are a
      different case, and lumping them in with approve was a mistake worth
      naming: Delivered is all-or-nothing by design, so it is genuinely a
      document-level yes or no needing no line detail, and Paid across twenty
      documents after a payment run is an ordinary afternoon. Neither locks
      anything that is not already locked.

    ⚠ A MIXED SELECTION IS REFUSED. A work order reads "Completed" where a
      purchase order reads "Delivered" — same status underneath, different word
      to the person reading it. One button cannot honestly say both, and Saahil
      chose blocking over inventing a third word for it.

    Each document goes through po_service, one at a time, so every rule the
    single-document path enforces is enforced here too. Refusals are collected
    and reported rather than stopping the batch.
    """
    target = request.POST.get("to", "")
    if target not in (PurchaseOrder.Status.DELIVERED, PurchaseOrder.Status.PAID):
        messages.error(request, "Documents can only be moved to Delivered/Completed or Paid from "
                                "this screen. Approving is done on the document itself, where you "
                                "can see what you are locking.")
        return _register_redirect(request)

    # ⚠ THE BULK BOX OFFERS ONLY WHAT THAT ROLE COULD DO ONE DOCUMENT AT A TIME.
    #   Saahil's rule, and the reason it exists: a Purchase manager cannot mark
    #   a single document Paid, so being able to mark twenty at once would make
    #   the single-document rule decoration. Same mapping as the document
    #   screen, read from the same place.
    if not perms.can(request.user, TRANSITION_PERMS[target]):
        return HttpResponseForbidden(
            "Your role does not include this step. Ask an Admin if you think it should.")

    orders = list(_register_selection(request).select_related("vendor", "project"))
    if not orders:
        messages.warning(request, "Nothing was selected, and no documents matched those filters.")
        return _register_redirect(request)

    kinds = {o.document_type for o in orders}
    if len(kinds) > 1 and target == PurchaseOrder.Status.DELIVERED:
        messages.error(
            request,
            "That selection mixes purchase orders and work orders. A work order is marked "
            "Completed and a purchase order Delivered — the same step, but the documents say "
            "different words and one button cannot honestly say both. Filter to one type and "
            "try again.")
        return _register_redirect(request)

    done, refused = [], []
    for order in orders:
        try:
            if target == PurchaseOrder.Status.DELIVERED:
                po_service.mark_delivered(order, user=request.user)
            else:
                po_service.mark_paid(order, user=request.user)
            done.append(order.number)
        except po_service.POError as refusal:
            refused.append(f"{order.number}: {refusal}")

    if done:
        word = "paid" if target == PurchaseOrder.Status.PAID else (
            "completed" if kinds == {DocumentType.WO} else "delivered")
        messages.success(request, f"{len(done)} document{'' if len(done) == 1 else 's'} marked "
                                  f"{word} — {', '.join(done[:8])}"
                                  f"{' and more' if len(done) > 8 else ''}.")
    if refused:
        messages.warning(request, "These were left alone:\n" + "\n".join(refused[:10]))

    return _register_redirect(request)
