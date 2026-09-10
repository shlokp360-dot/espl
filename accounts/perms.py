"""
WHO MAY DO WHAT — the agreed matrix, as data.

>>> ANCHOR: PERMS-MATRIX <<<

WHAT THIS FILE IS
    The table Saahil filled in with the customer in the room, screen by screen,
    written out as one dictionary. Changing a rule is one line here. Nothing
    else in the project decides who may do anything.

⚠ WHY DATA AND NOT `if role == "admin"` SCATTERED THROUGH THE VIEWS
    The same reason `hub.py` holds the launchpad tiles as a list: a rule you can
    read in one place can be checked against the agreed table in one sitting.
    Twenty scattered conditionals cannot, and the twenty-first gets forgotten.

⚠ A PERMISSION IS ONLY REAL IF THE ROLE CAN REACH THE SCREEN THE BUTTON IS ON.
    That sentence cost four corrections while the matrix was being agreed —
    an Accountant ticked for "post purchase orders" who could not open the BOM
    the button lives on, a Site engineer ticked for "mark delivered" who could
    not open a purchase order. When a key is added here, check where its button
    actually sits.

⚠ THE KEYS ARE SPLIT FINER THAN THE TABLE'S ROWS IN TWO PLACES, DELIBERATELY:

    po.view vs po.edit_draft   The table has one row, "View a PO · edit a draft
                               PO · PDF", ticked for the Site engineer. Reading
                               every value on a document is what Saahil asked
                               for — "Site engineer should know the values in
                               PO, all values" — but editing somebody's draft
                               order is not the same act. Site gets the first
                               and not the second. FLAGGED FOR CONFIRMATION.

    register.view vs .export   The bulk status box is ticked for Site; the Excel
                               and the zip of PDFs are not. Same screen, two
                               different permissions.


>>> ANCHOR: PERMS-ADD-A-ROLE <<<
==============================================================================
ADDING A ROLE, OR CHANGING WHAT ONE CAN DO
==============================================================================

⚠ THIS COSTS NOTHING AT RUNTIME. MATRIX is a dictionary built once when the
  process starts, and a check is a dict lookup and a set membership test — no
  query, no file, nanoseconds. The role itself arrives on the profile that is
  already joined onto the user (accounts.backends.LoginBackend.get_user), so the
  permission layer adds ZERO queries to any screen. There is ONE copy of every
  screen, shared by every role; nothing here is duplicated per person.

TO ADD A ROLE — about fifteen minutes, three files, one test run:

  1. accounts/models.py   Add one line to `Role`. Then
                          `python manage.py makemigrations accounts` writes an
                          AlterField for the choices; it changes no data and no
                          column, but CI's `makemigrations --check` will fail
                          without it.

  2. accounts/perms.py    Add the new role to every MATRIX line it holds — one
                          word per line. A role named nowhere in MATRIX can sign
                          in and see an empty launchpad, which is a legitimate
                          state (Compliance is exactly that today).

  3. accounts/test_matrix.py
                          Add it to EVERYBODY and to the SCREENS / ACTIONS rows.
                          That file is the specification written out by hand; it
                          will then prove the new role reaches what was agreed
                          and nothing else.

  Then `python manage.py test`. Nothing else in the project needs touching —
  the launchpad, the Master data page, the button-hiding and the bulk box all
  read this file.

TO CHANGE WHAT AN EXISTING ROLE MAY DO: one word in MATRIX, one word in
  test_matrix.py, run the suite. The two-places rule is deliberate — a behaviour
  change should be made twice by somebody who noticed they were doing it.

⚠ WHAT WOULD IT TAKE TO LET THE ADMIN INVENT ROLES FROM A SCREEN?
  A `Role` table, a `RolePermission` table seeded from this dictionary, a
  tick-grid screen, and a rewrite of the test to check the seed rather than the
  code. Roughly a day. It was OFFERED AND TURNED DOWN — Saahil: "the admin
  should be able to add new users based on these defined roles for new hires."
  The reason to keep it as it is: this file can be read against the agreed table
  in one sitting, and a mis-ticked box on a screen is silent where a code change
  is reviewed. If that decision is ever revisited, the seed data is right here
  and the migration writes itself.
"""
from functools import wraps

from django.http import HttpResponseForbidden

from accounts.models import Role, role_of

A, PM, PUR, ACC, SITE, COMP = (
    Role.ADMIN, Role.PROJECT_MANAGER, Role.PURCHASE,
    Role.ACCOUNTANT, Role.SITE, Role.COMPLIANCE,
)

