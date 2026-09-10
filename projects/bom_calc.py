"""
Every derived number on the BOM screen. This is the only file that computes them.

WHAT THIS FILE IS FOR
    One function per figure the BOM shows. Nothing else in the codebase should
    calculate any of these — not a view, not a template, not the Excel export,
    not purchase-order generation. They all call in here.

WHY THAT MATTERS MORE THAN IT SOUNDS
    In the HTML prototype "quantity to order" ended up computed in three
    separate places. In Django it would naturally become four — the screen, the
    export, the PO generator, the tests. Change the rule once and you have
    silently broken three of them, and the breakage shows up as a wrong number
    on a real purchase order weeks later.

⚠⚠ EVERY FIGURE HERE IS EX-GST. GST APPEARS ONLY ON A PURCHASE ORDER.
    The BOQ adds GST once, at the very end, to the whole estimate. So a trade's
    amount (rate x BUA) is a PRE-GST number, and that same number becomes the
    activity's budget reserve. Planned, used and variance must therefore also
    exclude GST, or you are comparing a price against a price-plus-tax.

    This was got wrong once and it mattered: RCC reported 99.3% of budget
    consumed when the true figure was 84.2% — "at the ceiling" versus
    "twenty-five lakh spare". See PROJECT-CONTEXT.md, 5 Aug 2026.

WHERE THE QUANTITIES COME FROM
    approved / in draft / received are NOT stored on the BOM line. They are
    summed from the purchase orders each time, so the two can never disagree.

⚠ ONE THING THAT LOOKS LIKE CACHING AND IS NOT
    Several figures need the same three sums. suggested_order_qty needs approved
    and in-draft; order_qty needs the suggestion; po_value needs the order
    quantity. Called one after another, each re-ran every query underneath it —
    fourteen queries per row, measured, so a six-line activity cost 119.

    So the functions now ACCEPT those sums as optional arguments, and
    line_figures works them out once and passes them down. The formulas are
    untouched, and calling any function on its own still queries exactly as
    before.

    This is NOT the forbidden thing. The forbidden thing is storing approved or
    in-draft ON the BomLine, where it would be a second copy that can drift from
    the purchase orders. These values live for the length of one calculation and
    then vanish. Nothing can read a stale one, because there is nowhere to read
    it from.
"""
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import DecimalField, ExpressionWrapper, F, Sum, Value
from django.db.models.functions import Coalesce

ZERO = Decimal("0")
_SUM = DecimalField(max_digits=18, decimal_places=3)
_MONEY = DecimalField(max_digits=18, decimal_places=4)

# Rupees to the paisa, rounded half-up.
#
# ⚠ MONEY IS ROUNDED WHERE IT IS CALCULATED, NEVER IN A TEMPLATE. The money
#   columns in the database are all 2dp, but derived figures were not rounded at
#   all, so a division or a percentage grew a long tail. The screen filters hid
#   it; Django Admin, the Excel export and the PDF would not have. Saahil found
#   five-decimal figures on his own screen, and a tax document showing one is
#   not defensible.
_PAISA = Decimal("0.01")


# ⚠ "NOBODY HAS LOOKED YET", WHICH IS NOT "LOOKED AND FOUND NOTHING". A rate of
#   None is a real answer — this vendor has never been paid for this material —
#   so None cannot double as the default that means "go and fetch it". See
#   effective_vendor_rate.
_UNSET = object()


def _money(value):
    return Decimal(value).quantize(_PAISA, rounding=ROUND_HALF_UP)


def _sum(queryset, field="quantity"):
    """Total a column, returning 0 rather than None when there are no rows."""
    return queryset.aggregate(
        total=Coalesce(Sum(field), Value(ZERO), output_field=_SUM)
    )["total"]


# Databases limit how many values one query may carry. SQLite's old limit was
# 999; a 3,200-line BOM would sail past it. Asking in batches costs one extra
# query per batch and works everywhere.
_BATCH = 900


