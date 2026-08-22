"""
Budget against plan against actual — per project, and per trade inside one.

>>> ANCHOR: ANALYTICS-BUDGET <<<

⚠ THREE COLUMNS, BECAUSE THERE ARE TWO DIFFERENT GAPS AND TWO DIFFERENT PEOPLE.

      BUDGET      the BOQ rate × built-up area. What was quoted.
      PLAN        the BOM's planned quantities × rate. What we intend to buy.
      ACTUAL      committed → received → paid.

    Budget minus plan is an ESTIMATING gap: the quote was wrong, or the design
    changed. Plan minus actual is a BUYING gap: the rate negotiated, or the
    quantity actually consumed. Collapsing them into one "variance" hides which
    of the two happened, and they are not the same person's problem.

⚠ THE WORD ON SCREEN IS "BUDGET". Saahil's call: the officials read budget.
    `reserve` stays in the code and on the BOM screen, where the site team has
    used it since July — one number, two audiences, and the label follows the
    reader.

⚠ EVERYTHING IS EX-GST. The BOQ adds GST once at the very end, so budget, plan
    and committed are all pre-tax and directly comparable. Paid is the one
    figure that is not, and it is not shown in this grid — it lives on Payments.
    Mixing the two once reported an activity at 99.3% of budget when the truth
    was 84.2%.

⚠ THE BUDGET IS MATCHED TO A TRADE BY NAME, NOT BY ID — the known landmine
    recorded in `OPEN-BEFORE-GO-LIVE.md`. This module inherits that and does not
    make it worse: it reads the same estimate lines the BOM screen reads, so if
    a rename ever zeroes a reserve, both screens go wrong together and visibly,
    rather than one of them inventing a number.

⚠ FIGURES ARE COMPUTED IN BULK, ONE PROJECT AT A TIME. `bom_calc.figures_for`
    answers three questions for a whole BOM rather than three per line. The cost
    is per PROJECT, not per trade — a test asserts adding trades does not add
    queries.
"""
from decimal import Decimal

from projects.bom_calc import figures_for
from projects.models import Project

ZERO = Decimal("0.00")


def _budget_by_name(project):
    """
    Each trade's budget on this project: rate × built-up area, from the estimate.

    ⚠ A LIVE LINK, NOT A COPY — editing the BOQ moves it. That is the single
      documented exception to copy-don't-link in this system, and it exists so
      the number the site is measured against is always the current quote.
    """
    estimate = getattr(project, "estimate", None)
    if estimate is None:
        return {}
    return {line.name: line.rate * project.bua_sqft for line in estimate.lines.all()}


def _blank(label, activity=None):
    return {
        "label": label,
        "activity": activity,
        "budget": ZERO,
        "plan": ZERO,
        "committed": ZERO,
        "received": ZERO,
        "lines": 0,
    }


def _finish(row):
    """The three derived figures, worked out once, here."""
    row["left"] = row["budget"] - row["committed"]
    row["used_pct"] = int(round(row["committed"] * 100 / row["budget"])) if row["budget"] else 0
    row["plan_pct"] = int(round(row["plan"] * 100 / row["budget"])) if row["budget"] else 0
    # ⚠ OVER BUDGET IS A FLAG, NOT A BANNER. Saahil's standing rule for this
    #   system: an overspend shows as a red number and never as an alert bar.
    row["over"] = row["committed"] > row["budget"] > ZERO
    return row


def by_trade(project):
    """
    One row per trade on one project, plus a total row.

    A trade with a budget and no BOM lines still appears — quoted and not yet
    planned is a real state and hiding it would make the total not add up.
    """
    budgets = _budget_by_name(project)
    rows = {}

    bom = getattr(project, "bom", None)
    if bom is not None:
        lines = list(bom.lines.select_related("activity", "material", "material__group", "vendor"))
        for line, figure in zip(lines, figures_for(lines)):
            activity = line.activity
            row = rows.setdefault(activity.pk, _blank(activity.name, activity))
            row["plan"] += figure["estimated_value"]
            row["committed"] += figure["committed_value"]
            row["received"] += figure["used_value"]
            row["lines"] += 1

    # Budgets are keyed by the estimate line's NAME — see the note at the top.
    for row in rows.values():
        row["budget"] = budgets.pop(row["label"], ZERO)
    for name, amount in budgets.items():
        rows[f"unplanned-{name}"] = dict(_blank(name), budget=amount)

    out = [_finish(row) for row in rows.values()]
    return sorted(out, key=lambda row: row["budget"], reverse=True)


def by_project(projects):
    """One row per project — every trade on it, rolled up."""
    out = []
    for project in projects:
        row = _blank(f"{project.code} — {project.name}")
        row["project"] = project
        for trade in by_trade(project):
            for key in ("budget", "plan", "committed", "received", "lines"):
                row[key] += trade[key]
        out.append(_finish(row))
    return sorted(out, key=lambda row: row["budget"], reverse=True)


def by_material(project, limit=20):
    """
    The heaviest materials on one project — planned, committed, received.

    ⚠ RANKED BY WHAT HAS BEEN COMMITTED, not by what was planned. The question
      this table answers is "where is the money actually going", and a material
      planned in bulk and never ordered is not where the money is going.
    """
    bom = getattr(project, "bom", None)
    if bom is None:
        return []

    lines = list(bom.lines.select_related("activity", "material", "material__group", "vendor"))
    rows = {}
    for line, figure in zip(lines, figures_for(lines)):
        material = line.material
        row = rows.setdefault(material.pk, {
            "material": material,
            "label": material.name,
            "code": material.code,
            "uom": material.uom,
            "plan": ZERO, "committed": ZERO, "received": ZERO,
        })
        row["plan"] += figure["estimated_value"]
        row["committed"] += figure["committed_value"]
        row["received"] += figure["used_value"]
    ranked = sorted(rows.values(), key=lambda row: row["committed"], reverse=True)
    return ranked[:limit]


def total(rows):
    """The footer. Added from the same rows the grid prints, never re-queried."""
    row = _blank("All")
    for entry in rows:
        for key in ("budget", "plan", "committed", "received", "lines"):
            row[key] += entry[key]
    return _finish(row)


def live_projects():
    return Project.objects.filter(
        status__in=[Project.Status.WON, Project.Status.COMPLETED]).order_by("name")