#: permission key → the roles that hold it. Admin is in every line on purpose:
#: "Admin sees everything" is a rule, not an exception handled elsewhere.
MATRIX = {
    # ---- projects ------------------------------------------------------
    "projects.view":     {A, PM, PUR, ACC},
    "projects.edit":     {A, PM},              # create, edit, and the status control

    # ---- the estimate --------------------------------------------------
    "boq.view":          {A, PM},
    "boq.edit":          {A, PM},

    # ---- the bill of materials ----------------------------------------
    # ⚠ SITE WAS ADDED HERE AND THEN TAKEN BACK OUT, AND THE REVERSAL IS THE
    #   POINT. Giving the engineer the stock column first meant giving them the
    #   whole buying grid read-only — order quantities, vendors, vendor rates,
    #   PO values, variance. Saahil's answer when that was put to him was to
    #   build the narrow screen instead: "your suggestion of having only a BOM
    #   stock view is good."
    #
    #   So the full grid is Admin, PM and Purchase again, and `bom.stock` below
    #   opens a screen of its own that carries no money at all.
    "bom.view":          {A, PM, PUR},
    "bom.edit":          {A, PM, PUR},
    # ⚠⚠ THE NARROWEST KEY IN THE MATRIX, AND DELIBERATELY SO. Saahil: "if the
    #   site engineer can edit the site stock in the BOM table… they are not
    #   allowed to change anything else or place an order, but they can just
    #   maintain the stock for that particular BOM line."
    #
    #   It exists because `bom.edit` is one key covering quantities, rates,
    #   vendors AND the button that raises purchase orders. Handing that to the
    #   person counting bags on site would hand them the money as well.
    #
    #   ⚠ IT OPENS A SCREEN OF ITS OWN, NOT THE BOM. `stock_screen` lists code,
    #     material, unit, stock, threshold and the low flag — and no money, no
    #     vendors and no quantities anybody has ordered.
    #
    #   ⚠ THE VIEW STILL ENFORCES IT FIELD BY FIELD — see _apply_edits. The
    #     narrow screen is what somebody sees; the field check is what makes it
    #     true. A stale page and a crafted POST both bypass a template.
    "bom.stock":         {A, PM, PUR, SITE},
    "bom.generate":      {A, PM, PUR},
    "bom.post":          {A, PM, PUR},         # ⚠ Accountant was ticked and then
                                               #   withdrawn: "lets not make him
                                               #   post POs, but allow him to
                                               #   change status."

    # ---- a purchase order ----------------------------------------------
    "po.view":           {A, PM, PUR, ACC, SITE},
    "po.edit_draft":     {A, PM, PUR, ACC},
    "po.discard":        {A, PM, PUR},
    "po.approve":        {A, PM},              # ⚠ the moment money is committed
    "po.deliver":        {A, PM, PUR, SITE},   # the person who saw the lorry
    "po.pay":            {A, PM, ACC},

    # ---- the cross-project register ------------------------------------
    "register.view":     {A, PM, PUR, ACC, SITE},
    "register.export":   {A, PM, PUR, ACC},

    # ---- master data ----------------------------------------------------
    "masters.view":      {A, PM, PUR, ACC},
    "masters.edit":      {A, PM, PUR, ACC},
    "masters.import":    {A, PM, PUR, ACC},    # ⚠ one file rewrites 705 rates;
                                               #   his call, recorded as his call

    # ---- task management -------------------------------------------------
    #
    # ⚠ THREE KEYS, AND TWO OF THEM ARE HELD BY EVERYBODY TODAY. That is not a
    #   waste of a line: they are three different acts, and only one of them is
    #   about being a manager.
    #
    #     tasks.view    reading the plan. A site engineer who cannot see what
    #                   comes after his own row cannot see what he is holding up,
    #                   and a purchase manager reads it to know when material is
    #                   actually wanted. Same instinct as "Site engineer should
    #                   know the values in PO, all values".
    #     tasks.mine    ticking YOUR OWN subtask done or blocked, and typing the
    #                   reason. The person who did the work is the only one who
    #                   knows it is finished — "the engineers tick is final".
    #                   ⚠ WHOSE row it is, is checked in the view, not here. The
    #                     matrix answers "may this role tick at all", never
    #                     "may this person tick that particular line".
    #     tasks.manage  creating header tasks, assigning them, moving dates,
    #                   milestones — anybody's row, not just your own.
    #
    #   Splitting them now costs three lines. Discovering later that "tasks" was
    #   one key means going back through every screen to work out which half of
    #   it each rule meant.
    "tasks.view":        {A, PM, PUR, ACC, SITE, COMP},
    "tasks.mine":        {A, PM, PUR, ACC, SITE, COMP},
    "tasks.manage":      {A, PM},

    # ---- ours, and only ours -------------------------------------------
    "company.manage":    {A},                  # company profile and company rates
    "users.manage":      {A},
    "analytics.view":    {A},                  # not built

    # ---- compliance — designed, not built ------------------------------
    "compliance.view":   {A, PM, ACC, SITE, COMP},
    "compliance.upload": {A, COMP},
    # ⚠ A THIRD KEY, AND IT IS A DIFFERENT ACT FROM UPLOADING. Editing the
    #   checklist changes what EVERY project is measured against — one new line
    #   makes twelve sites non-compliant at once. Same two roles today; the
    #   split exists so it can be narrowed without touching the upload rule.
    "compliance.master": {A, COMP},

    # ⚠ ANCHOR: INFO-PANELS — writing the Gujarati on the ⓘ panels. ADMIN ALONE,
    #   deliberately narrower than `masters.edit`, which Project manager,
    #   Purchase and Accountant all hold. This is not a list of materials: it is
    #   what the whole company reads as instructions, in a language most of the
    #   office cannot check. Saahil's call when the two were put to him.
    "help.edit": {A},
}