def _batched(items, size=_BATCH):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def bulk_quantities(lines):
    """
    Approved, in-draft and received for MANY lines, in three queries instead of
    three per line.

    >>> ANCHOR: BOM-CALC-BULK <<<
    WHY THIS EXISTS
        A real project has sixteen activities and one to two hundred lines under
        each. Asking the database three questions per line meant 618 queries to
        draw one screen and over 8,000 — nine seconds — to press Post POs.
        Measured on a 3,200-line project, not guessed.

        The database can answer "the approved quantity for ALL of these lines"
        just as easily as it answers it for one. This asks that way.

    ⚠ THIS IS NOT A SECOND COPY OF ANYTHING.
        The rule that matters — the BOM stores no approved / in-draft / received
        of its own — is untouched. These totals are still summed from the
        purchase orders, still every time they are needed. They are handed
        around inside one calculation and then thrown away. There is nowhere for
        a stale figure to survive, because nothing is written anywhere.

        The formulas in this file are not changed by any of it. They are given
        numbers instead of fetching them.

    Returns {line_id: {"approved": …, "draft": …, "received": …}}.
    """
    from .bom_models import PurchaseOrder, PurchaseOrderLine, Receipt

    ids = [line.id for line in lines]
    totals = {line_id: {"approved": ZERO, "draft": ZERO, "received": ZERO} for line_id in ids}
    if not ids:
        return totals

    committed = [PurchaseOrder.Status.APPROVED, PurchaseOrder.Status.DELIVERED,
                 PurchaseOrder.Status.PAID]

    for batch in _batched(ids):
        for line_id, total in (PurchaseOrderLine.objects
                               .filter(bom_line_id__in=batch, purchase_order__status__in=committed)
                               .values("bom_line_id").annotate(total=Sum("quantity"))
                               .values_list("bom_line_id", "total")):
            totals[line_id]["approved"] = total

        for line_id, total in (PurchaseOrderLine.objects
                               .filter(bom_line_id__in=batch,
                                       purchase_order__status=PurchaseOrder.Status.DRAFT)
                               .values("bom_line_id").annotate(total=Sum("quantity"))
                               .values_list("bom_line_id", "total")):
            totals[line_id]["draft"] = total

        for line_id, total in (Receipt.objects
                               .filter(po_line__bom_line_id__in=batch)
                               .values("po_line__bom_line").annotate(total=Sum("quantity"))
                               .values_list("po_line__bom_line", "total")):
            totals[line_id]["received"] = total

    return totals


def bulk_committed_value(lines):
    """
    The MONEY already committed to vendors, per line, in one query per batch.

    >>> ANCHOR: BOM-CALC-COMMITTED <<<
    WHY THIS EXISTS AT ALL
        Until now the BOM could say how much a line was PLANNED to cost, and how
        much it was ABOUT to cost — po_value, which is order_qty x vendor rate.
        But posting clears the typed order quantity, so po_value drops to zero
        the instant an order is raised. It means "about to be ordered", not "has
        been ordered", and there was no rupee figure anywhere for the latter.

        That was survivable while the reserve covered material only. Now that a
        work order to a labour contractor draws on the SAME activity reserve,
        "how much of this activity have I actually committed?" is the question
        people will ask, and the screen could not answer it.

    WHAT COUNTS
        Lines on documents that are APPROVED, DELIVERED or PAID — the same three
        statuses approved_qty uses, because those are the ones we are committed
        to. A DRAFT is excluded: it is not a promise to anybody.

    HOW IT IS VALUED
        (quantity x rate) minus the line discount — the line's TAXABLE value, at
        the rate frozen onto that document, EX-GST.

        Ex-GST because the reserve is ex-GST and GST is recoverable; mixing them
        would report an activity as overspent when it was not. That mistake has
        been made here once already: RCC read 99.3% of budget when the truth was
        84.2%.

        At the document's own rate, not the planning rate, because this figure
        answers what we agreed to pay — not what we hoped to.

    ⚠ THE BILL-LEVEL DEDUCTION IS DELIBERATELY NOT INCLUDED.
        It is applied after GST on the whole document and cannot honestly be
        attributed to one activity's lines. The screen should say so rather than
        imply the figure nets out.

    ⚠ ONE QUERY PER BATCH, NOT ONE PER LINE. A per-row version of this is
      exactly the shape that once cost 8,000 queries and nine seconds. The
      discount is applied in SQL so the database returns the finished figure.

    Returns {line_id: Decimal}.
    """
    from .bom_models import PurchaseOrder, PurchaseOrderLine

    ids = [line.id for line in lines]
    totals = {line_id: ZERO for line_id in ids}
    if not ids:
        return totals

    committed = [PurchaseOrder.Status.APPROVED, PurchaseOrder.Status.DELIVERED,
                 PurchaseOrder.Status.PAID]

    # Two sums, one query, and THE DIVISION HAPPENS IN PYTHON.
    #
    # ⚠ DO NOT "SIMPLIFY" THIS INTO qty * rate * (1 - discount/100).
    #   That form was written first and silently dropped every discount:
    #   SQLite integer-divides 10 / 100 to 0, so the multiplier came out as 1.
    #   PostgreSQL — which this will run on in production — divides exactly and
    #   would have got it right. A figure that differs between the developer's
    #   laptop and the client's server is worse than one that is simply wrong,
    #   because the tests pass on the machine that made the change.
    #
    #   Summing whole rupees in SQL and dividing once in Python is exact on
    #   every backend, and still one query.
    base = ExpressionWrapper(F("quantity") * F("rate"), output_field=_MONEY)
    weighted = ExpressionWrapper(F("quantity") * F("rate") * F("discount_pct"),
                                 output_field=_MONEY)

    for batch in _batched(ids):
        for line_id, gross, discounted in (
                PurchaseOrderLine.objects
                .filter(bom_line_id__in=batch, purchase_order__status__in=committed)
                .values("bom_line_id")
                .annotate(gross=Sum(base), discounted=Sum(weighted))
                .values_list("bom_line_id", "gross", "discounted")):
            totals[line_id] = _money((gross or ZERO) - (discounted or ZERO) / Decimal("100"))

    return totals


