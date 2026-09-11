"""
The launchpad's tiles, and the second-level Master data page.

WHAT THIS FILE IS FOR
    tiles_for(role)     the tiles on the home screen
    master_data_for()   the entries behind the Master data tile

WHY THIS IS DATA AND NOT HTML
    >>> ANCHOR: HUB-TILES <<<
    Saahil's description of the launchpad was "the admin sees 4-5 tiles". Roles
    do not exist yet — security is its own slice — but the sentence says exactly
    what the shape has to be: SOMEBODY sees SOME of these.

    So every tile carries the roles it belongs to, and `tiles_for` filters on
    them. Today nothing passes a role and everyone sees everything. When the
    security slice lands, showing a storekeeper a smaller launchpad is one
    argument to this function.

    Written as markup in a template instead, the same change would mean picking
    apart a grid of divs and threading a permission check through each one. This
    costs nothing now and saves that later.

⚠ TILES FOR SCREENS THAT DO NOT EXIST ARE DELIBERATE, NOT PLACEHOLDER SLOPPINESS.
    Analytics has no code behind it and is drawn greyed, reading "Coming later".
    Task management sat beside it in the same state for weeks and has now lit up,
    which is the whole point of the arrangement. Saahil asked for it in these
    words:

        "the last 2 will be added later but it gives a view to the user
         holistically"

    Somebody opening this app for the first time should see the shape of the
    whole system, including the parts still to come. A tile that appears one day
    without warning teaches nobody anything; a tile that has been sitting there
    greyed for two months is understood the moment it lights up.

⚠ A TILE ONLY EARNS ITS PLACE IF IT WORKS WITHOUT A PROJECT.
    The BOQ and the BOM are per-project screens — "Bill of materials" on a home
    page is meaningless until you say whose. Those stay behind Projects. What
    the launchpad lists is Projects, and the things that genuinely cut across
    every project.
"""
from django.urls import reverse

from accounts.models import Role
from accounts.perms import role_can

# ⚠ THESE NAMES PREDATE THE ACCOUNTS APP AND NOW POINT AT IT.
#   They were invented here months before there was a login, so that filtering
#   the launchpad by role would one day be an argument rather than a rewrite.
#   That day is this commit: the strings are the same, the source of truth has
#   moved to accounts.models.Role, and nothing that imported them broke.
ROLE_ADMIN = Role.ADMIN
ROLE_PURCHASE = Role.PURCHASE
ROLE_SITE = Role.SITE

ALL_ROLES = frozenset(Role.values)