def role_can(role, key):
    """Whether a ROLE holds a permission. The only place MATRIX is read."""
    try:
        holders = MATRIX[key]
    except KeyError:  # pragma: no cover - a typo in a decorator, not a state
        raise KeyError(
            f"{key!r} is not in the permission matrix. Add it there rather than "
            "inventing a rule in a view.")
    return role in holders


def can(user, key):
    """
    Whether a USER may do something.

    ⚠ A SUPERUSER IS NOT AUTOMATICALLY ALLOWED. Django's `is_superuser` opens
      Admin, which is the emergency exit; it should not silently satisfy a
      business rule about approving purchase orders. The one exception is
      managing users, so that a superuser can always repair a locked-out
      installation — see `accounts.views`.
    """
    if not user or not user.is_authenticated:
        return False
    return role_can(role_of(user), key)


def requires(key):
    """
    The decorator every protected view carries.

    ⚠ 403, NOT A REDIRECT. Sending somebody to a screen they can open instead
      hides the refusal; a Purchase manager who clicks Approve and lands quietly
      on the launchpad will click it again tomorrow. The templates hide what a
      role cannot use, so reaching this at all means somebody typed an address
      or followed a stale link — and should be told.
    """
    def decorate(view):
        @wraps(view)
        def guarded(request, *args, **kwargs):
            if not can(request.user, key):
                return HttpResponseForbidden(
                    "Your role does not include this. Ask an Admin if you think it should.")
            return view(request, *args, **kwargs)
        guarded.permission_key = key      # read by the test that walks the matrix
        return guarded
    return decorate


def requires_any(*keys):
    """
    The door opens if ANY of these keys is held. What happens inside is then
    decided field by field.

    ⚠ THIS IS NOT A WEAKER `requires`, AND IT MUST NOT BECOME ONE. It exists for
      exactly one shape: a single POST address that writes several things, where
      different roles may write different subsets of them. The BOM grid is that
      shape — it is one form, so every button submits the whole page, and the
      site engineer's stock figure arrives in the same request as the vendor
      rates they may not touch.

      The door being open therefore says nothing about what gets written. See
      ANCHOR: BOM-STOCK-ONLY — `_apply_edits` refuses each field on its own, and
      that is the safeguard. If you reach for this decorator anywhere the view
      does NOT then check per field, you have opened a hole.
    """
    if not keys:  # pragma: no cover - a programming mistake, not a state
        raise ValueError("requires_any needs at least one permission key.")

    def decorate(view):
        @wraps(view)
        def guarded(request, *args, **kwargs):
            if not any(can(request.user, key) for key in keys):
                return HttpResponseForbidden(
                    "Your role does not include this. Ask an Admin if you think it should.")
            return view(request, *args, **kwargs)
        # The narrowest key, so anything walking the matrix still finds a rule.
        guarded.permission_key = keys[0]
        guarded.permission_keys = keys
        return guarded
    return decorate