def boq_rows(estimate):
    """
    An estimate's lines, loaded once and wired so every figure on them is free.

    >>> ANCHOR: BOQ-SCREEN <<<
    ⚠ THE BULK PATH FOR THE BOQ, and it exists for exactly the reason
      figures_for() exists for the BOM.

      EstimateLine.amount walks back to estimate.project for the built-up area,
      and EstimateLine.share asks the estimate for its composite rate — which
      re-queries every line, for every line. Rendering an 18-trade estimate cost
      38 extra queries because of it. Measured on the sweep, not guessed.

      This loads the lines once, hands each one the estimate object it already
      has, and works the composite out in a single pass. The formulas are
      untouched — they live on the model, and this only stops them asking the
      database the same question eighteen times.

    ⚠ NOT CACHING. Nothing is written anywhere; these values live on in-memory
      objects for the length of one request. The forbidden thing is STORING a
      derived figure where it can drift from what it was derived from.
    """
    project = estimate.project
    lines = list(estimate.lines.all())

    # One pass for the composite, then hand it to the estimate the lines will ask.
    estimate._composite = sum((line.rate for line in lines), ZERO)
    for line in lines:
        # The reverse FK Django will not fill in by itself. Without it, every
        # line fetches its own copy of the estimate, and then of the project.
        line.estimate = estimate

    return lines


def reserve_changes(project, rates_before):
    """
    What changing a BOQ rate did to the budgets underneath it.

    >>> ANCHOR: BOM-CALC-RESERVE <<<
    An activity's reserve is a LIVE LINK to its estimate line — rate × BUA, read
    fresh every time — so editing a rate moves the number the site team is
    measured against. Saahil asked, when the live link was chosen on 4 Aug, that
    editing a saved BOQ warn about exactly that.

    ⚠ ONE IMPLEMENTATION, TWO CALLERS. This used to live inside
      admin.py's save_formset, so it only fired in Admin. The BOQ screen needs
      the identical warning, and two copies would say different things within a
      month. Each caller formats and shows it; only this decides what happened.

    ⚠ IT REPORTS FIGURES, NOT A CAUTION. "This may affect the BOM" trains people
      to click past it. The old reserve, the new one, and where planned value now
      sits against both is something somebody can actually act on.

    `rates_before` is {estimate_line_name: rate} read BEFORE the save.
    Returns [] when the project has no BOM — until then an estimate is just an
    estimate and there is nothing downstream to disturb.
    """
    bom = getattr(project, "bom", None)
    if bom is None or not rates_before:
        return []

    from .models import Activity

    changes = []
    for line in project.estimate.lines.all():
        before = rates_before.get(line.name)
        if before is None or before == line.rate:
            continue

        activity = Activity.objects.filter(name=line.name).first()
        if activity is None or not bom.lines.filter(activity=activity).exists():
            continue

        totals = activity_totals(bom, activity)
        old_reserve = before * project.bua_sqft
        planned = totals["planned_value"]
        changes.append({
            "name": line.name,
            "old_rate": before,
            "new_rate": line.rate,
            "old_reserve": old_reserve,
            "new_reserve": totals["reserve"],
            "planned_value": planned,
            "was_pct": (planned / old_reserve * 100) if old_reserve else ZERO,
            "now_pct": totals["percent_used"] * 100,
        })
    return changes


def describe_reserve_change(change):
    """The same sentence wherever the warning is shown."""
    from .templatetags.inr import rupees
    return (f"{change['name']}: reserve moves ₹{rupees(change['old_reserve'])} → "
            f"₹{rupees(change['new_reserve'])}. Planned value is "
            f"₹{rupees(change['planned_value'])}, which was {change['was_pct']:.1f}% of the "
            f"reserve and is now {change['now_pct']:.1f}%.")


def bulk_stock_echoes(lines):
    """
    The same material carrying site stock on more than one line of one BOM.

    >>> ANCHOR: STOCK-ECHO <<<
    WHAT THIS IS, AND WHAT IT IS NOT

        It is NOT a double-count bug. Per-line stock is deliberate: Saahil's
        rule is that stock is a user input and the figures are an ALLOCATION —
        "if he adds stock in material line 1, that should add up to header, and
        if there is stock in material line 2, even that should add up, dual
        entry is the right way."

        So two lines each holding 100 bags means 200 bags on site, split
        between two trades. That is correct and must keep working.

        What cannot be told apart from it is the mistake: one pile of 100 bags,
        typed as 100 on both lines because both trades can see it. The
        arithmetic is identical; only the person knows which they meant.

    SO THIS SAYS WHERE ELSE THE MATERIAL HAS STOCK, AND LETS THEM DECIDE.
        No banner, no block, no automatic correction — the same shape as
        bulk_draft_conflicts, and for the same reason: the system can see that
        two numbers exist, and cannot possibly know whether they are two piles
        or one counted twice.

    ⚠ ONE QUERY PER BATCH, never one per line. This runs on every BOM page load
      and a project holds thousands of lines.

    Returns {line_id: {"total": Decimal, "elsewhere": [(activity_name, qty), …]}}
    for lines whose material carries stock on another line too. Lines with no
    echo are left out, so an empty dict means there is nothing to say.
    """
    lines = list(lines)
    if not lines:
        return {}

    bom_ids = {line.bom_id for line in lines}
    # Every line in these BOMs that has stock on it — one query, whatever the
    # size of the screen.
    from .bom_models import BomLine
    stocked = list(BomLine.objects
                   .filter(bom_id__in=bom_ids, stock_qty__gt=0)
                   .select_related("activity")
                   .values("id", "bom_id", "material_id", "stock_qty",
                           "activity__name", "activity__sort_order"))

    by_material = {}
    for row in stocked:
        by_material.setdefault((row["bom_id"], row["material_id"]), []).append(row)

    out = {}
    for line in lines:
        siblings = by_material.get((line.bom_id, line.material_id), [])
        if len(siblings) < 2:
            continue
        others = [(row["activity__name"], row["stock_qty"])
                  for row in sorted(siblings, key=lambda r: (r["activity__sort_order"], r["id"]))
                  if row["id"] != line.id]
        if not others:
            continue
        out[line.id] = {
            "total": sum((row["stock_qty"] for row in siblings), ZERO),
            "elsewhere": others,
        }
    return out