# ⚠ `url_name` is a URL NAME, never a written-out path. A test walks this list
#   and reverses every one of them, so a tile pointing at a screen that has been
#   renamed fails the suite instead of 404-ing on somebody's screen.
_TILES = [
    {
        "key": "projects",
        "color": "#2E5C9A",
        "icon": "M3 21V8l9-5 9 5v13H3zm4-2h4v-5h2v5h4V9.4L12 5.3 7 9.4V19z",
        "title": "Projects",
        "subtitle": "Estimates, bills of materials and everything per site",
        "url_name": "project_list",
        "perm": "projects.view",
        "live": True,
    },
    {
        "key": "orders",
        "color": "#8A6D1F",
        "icon": "M6 2h9l5 5v15H6V2zm8 1.5V8h4.5L14 3.5zM8 11h8v2H8v-2zm0 4h8v2H8v-2z",
        "title": "Purchase orders",
        "subtitle": "Every document across every project",
        "url_name": "po_register",
        "perm": "register.view",
        "live": True,
    },
    {
        "key": "masters",
        "color": "#4C6B3A",
        "icon": "M4 4h7v7H4V4zm9 0h7v7h-7V4zM4 13h7v7H4v-7zm9 0h7v7h-7v-7z",
        "title": "Master data",
        "subtitle": "Materials, vendors, construction activities and the company's own details",
        "url_name": "master_data",
        "perm": "masters.view",
        "live": True,
    },
    {
        "key": "analytics",
        "color": "#4A3B79",
        "icon": "M4 20V10h3v10H4zm6.5 0V4h3v16h-3zM17 20v-7h3v7h-3z",
        "title": "Analytics",
        "subtitle": "Committed, owed and paid — and reserve against actual",
        "url_name": "analytics_home",
        # ⚠ THE ONLY PERMISSION IN THE MATRIX HELD BY ONE ROLE. Reserve against
        #   actual is the insight the owner keeps.
        "perm": "analytics.view",
        "live": True,
    },
    {
        "key": "compliance",
        "color": "#A32D2D",
        "icon": "M12 2l8 3v6c0 5-3.4 9.3-8 11-4.6-1.7-8-6-8-11V5l8-3zm-1.2 13.2l5.7-5.7-1.4-1.4-4.3 4.3-2.1-2.1-1.4 1.4 3.5 3.5z",
        "title": "Compliance",
        "subtitle": "AMC and RERA — what every site holds, and what it is missing",
        "url_name": "compliance_home",
        # ⚠ THE WIDEST READ PERMISSION IN THE SYSTEM, and deliberately: a site
        #   engineer in front of an inspector needs the labour licence on their
        #   phone. Uploading is Admin and Compliance only.
        "perm": "compliance.view",
        "live": True,
    },
    {
        "key": "tasks",
        "color": "#C55A11",
        "icon": "M4 5h16v2H4V5zm0 6h10v2H4v-2zm0 6h13v2H4v-2zm14-5l1.5 1.5L21 12l1 1-2.5 2.5L17 13l1-1z",
        "title": "Task management",
        "subtitle": "Who is doing what on site, and by when",
        "url_name": "task_board",
        # ⚠ `tasks.view`, NOT `tasks.manage`. Everybody holds this one, which is
        #   why the tile stays where it has always been for every role — the
        #   board is a thing you read. Creating and assigning is `tasks.manage`,
        #   and that hides the buttons, not the screen.
        "perm": "tasks.view",
        # ⚠ THIS WENT LIVE AFTER SITTING GREYED SINCE THE LAUNCHPAD WAS WRITTEN,
        #   which is exactly what the greyed tiles were for: "the last 2 will be
        #   added later but it gives a view to the user holistically". Nobody has
        #   to be told where it is — they have been looking at it for weeks.
        "live": True,
    },
    {
        "key": "sales",
        "color": "#0F766E",
        "icon": "M3 11l9-8 9 8v10h-6v-6H9v6H3V11zm9 1.5a2 2 0 100-4 2 2 0 000 4z",
        "title": "Sales",
        "subtitle": "Units, enquiries, bookings and what customers still owe",
        "url_name": "sales_home",
        "perm": "sales.view",
        "live": True,
    },
    {
        "key": "finance",
        "color": "#B45309",
        "icon": "M3 6h18v12H3V6zm2 2v8h14V8H5zm7 1a3 3 0 110 6 3 3 0 010-6z",
        "title": "Finance & Accounting",
        "subtitle": "Bills against orders, contractor bills, payments and what is owed",
        "url_name": "finance_home",
        "perm": "finance.view",
        "live": True,
    },
    {
        "key": "drawings",
        "color": "#1D4ED8",
        "icon": "M3 3h18v18H3V3zm2 2v14h14V5H5zm2 2h6v2H7V7zm0 4h10v2H7v-2zm0 4h8v2H7v-2z",
        "title": "Drawings",
        "subtitle": "Every drawing, its revisions, and who was sent which",
        "url_name": "drawings_home",
        "perm": "drawings.view",
        "live": True,
    },
]