def bulk_draft_conflicts(lines, quantities=None):
    """
    Live drafts that no longer agree with the plan behind them.

    >>> ANCHOR: DRAFT-CONFLICT <<<
    THE PRINCIPLE THIS EXISTS TO SERVE
        The BOM is a plan. A purchase order is a document. Changing the plan must
        never silently rewrite a document that has already been raised — but it
        must not leave the two quietly disagreeing either. So: say the document
        is out of step, and offer to fix it. Never both, never neither, and never
        automatically.

    TWO WAYS THEY CAN DISAGREE

      vendor      The line now names a different vendor — or none at all — while
                  a draft is already sitting with the old one. The draft is not
                  wrong; it is simply no longer what the plan says. The remedy is
                  to lift THAT LINE off THAT DRAFT, leaving the other five
                  materials on it alone, which is what remove_draft_line does.

      over-plan   The plan was cut below what the drafts are already ordering.
                  Approved quantities are already committed and cannot be
                  reconsidered here, so what matters is whether the DRAFTS now
                  exceed what the plan still needs:

                      remaining = planned − approved
                      trouble   = draft > remaining

    ⚠ WHY THIS IS A PROPERTY AND NOT AN EVENT. It would have been easier to catch
      the moment somebody changes a vendor and warn then. That misses every other
      route to the same state — a bulk edit, an import, two people at once, a
      change made before this check existed — and the warning is lost the moment
      the page reloads. Computed from the data every time, it cannot be dodged
      and cannot go stale.

    ⚠ ONE QUERY PER BATCH. Never one per line.

    Returns {line_id: {"vendor": [...], "over_planned": Decimal}} for the lines
    in trouble only. Lines that agree with their drafts are left out entirely, so
    an empty dict means all is well.
    """
    from .bom_models import PurchaseOrder, PurchaseOrderLine

    lines = list(lines)
    ids = [line.id for line in lines]
    if not ids:
        return {}

    by_id = {line.id: line for line in lines}
    totals = bulk_quantities(lines) if quantities is None else quantities
    conflicts = {}

    for batch in _batched(ids):
        rows = (PurchaseOrderLine.objects
                .filter(bom_line_id__in=batch,
                        purchase_order__status=PurchaseOrder.Status.DRAFT)
                .values("id", "bom_line_id", "quantity",
                        "purchase_order_id", "purchase_order__number",
                        "purchase_order__vendor_id", "purchase_order__vendor__name"))

        for row in rows:
            line = by_id[row["bom_line_id"]]
            if line.vendor_id == row["purchase_order__vendor_id"]:
                continue
            entry = conflicts.setdefault(line.id, {"vendor": [], "over_planned": ZERO})
            entry["vendor"].append({
                "po_line_id": row["id"],
                "order_id": row["purchase_order_id"],
                "number": row["purchase_order__number"],
                "vendor_name": row["purchase_order__vendor__name"],
                "quantity": row["quantity"],
            })

    for line in lines:
        sums = totals.get(line.id) or {"approved": ZERO, "draft": ZERO}
        if not sums["draft"]:
            continue
        remaining = line.planned_qty - sums["approved"]
        if sums["draft"] > remaining:
            entry = conflicts.setdefault(line.id, {"vendor": [], "over_planned": ZERO})
            entry["over_planned"] = sums["draft"] - max(ZERO, remaining)

    return conflicts


def committed_value(line):
    """
    One line's committed money. Prefer bulk_committed_value for a whole screen —
    see the note there about why per-row versions of this are dangerous.
    """
    return bulk_committed_value([line])[line.id]