def tiles_for(role=None):
    """
    The tiles somebody should see.

    ⚠ TILES ARE FILTERED BY PERMISSION, NOT BY A LIST OF ROLES.
      Each tile names the key that opens the screen behind it, so a tile can
      never appear for somebody the view would then refuse — the two cannot
      drift, because they read the same line of the matrix.

    `role=None` means "nobody in particular" and returns everything; it is what
    the tests for the launchpad's shape use, and what the screen used before
    there were roles.

    Each tile comes back with `url` resolved, or None when it is not live, so
    the template never calls {% url %} on a screen that does not exist.
    """
    out = []
    for tile in _TILES:
        if role is not None and tile["perm"] is not None and not role_can(role, tile["perm"]):
            continue
        resolved = dict(tile)
        resolved["url"] = reverse(tile["url_name"]) if tile["url_name"] else None
        out.append(resolved)
    return out


# ---------------------------------------------------------- master data page
#
# >>> ANCHOR: HUB-MASTERS <<<
# The second level behind the Master data tile.
#
# ⚠⚠ IT USED TO BE A FLAT LIST OF NINE ENTRIES, FIVE OF WHICH DROPPED INTO
#    DJANGO ADMIN. Saahil found the Units of measure one and asked the obvious
#    question — "the UOM tile still shows and opens up Django, I could not see
#    any UI for that" — and then the better one:
#
#      "Can we not just make it one tile and then have different sections to
#       navigate it? So the master data when we go inside, we do not see sixty
#       eight tiles."
#
#    So the second level is now FIVE entries, and the things that belong
#    together sit behind tabs on one screen rather than each earning a tile.
#
# ⚠ NOTHING OPENS DJANGO ADMIN FROM HERE ANY MORE. Material groups, vendor
#   groups, vendor rates, units of measure and construction activities all have
#   screens of their own. The "Opens in Admin" section is gone, along with the
#   note explaining it.
#
# ⚠ COMPANY RATES IS NOT ON THIS PAGE, AND IT HAS NOT BEEN DELETED. The
#   company's ₹/sqft per activity was never company data — it is a COLUMN on the
#   construction activity master, and it now lives on that screen. Saahil, when
#   it was described to him: "Those rates are related to concerned activity. Are
#   they not? Then why is it coming in company profile?" He was right; the
#   separate screen was an accident of build order, from when activities had no
#   screen at all.
#
# ⚠ USERS STAYS ITS OWN ENTRY rather than being folded into Company. His call —
#   "for company, go with profile and keep users separate".

# ⚠ A LINK TABLE IS NOT A SCREEN. Saahil's call, and Admin already agreed with
#   him: MaterialAdmin carries MaterialActivityInline and VendorAdmin carries
#   VendorCategoryInline, so both are edited INSIDE the record they belong to.
#
#   "Material is to be linked to activity in the same material master screen,
#    not as a separate tile."
#
#   The models stay registered in Admin, because a list view is still the only
#   way to fix a spelling across every record at once. They just do not earn a
#   tile, and nothing on this page points at Admin any more.

#: title -> the permission that opens it. One entry, one key, checked one at a
#: time, so a purchase manager who maintains vendors is not shown the company's
#: own profile or the Users screen.
_ENTRY_PERMS = {
    "materials_home": "masters.view",
    "vendors_home": "masters.view",
    "activity_master": "masters.view",
    "company_profile": "company.manage",
    "user_list": "users.manage",
    # ⚠ ANCHOR: INFO-PANELS — Admin alone, narrower than masters.edit.
    "panel_text": "help.edit",
}