def figures_for(lines):
    """
    Every derived figure for a whole list of lines, the cheap way.

    Use this instead of calling line_figures in a loop. It is the same
    arithmetic — it just asks the database three questions in total rather than
    three per line. The screen, the activity roll-ups and purchase-order
    generation all go through here.
    """
    lines = list(lines)
    totals = bulk_quantities(lines)
    money = bulk_committed_value(lines)
    # ⚠ .get() WOULD BE WRONG HERE. A line with no captured rate is absent from
    #   the dict, and `.get(id)` returning None is exactly the "looked and found
    #   nothing" answer we want — but only because the key is genuinely absent
    #   rather than never fetched. See _UNSET.
    rates = bulk_vendor_rates(lines)
    return [line_figures(line, quantities=totals.get(line.id), committed=money.get(line.id),
                         captured=rates.get(line.id))
            for line in lines]


# ---------------------------------------------------------------- quantities

def approved_qty(line):
    """
    How much has been committed to a vendor.

    Counts APPROVED, DELIVERED and PAID — everything past the point of
    commitment. A draft is not committed and is counted separately.
    """
    from .bom_models import PurchaseOrder
    return _sum(line.po_lines.filter(purchase_order__status__in=[
        PurchaseOrder.Status.APPROVED,
        PurchaseOrder.Status.DELIVERED,
        PurchaseOrder.Status.PAID,
    ]))


def draft_qty(line):
    """
    How much is sitting on purchase orders that have not been approved.

    >>> ANCHOR: PO-INVARIANT <<<
    This IS the sum of the draft PO lines — not a stored figure kept in step
    with them. Delete a draft and the quantity is simply no longer there to add
    up; nothing has to remember to give it back.
    """
    from .bom_models import PurchaseOrder
    return _sum(line.po_lines.filter(purchase_order__status=PurchaseOrder.Status.DRAFT))


def received_qty(line):
    """
    How much has actually arrived on site.

    Measures what was DELIVERED, not what was consumed — there is no
    goods-receipt inspection step, so this cannot see wastage or breakage.
    """
    from .bom_models import Receipt
    return _sum(Receipt.objects.filter(po_line__bom_line=line))


def suggested_order_qty(line, approved=None, draft=None):
    """
    What the system suggests ordering.

    >>> ANCHOR: BOM-CALC-TO-ORDER <<<
    planned - approved - in draft - stock, floored at zero.
    Changing this changes the BOM screen, the Excel export and PO generation.

    Drafts are subtracted deliberately. Without that, a quantity sitting on an
    unapproved PO would still look un-ordered, and someone would raise a second
    order for material already on its way.

    ⚠ KNOWN GAP: stock is held per material per site, but this subtracts it on
    every line. A material appearing under two activities subtracts the same
    stock twice and therefore under-orders. Visible in the prototype with cement
    on two RCC lines. Undecided — see PROJECT-CONTEXT.md.

    `approved` and `draft` may be handed in when the caller has already summed
    them. Leave them out and they are summed here, exactly as before.
    """
    approved = approved_qty(line) if approved is None else approved
    draft = draft_qty(line) if draft is None else draft
    return max(ZERO, line.planned_qty - approved - draft - line.stock_qty)


def order_qty(line):
    """
    The quantity that will actually be ordered. NOTHING UNLESS SOMEBODY TYPED IT.

    >>> ANCHOR: BOM-CALC-TO-ORDER <<<
    ⚠ THIS SUPERSEDES THE ORIGINAL RULE. Blank used to mean "use the
    suggestion", so pressing Post POs ordered every line at its suggested
    quantity. Saahil's call, 9 Aug 2026, and he is right about why: a real
    project is sixteen activities of three to four hundred materials, so that
    button would have ordered THE ENTIRE PROJECT in one press. Nobody would have
    meant to do it and everybody would have been able to.

    The suggestion has not gone away — see suggested_order_qty. It still shows
    on every row as "here is what is still outstanding". It has stopped being an
    instruction and become advice, which is the correct relationship between a
    computer and a purchase order.

    Posting clears what was typed, so the next round starts from zero again
    rather than silently repeating the last order.
    """
    if line.order_qty_override is None:
        return ZERO
    return max(ZERO, line.order_qty_override)


def is_overridden(line, suggested=None):
    """
    True when the typed quantity is not the suggested one.

    Not a problem — ordering 20 of a planned 150 is normal, and so is ordering
    extra. It only drives a small note on screen so the difference is visible
    rather than looking like a mistake.
    """
    if line.order_qty_override is None:
        return False
    suggested = suggested_order_qty(line) if suggested is None else suggested
    return line.order_qty_override != suggested


def is_below_threshold(line):
    """Site stock has fallen below the reorder level. Drives the red flag."""
    return line.min_qty > 0 and line.stock_qty < line.min_qty


def discontinued_reason(line):
    """
    Why this line cannot be ordered, or "" when it can.

    >>> ANCHOR: DISCONTINUED-BLOCK <<<
    Deactivating a material or a vendor means "we have stopped using this". It
    removes them from the pickers, but a line set up months ago keeps whatever
    it was given — so without this the system would cheerfully raise a real
    order for a discontinued product from a supplier the company has dropped.

    Lives here, with the other per-line facts, so the screen's red flag and
    po_service's refusal are reading the SAME rule rather than two versions of
    it that agree today.
    """
    reasons = []
    if not line.material.is_active:
        reasons.append("the material is discontinued")
    if line.vendor is not None and not line.vendor.is_active:
        reasons.append("the vendor is no longer used")
    return " and ".join(reasons)


# -------------------------------------------------------------------- rates

def planning_rate(line):
    """
    The rate THIS PROJECT plans at.

    >>> ANCHOR: PLANNING-RATE <<<
    The line's own planned_rate when it has one, otherwise the material master's
    estimation rate — which is what every line used before the field existed, so
    a blank behaves exactly as the old `market_rate` did.

    WHY IT STOPPED BEING THE MASTER RATE ALONE (Saahil, 10 Aug 2026)
        For cement the master rate is a fair company-wide benchmark and what
        varies per project is the QUANTITY. For a material sold as a lump —
        signage, a security deposit, a lightning arrestor — the quantity is
        always 1, so the AMOUNT is what varies, and it was locked inside
        company-wide master data. Planning one project's signage meant editing
        the master and moving the figure on every other project at once.

    ⚠ THIS RENAMED `market_rate`, WHICH NO LONGER EXISTS. Anything still calling
      that name is stale code from before this date.

    ⚠ IT ALSO CHANGES WHAT VARIANCE MEANS, deliberately. rate_variance now
      measures the vendor's quote against THIS PROJECT'S plan rather than
      against the company benchmark — "did I buy at the rate I planned for this
      job?". Saahil's call.
    """
    if line.planned_rate is not None:
        return line.planned_rate
    return line.material.estimation_rate or ZERO


def effective_vendor_rate(line, captured=_UNSET):
    """
    The chosen vendor's rate: typed, else last paid, else the planning rate.

    >>> ANCHOR: VENDOR-RATE-CAPTURE <<<
    ⚠⚠ THE MIDDLE STEP IS NEW AND IT CHANGES MONEY. Until now this was two
       steps — typed, else the planning rate — so a line naming a vendor with no
       typed rate was compared against the plan and always reported 0.0%
       variance. It was measuring the plan against itself. Saahil, looking at a
       screen of 0.0%: the rate captured from an approved order "can be used as
       a reference for vendor rates in BOM".

    ⚠ WHY THE FALLBACK MOVED AND NOT JUST THE PLACEHOLDER. The grey number in
      the Vend Rate cell is not decoration: it states what a BLANK cell will
      actually use. Showing "last paid ₹340" over a cell that would compute with
      ₹20 is a screen contradicting itself — bug 24's shape, in a cell that
      drives PO value. So either both move or neither does. He chose both.

    ⚠ `captured` IS THE BULK HAND-DOWN, and `_UNSET` is not the same as `None`.
      None means "looked, and this vendor has never been paid for this material";
      _UNSET means "nobody has looked yet, go and ask". Collapsing the two would
      make every bulk caller silently skip the new step.
    """
    if line.vendor_rate is not None:
        return line.vendor_rate
    if captured is _UNSET:
        captured = bulk_vendor_rates([line]).get(line.id)
    if captured is not None:
        return captured
    return planning_rate(line)


def bulk_vendor_rates(lines):
    """
    The last rate paid to each line's chosen vendor for its material — for MANY
    lines, in ONE query rather than one per line.

    >>> ANCHOR: BOM-CALC-BULK <<<
    The BOM screen calls effective_vendor_rate for every row, so a lookup inside
    it would be a query per row on a screen that already learned that lesson
    twice — 618 queries to draw one screen, and bugs 3, 9 and 10. Same shape as
    bulk_quantities: ask the database once for all of them.

    ⚠ THE QUERY IS A SUPERSET AND THAT IS FINE. Filtering on the two id lists
      separately can return combinations no line asked for; the dict lookup is
      by the exact (vendor, material) pair, so the extras are read and dropped.
      The alternative — an OR of N exact pairs — is one enormous query that
      degrades faster than the rows it saves.

    ⚠ A LINE WITH NO VENDOR IS NOT IN THE RESULT. Nothing has been agreed with
      anybody, so there is no "last paid" to fall back to.

    Returns {line_id: Decimal} for lines that have one. Absent means none.
    """
    from masters.models import VendorRate

    wanted = [line for line in lines if line.vendor_id]
    if not wanted:
        return {}

    vendor_ids = {line.vendor_id for line in wanted}
    material_ids = {line.material_id for line in wanted}

    # ⚠ `.order_by()` STRIPS Meta.ordering, which sorts by material CODE and so
    #   drags in a join to the material table for a result that is read into a
    #   dict and never iterated in order. Cheap to leave in, free to remove.
    by_pair = {}
    for vendor_id, material_id, rate in (VendorRate.objects
                                         .filter(vendor_id__in=vendor_ids,
                                                 material_id__in=material_ids)
                                         .order_by()
                                         .values_list("vendor_id", "material_id", "rate")):
        by_pair[(vendor_id, material_id)] = rate

    found = {}
    for line in wanted:
        rate = by_pair.get((line.vendor_id, line.material_id))
        if rate is not None:
            found[line.id] = rate
    return found