#: (title, blurb, url name)
#:
#: ⚠ FIVE ENTRIES, NOT NINE. Each of the first three opens a screen with tabs
#:   rather than a tile per table — see the note at the top of this section.
_ENTRIES = [
    ("Materials",
     "705 of them, their groups, and the units they are measured in",
     "materials_home"),
    ("Vendors",
     "173 of them, what kind of supplier each is, and what they last quoted",
     "vendors_home"),
    # ⚠ THE RATE IS ON THIS SCREEN. It was "Company rates" until Saahil pointed
    #   out that a rate per activity is not company data.
    ("Construction activities",
     "The trade master the BOQ picks from, and the company ₹/sqft for each",
     "activity_master"),
    ("Company profile",
     "Our name, GSTIN, addresses and the standard terms that print on every document",
     "company_profile"),
    # ⚠ USERS LIVES HERE, NOT ON THE LAUNCHPAD, and not inside Company either.
    #   Saahil: "add it under master data tile", and later "keep users separate".
    ("Users",
     "Who can sign in, as which role, and who has never signed in at all",
     "user_list"),
    # ⚠ THE SIXTH ENTRY, AND IT CHANGES A DECISION. Master data was five entries
    #   by Saahil's own call; he asked for this one: "can we just not have an
    #   info master panel in the master data?" — so their own people can correct
    #   the Gujarati on the ⓘ panels without a developer.
    ("Screen instructions",
     "The ⓘ panels every screen carries, in Gujarati",
     "panel_text"),
]


def master_data_for(role=None):
    """
    The entries behind the Master data tile.

    ⚠ RETURNS ONE LIST, NOT TWO. It used to return (in_admin, own) because half
      the tables had no screen; nothing opens Django Admin from this page any
      more, so the split has nothing left to describe.

    ⚠ EACH ENTRY IS FILTERED BY THE PERMISSION THAT OPENS IT, one at a time,
      rather than the page being all-or-nothing. A purchase manager who
      maintains vendors sees Materials, Vendors and Construction activities; the
      company's own profile and the Users screen are not shown to them, because
      the views behind those two would refuse.

    ⚠ Saahil asked for company data to sit here rather than in the header —
      "Have Company Data under master data itself".
    """
    def allowed(key):
        return role is None or role_can(role, key)

    return [
        {"title": title, "blurb": blurb, "url": reverse(url_name)}
        for title, blurb, url_name in _ENTRIES
        if allowed(_ENTRY_PERMS[url_name])
    ]


def stats_for(role):
    """
    A handful of live figures for the home screen, each shown only to a role
    that can open the screen it counts. Five cheap COUNT queries at most — the
    figures are the ones somebody checks first thing in the morning.
    """
    from datetime import date
    from django.db.models import Q
    out = []
    if role_can(role, "projects.view"):
        from projects.models import Project
        out.append(("Live projects", Project.objects.filter(status__in=Project.ONGOING).count(),
                    reverse("project_list"), "#2E5C9A"))
    if role_can(role, "register.view"):
        from projects.bom_models import PurchaseOrder
        out.append(("Orders awaiting approval",
                    PurchaseOrder.objects.filter(status=PurchaseOrder.Status.DRAFT).count(),
                    reverse("po_register") + "?status=draft", "#8A6D1F"))
    if role_can(role, "tasks.view"):
        from tasks.models import Subtask
        today = date.today()
        # Overdue = open and its planned finish is behind us. The finish is
        # start + days, so narrow in SQL to open rows and finish in Python.
        overdue = sum(1 for t in Subtask.objects.filter(status__in=["open", "blocked"])
                      .only("start", "days", "status") if t.planned_end < today)
        out.append(("Tasks overdue", overdue, reverse("task_board"), "#C55A11"))
    if role_can(role, "compliance.view"):
        from compliance.models import ComplianceDocument
        soon = date.today()
        from datetime import timedelta
        n = ComplianceDocument.objects.filter(
            expires_on__isnull=False, expires_on__lte=soon + timedelta(days=60)).count()
        out.append(("Documents expiring in 60 days", n, reverse("compliance_timeline"), "#A32D2D"))
    if role_can(role, "sales.view"):
        from sales.models import Unit
        from sales.calc import bulk_unit_status
        units = list(Unit.objects.filter(is_active=True, project__status__in=["won"]).only("id"))
        status = bulk_unit_status(units)
        free = sum(1 for u in units if status.get(u.id) in ("available", "cancelled"))
        out.append(("Units available", free, reverse("sales_units"), "#0F766E"))
    return out