def rate_variance(line, captured=_UNSET):
    """
    How far the vendor's rate sits from what this project planned, as a fraction.
    Positive = the vendor is dearer. Zero when there is nothing to compare.

    ⚠ THE BENCHMARK IS STILL THE PLANNING RATE. Only the actual side of the
      comparison changed. The question this answers is unchanged: "did I buy at
      the rate I planned for this job?"
    """
    benchmark = planning_rate(line)
    if not benchmark:
        return ZERO
    return (effective_vendor_rate(line, captured=captured) - benchmark) / benchmark


# ------------------------------------------------------------------- values

def estimated_value(line):
    """
    What this line is planned to cost. EX-GST — comparable with the reserve.

    ⚠ A `Lumpsum`-UOM material needs no special handling here and must not get
      any. Quantity 1 times a planning rate of ₹85,000 is ₹85,000, and quantity
      0.3 for a 30%-completion bill is ₹25,500. What keeps every formula in this
      file working is not that the quantity happens to be 1 — it is that there
      IS a quantity. A planned-AMOUNT field was proposed and rejected precisely
      because suggested_order_qty subtracts quantities from quantities, and
      "3 bags approved" cannot be taken away from "₹85,000 planned".
    """
    return line.planned_qty * planning_rate(line)


def used_value(line, received=None):
    """
    What has arrived, valued at the planning rate. EX-GST.

    Deliberately NOT actual purchase-order spend. This answers "how much of my
    budget have I consumed", so it must be measured in the same currency as the
    budget. Actual spend is committed_value, below.
    """
    received = received_qty(line) if received is None else received
    return received * planning_rate(line)


def po_value(line, order=None, captured=_UNSET):
    """What ordering this line right now would cost, at the vendor's rate. EX-GST."""
    order = order_qty(line) if order is None else order
    return order * effective_vendor_rate(line, captured=captured)


# --------------------------------------------------------- activity roll-ups

def reserve(bom, activity):
    """
    An activity's budget on this project.

    >>> ANCHOR: BOM-CALC-RESERVE <<<
    A LIVE LINK to the estimate line, not a copy: rate x built-up area, read
    fresh every time. Editing the estimate moves this, and therefore moves the
    number the site team is measured against — which is why editing a saved BOQ
    must warn about exactly that.

    This is the single documented exception to copy-don't-link in the system.
    BOM and PO line prices still take frozen copies.

    Zero when the activity is not on the estimate — spend against it was never
    quoted, which is a useful signal rather than an error.
    """
    line = bom.project.estimate.lines.filter(name=activity.name).first() if hasattr(
        bom.project, "estimate") else None
    if line is None:
        return ZERO
    return line.rate * bom.project.bua_sqft


def activity_totals(bom, activity):
    """
    Everything the KPI strip shows for one activity, in a single pass.

    Returned as a plain dict so the screen, the Excel export and the tests all
    read identical figures.
    """
    # ⚠ material__group IS NOT OPTIONAL. The grid greys Stock and Min on
    #   non-stock materials, which means reading material.group.is_stock_item on
    #   every row — one extra query per row without this, and the query-count
    #   test caught exactly that when the column was added.
    lines = list(bom.lines.filter(activity=activity)
                 .select_related("material", "material__group", "vendor"))

    # Every roll-up is summed from the SAME per-line figures the grid prints, so
    # a total can never disagree with the column above it. It also means each
    # line is worked out once rather than once per total — and, through
    # figures_for, in three queries rather than three per line.
    figures = figures_for(lines)

    planned = sum((f["estimated_value"] for f in figures), ZERO)
    budget = reserve(bom, activity)

    return {
        "activity": activity,
        "lines": lines,
        "figures": figures,
        "line_count": len(lines),
        "reserve": budget,
        "planned_value": planned,
        "variance": budget - planned,
        "percent_used": (planned / budget) if budget else ZERO,
        "used_value": sum((f["used_value"] for f in figures), ZERO),
        # ⚠ "About to be ordered", NOT "has been ordered". Posting clears the
        #   typed quantity, so this reads zero the moment orders are raised.
        "po_value_now": sum((f["po_value"] for f in figures), ZERO),
        # What this activity has actually committed to vendors, ex-GST, so it is
        # directly comparable with the reserve above it. Includes work orders,
        # because labour draws on the same reserve as material — the BOQ rate for
        # Plaster always paid for plasterers too, it was simply never tracked.
        "committed_value": sum((f["committed_value"] for f in figures), ZERO),
        "below_threshold": sum(1 for f in figures if f["below_threshold"]),
        "to_order_count": sum(1 for f in figures if f["order_qty"] > 0),
        # The grid's footer row. Here rather than in the template for the same
        # reason as everything else in this file: a total added up in a template
        # is a second implementation of a rule that already exists.
        "order_qty_total": sum((f["order_qty"] for f in figures), ZERO),
    }


def discard_effect(purchase_order):
    """
    What throwing away this draft order would do to the BOM, worked out BEFORE
    anyone presses the button.

    >>> ANCHOR: BOM-CALC-DISCARD-PREVIEW <<<
    Discarding a draft is safe but not invisible. Saahil asked for the warning
    to say WHICH figure moves, not just "are you sure?".

    ⚠ WHAT MOVES CHANGED ON 9 AUG 2026, when order quantities stopped defaulting
    to the suggestion. Posting an order CONSUMES the quantity somebody typed, so
    discarding it does NOT put that number back in the order box — it puts the
    material back into "still to buy". Whoever wants it re-ordered has to type
    it again, deliberately. That is the honest description and it is what this
    reports; saying "it comes back under To Order" would now be a lie.

    Nothing is written and nothing is simulated twice — the after-figures use
    the same functions as the before-figures, with the draft quantity reduced by
    what is on this order.

    Returns a list, one entry per activity:
        {activity, lines: [{line, returning, still_to_buy_before, still_to_buy_after}],
         value_cancelled}
    """
    bom = purchase_order.project.bom

    # A single order can carry two lines for the same BOM row; add them up first.
    returning = {}
    for po_line in purchase_order.lines.select_related(
            "bom_line__activity", "bom_line__material", "bom_line__vendor"):
        returning[po_line.bom_line] = returning.get(po_line.bom_line, ZERO) + po_line.quantity

    by_activity = {}
    for line, quantity in returning.items():
        approved = approved_qty(line)
        draft = draft_qty(line)

        # "Still to buy" is the suggestion — planned less what is already
        # committed, on order or in stock. Taking this order away puts its
        # quantity back into that figure.
        before = suggested_order_qty(line, approved, draft)
        after = suggested_order_qty(line, approved, max(ZERO, draft - quantity))

        entry = by_activity.setdefault(line.activity, {
            "activity": line.activity, "lines": [], "value_cancelled": ZERO})
        entry["lines"].append({"line": line, "returning": quantity,
                               "still_to_buy_before": before, "still_to_buy_after": after})
        # Valued at the rate ON THE ORDER, not the current one — that is what is
        # actually being cancelled.
        entry["value_cancelled"] += quantity * _rate_on_order(purchase_order, line)

    effects = sorted(by_activity.values(),
                     key=lambda e: (e["activity"].sort_order, e["activity"].name))
    return effects


def _rate_on_order(purchase_order, line):
    """The rate this order actually carries for a line — a frozen copy, not today's."""
    po_line = purchase_order.lines.filter(bom_line=line).first()
    return po_line.rate if po_line else effective_vendor_rate(line)


def line_figures(line, quantities=None, committed=None, captured=_UNSET):
    """
    Every derived number for one BOM line, in one dict.

    The screen, the Excel export and the tests all read this, so none of them
    can drift from the others.

    The three sums are taken ONCE here and handed to everything that needs them,
    which is what makes one row one small handful of queries instead of
    seventeen. The formulas below are the same ones; only the number of times
    the database is asked has changed.

    `quantities`, `committed` and `captured` let a caller that has already
    fetched them in bulk hand them straight in — see figures_for. Leave them out
    and this fetches its own, which is what a single line on its own should do.
    """
    # ⚠ RESOLVED ONCE, HERE, rather than left as _UNSET for each reader to
    #   handle. Two readers below need it and one of them (`captured_rate`) has
    #   no way to fetch for itself, so a sentinel reaching them would quietly
    #   report "no rate captured" on a line that has one.
    if captured is _UNSET:
        captured = bulk_vendor_rates([line]).get(line.id)
    if committed is None:
        committed = committed_value(line)
    if quantities is None:
        approved = approved_qty(line)
        draft = draft_qty(line)
        received = received_qty(line)
    else:
        approved = quantities["approved"]
        draft = quantities["draft"]
        received = quantities["received"]
    suggested = suggested_order_qty(line, approved=approved, draft=draft)
    ordering = order_qty(line)          # zero unless somebody typed a quantity

    return {
        "line": line,
        "planned_qty": line.planned_qty,
        "approved_qty": approved,
        "draft_qty": draft,
        "received_qty": received,
        "stock_qty": line.stock_qty,
        "min_qty": line.min_qty,
        "suggested_order_qty": suggested,
        "order_qty": ordering,
        "is_overridden": is_overridden(line, suggested=suggested),
        "below_threshold": is_below_threshold(line),
        "discontinued_reason": discontinued_reason(line),
        "planning_rate": planning_rate(line),
        # True when this project set its own rate rather than inheriting the
        # material master's. The screen shows it, so nobody wonders why two
        # projects value the same material differently.
        "rate_is_overridden": line.planned_rate is not None,
        "vendor_rate": effective_vendor_rate(line, captured=captured),
        "rate_variance": rate_variance(line, captured=captured),
        # What the screen puts in the grey placeholder. None means there is
        # nothing to suggest and the planning rate is shown instead, which is
        # what the cell has always done.
        "captured_rate": captured,
        "estimated_value": estimated_value(line),
        "used_value": used_value(line, received=received),
        # ⚠ Two different questions, and the screen must not blur them:
        #   po_value       — what pressing Post POs right now WOULD cost.
        #                    Zero once posted, because posting clears the typed
        #                    quantity. "About to be ordered."
        #   committed_value— what has ALREADY been ordered, at the rate on the
        #                    document. "Actually committed."
        "po_value": po_value(line, order=ordering, captured=captured),
        "committed_value": committed,
    }
