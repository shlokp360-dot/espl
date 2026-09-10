"""
The analytics overview — the one page the admin opens with ten minutes to spare.

>>> ANCHOR: ANALYTICS-OVERVIEW <<<

⚠ THE ADMIN, AND NOBODY ELSE. `analytics.view` is the one permission in the
    whole matrix held by a single role, and that was deliberate: reserve against
    actual is the insight the owner keeps.

⚠ NO SINGLE HEADLINE NUMBER. Saahil's answer when asked which one figure belongs
    at the top: there isn't one. Committed, owed and paid are three different
    questions and a business that reads only one of them is guessing at the
    other two. So six boxes, each labelled with which stage it counts.

⚠ EVERY FIGURE COMES FROM `analytics/money.py`. Nothing on this page re-derives
    money from lines, and nothing calls a figure "spend" unless it left the bank.
"""
from datetime import timedelta

from django.shortcuts import render
from django.utils import timezone

from accounts.perms import requires
from analytics import budget, charts, money, periods
from masters.models import Vendor
from projects.bom_models import PurchaseOrder
from projects.models import Estimate, Project
from tasks import schedule as schedule_geometry
from tasks.models import DelayReason, Subtask, TaskHeader


def _filters(request, today):
    """The three controls every analytics page carries, read once."""
    month = (request.GET.get("month") or "").strip()
    project_id = (request.GET.get("project") or "").strip()
    doc_type = (request.GET.get("type") or "").strip()

    project = Project.objects.filter(pk=project_id).first() if project_id else None
    start, end, label, kind = periods.bounds(today, month)
    return {
        "start": start, "end": end, "label": label, "kind": kind,
        "project": project, "doc_type": doc_type if doc_type in ("PO", "WO") else "",
        "month": month,
        "months": periods.months_so_far(today),
        "projects": Project.objects.filter(
            status__in=[Project.Status.WON, Project.Status.COMPLETED]).order_by("name"),
    }


@requires("analytics.view")
def overview(request):
    today = timezone.localdate()
    view = _filters(request, today)
    project, doc_type = view["project"], view["doc_type"]

    paid = money.documents("paid", view["start"], view["end"], project, doc_type)
    committed = money.documents("committed", view["start"], view["end"], project, doc_type)
    owed = money.outstanding(project, doc_type)

    paid_totals = money.add_up(paid)
    committed_totals = money.add_up(committed)
    owed_totals = money.add_up(owed)

    # ⚠ EVERY UNPAID DOCUMENT NOW HAS A DUE DATE — a vendor with nothing in its
    #   terms takes the house default of 30 days (Saahil's call). What is still
    #   counted is how many rested on that assumption, because an assumed date
    #   can put a real invoice in the wrong bucket and the reader should know
    #   how much of the figure is a guess.
    horizon = today + timedelta(days=30)
    due_soon, assumed = [], 0
    for order in owed:
        due = money.due_date(order)
        if due and due <= horizon:
            due_soon.append(order)
        if money.terms_assumed(order):
            assumed += 1
    due_soon_totals = money.add_up(due_soon)

    # ---- reserve consumed ------------------------------------------------
    # ⚠ EX-GST AGAINST EX-GST. The reserve comes from the estimate, which adds
    #   GST once at the very end, so it is compared with `taxable` and never with
    #   an invoice value. Mixing the two once reported an activity at 99.3% of
    #   budget when the truth was 84.2%.
    reserve = _reserve_total(project)

    # ---- what the money bought, by month ---------------------------------
    by_month = []
    for key, label in view["months"]:
        first, last, _label, _kind = periods.bounds(today, key)
        by_month.append({
            "label": label.split()[0],
            "values": [
                money.add_up(money.documents("committed", first, last, project, doc_type))["taxable"],
                money.add_up(money.documents("paid", first, last, project, doc_type))["net_payable"],
            ],
        })

    # ⚠ EX-GST, AND THE SCREEN SAYS SO. A document's deduction, round-off and
    #   TDS belong to the whole document and cannot honestly be split across
    #   trades — see money.by_activity.
    activity_split = money.by_activity(paid)
    split = money.settlement(project, doc_type)

    return render(request, "analytics/overview.html", {
        "view": view,
        "paid": paid_totals,
        "split": split,
        "settlement_bar": charts.stacked([
            {"label": "Settled", "value": split["settled"]["net_payable"],
             "colour": charts.PALETTE[5]},
            {"label": "Payable now", "value": split["payable_now"]["net_payable"],
             "colour": charts.PALETTE[3]},
            {"label": "Not yet payable", "value": split["not_yet_payable"]["net_payable"],
             "colour": charts.PALETTE[4]},
        ]),
        "activity_donut": charts.donut([
            {"label": row["label"], "value": row["value"], "colour": charts.colour(index)}
            for index, row in enumerate(activity_split)]),
        "activity_rows": [
            {"label": row["label"], "value": row["value"], "colour": charts.colour(index),
             "pct": charts.share(row["value"], paid_totals["taxable"])}
            for index, row in enumerate(activity_split)],
        "committed": committed_totals,
        "owed": owed_totals,
        "due_soon": due_soon_totals,
        "due_soon_count": len(due_soon),
        "assumed": assumed,
        "reserve": reserve,
        "reserve_pct": charts.share(committed_totals["taxable"], reserve),
        "days_lost": _days_lost(project),
        "by_month": charts.bars(by_month, [
            {"label": "Committed", "colour": charts.PALETTE[0]},
            {"label": "Paid", "colour": charts.PALETTE[5]},
        ]),
        "series": [
            {"label": "Committed", "colour": charts.PALETTE[0]},
            {"label": "Paid", "colour": charts.PALETTE[5]},
        ],
        "drafts": PurchaseOrder.objects.filter(status=PurchaseOrder.Status.DRAFT).count(),
    })


# ------------------------------------------------------------- gross to net
#
# >>> ANCHOR: ANALYTICS-G2N <<<
#
# ⚠ THE LADDER EXISTED IN THE MODEL AND ON EVERY PRINTED PDF AND ON NO SCREEN.
#     It answers the three questions people confuse daily — what did we commit,
#     what will we be invoiced, and what actually leaves the bank — and it is
#     what a business head carries into a meeting.
#
# ⚠ THE STEPS ARE NAMED SO THEY CANNOT BE MISREAD:
#       deduction  is POST-TAX and is NOT a discount. The GST above sits on the
#                  undiscounted taxable value, so the vendor's own invoice will
#                  show a different taxable figure.
#       tds        is withheld FROM THE PAYMENT, computed on the TAXABLE value,
#                  never on the GST, and it does not reduce what the vendor
#                  bills.
#     Both are labelled on screen in those words.
#
# ⚠ EVERY STEP CLICKS THROUGH TO THE DOCUMENTS BEHIND IT. Without that a reader
#     who disbelieves a figure has nowhere to go, and a figure nobody can check
#     is a figure nobody trusts.

#: (key, label, kind, the note under it). One list, read by the chart, the table
#: and the drill links — so a step cannot exist in one and not the others.
G2N_STEPS = [
    ("gross", "Gross", "start", "quantity × rate, before anything"),
    ("discount", "Less discount", "less", "the per-line percentages"),
    ("taxable", "Basic", "total", "what GST is charged on"),
    ("gst", "Add GST", "add", "CGST + SGST, or IGST"),
    ("invoice_value", "Amount", "total", "basic plus GST — what the vendor's invoice says"),
    ("deduction", "Less deduction", "less", "agreed, POST-TAX — not a discount"),
    ("round_off", "Round off", "add", "to the nearest rupee, computed"),
    ("order_value", "Order value", "total", "what the vendor invoices us"),
    ("tds", "Less TDS", "less", "withheld from the payment, on the basic value"),
    ("net_payable", "Net payable", "total", "what actually leaves the bank"),
]


@requires("analytics.view")
def g2n(request):
    """The whole ladder, for a chosen stage, period and filter."""
    today = timezone.localdate()
    view = _filters(request, today)
    stage = request.GET.get("stage") if request.GET.get("stage") in money.STAGE_DATE else "committed"

    orders = money.documents(stage, view["start"], view["end"],
                             view["project"], view["doc_type"])
    ladder = money.add_up(orders)

    # ⚠ round_off is the one step that can be negative, and a waterfall drawn
    #   from an absolute value would step the wrong way. Its sign is kept and
    #   the kind flips with it.
    rows = []
    for key, label, kind, note in G2N_STEPS:
        amount = ladder[key]
        if key == "round_off" and amount < 0:
            kind, amount = "less", -amount
        rows.append({"key": key, "label": label, "kind": kind,
                     "amount": amount, "note": note, "raw": ladder[key]})

    return render(request, "analytics/g2n.html", {
        "view": view,
        "stage": stage,
        "stages": [("committed", "Committed — approved onward"),
                   ("received", "Received — delivered"),
                   ("paid", "Paid — money out")],
        "ladder": ladder,
        "rows": rows,
        "chart": charts.waterfall(rows, money=lambda value: intcomma_in(value)),
        "count": len(orders),
        "by_vendor": money.by_vendor(orders)[:10],
    })


@requires("analytics.view")
def documents(request):
    """
    Every document, filtered by whatever was clicked — the drill target.

    ⚠ THIS PAGE EXISTS BECAUSE DRILL-THROUGH NEEDS SOMEWHERE TO LAND. A figure
      nobody can open is a figure nobody trusts, and the per-project purchase
      order screen cannot be filtered across projects the way a drill needs.

    ⚠ IT IS A LIST, NOT A SECOND DOCUMENT SCREEN. Opening a row goes to the real
      document, which is the one place a purchase order may be read or changed.
    """
    today = timezone.localdate()
    view = _filters(request, today)
    stage = request.GET.get("stage") if request.GET.get("stage") in money.STAGE_DATE else None
    status = request.GET.get("status") or ""
    vendor_id = (request.GET.get("vendor") or "").strip()
    vendor = Vendor.objects.filter(pk=vendor_id).first() if vendor_id else None

    if stage:
        orders = money.documents(stage, view["start"], view["end"],
                                 view["project"], view["doc_type"], vendor)
    elif status == "owed":
        orders = money.outstanding(view["project"], view["doc_type"], vendor)
    else:
        rows = money.base_queryset(view["project"], view["doc_type"], vendor)
        if status in dict(PurchaseOrder.Status.choices):
            rows = rows.filter(status=status)
        orders = list(rows.order_by("-raised_on", "-id")[:400])

    return render(request, "analytics/documents.html", {
        "view": view,
        "stage": stage,
        "status": status,
        "vendor": vendor,
        "rows": [{"order": order, "totals": order.totals(),
                  "due": money.due_date(order),
                  "assumed": money.terms_assumed(order)} for order in orders],
        "ladder": money.add_up(orders),
        "statuses": PurchaseOrder.Status.choices,
    })


@requires("analytics.view")
def budget_page(request):
    """
    Budget against plan against actual.

    ⚠ ROWS ARE PROJECTS UNTIL YOU CHOOSE ONE, THEN THEY ARE TRADES. One screen,
      two grains, and the filter is the drill-down — a separate "detail page"
      would be the same table twice.
    """
    today = timezone.localdate()
    view = _filters(request, today)
    project = view["project"]

    rows = budget.by_trade(project) if project else budget.by_project(budget.live_projects())
    footer = budget.total(rows)

    return render(request, "analytics/budget.html", {
        "view": view,
        "rows": rows,
        "total": footer,
        # ⚠ THE GRAIN IS BOTH A COMPARISON AND A WORD ON SCREEN — "by
        #   construction activity" prints in the toolbar, and the table's first
        #   heading switches on the same value. Renaming the on-screen word
        #   without renaming this one broke the comparison silently and the
        #   heading read "Project" on a page grouped by activity: bug 24 again,
        #   perfectly rendered and saying the opposite of itself. Kept as ONE
        #   string so it cannot happen a second time.
        "grain": "construction activity" if project else "project",
        "chart": charts.bars([{
            "label": _short(row["label"]),
            "values": [row["budget"], row["plan"], row["committed"]],
        } for row in rows[:10]], [
            {"label": "Budget", "colour": charts.PALETTE[4]},
            {"label": "Plan", "colour": charts.PALETTE[0]},
            {"label": "Committed", "colour": charts.PALETTE[3]},
        ]),
        "series": [
            {"label": "Budget", "colour": charts.PALETTE[4]},
            {"label": "Plan", "colour": charts.PALETTE[0]},
            {"label": "Committed", "colour": charts.PALETTE[3]},
        ],
    })


@requires("analytics.view")
def bom_page(request):
    """
    What one site is buying: trades, then the materials carrying the money.

    ⚠ ONE PROJECT AT A TIME AND NO ROLL-UP. A material list added across sites
      would mix a tonne of steel at two different rates on two different jobs
      into an average nobody can act on.
    """
    today = timezone.localdate()
    view = _filters(request, today)
    project = view["project"] or budget.live_projects().first()

    rows = budget.by_trade(project) if project else []
    return render(request, "analytics/bom.html", {
        "view": view,
        "project": project,
        "rows": rows,
        "total": budget.total(rows),
        "materials": budget.by_material(project) if project else [],
        # ⚠ THE BAR IS THE PERCENTAGE, BECAUSE THE NUMBER BESIDE IT IS THE
        #   PERCENTAGE. It used to be committed rupees against a percentage
        #   label — see charts.hbars. The scale is fixed at 100 (or higher if
        #   something is over budget) so 12% draws as 12% of the track and not
        #   as a full bar.
        "chart": charts.hbars(
            [{"label": row["label"],
              "value": row["used_pct"],
              "display": f"{row['used_pct']}% of {intcomma_in(row['budget'])}",
              "colour": charts.PALETTE[6] if row["over"] else charts.PALETTE[0]}
             for row in sorted(rows, key=lambda row: -row["used_pct"]) if row["budget"]],
            maximum=max(100, *[row["used_pct"] for row in rows] or [100])),
    })


@requires("analytics.view")
def tasks_page(request):
    """
    Progress and delay, per trade — and the same chart the site team reads.

    ⚠ TASKS AND MONEY ARE NOT JOINED ON THIS SCREEN, ON SAAHIL'S INSTRUCTION:
      "task is different and bom is different… no need to combine them in a
      screen". Both appear on the Overview, which is where a business head asks
      the crossing question. A subtask names no material and no order, so a
      figure claiming what a particular delay cost would be invented.
    """
    today = timezone.localdate()
    view = _filters(request, today)
    project = view["project"] or budget.live_projects().first()

    headers = (TaskHeader.objects.filter(project=project)
               .select_related("activity", "owner")
               .prefetch_related("subtasks") if project else TaskHeader.objects.none())

    # >>> ANCHOR: ANALYTICS-WORK-FILTERS <<<
    # ⚠⚠ POINT 20. Analytics carried month, project and document type, and this
    #    tab had nothing for the two things the screen is actually ABOUT — which
    #    milestone, and which construction activity. Saahil raised it in the
    #    review and it then fell out of the plan for four commits.
    #
    # ⚠ ON THIS TAB ONLY, DELIBERATELY. `_filters` is the three controls EVERY
    #   analytics page carries; these two mean nothing on Payments or Gross to
    #   net, so they are read here rather than added to the shared set. The task
    #   board is out of scope — noted in the review and left alone.
    #
    # ⚠ THE CHOICES COME FROM THIS PROJECT, NOT THE MASTER. Offering all
    #   eighteen activities on a site that uses four is the prototype dropdown
    #   that listed every project's header tasks — bug 14, in a different hat.
    headers = list(headers)
    milestone_choices = sorted({(h.id, h.name) for h in headers}, key=lambda row: row[1])
    activity_choices = sorted({(h.activity_id, h.activity.name) for h in headers},
                              key=lambda row: row[1])

    milestone_id = (request.GET.get("milestone") or "").strip()
    activity_id = (request.GET.get("activity") or "").strip()
    if milestone_id.isdigit():
        headers = [h for h in headers if h.id == int(milestone_id)]
    if activity_id.isdigit():
        headers = [h for h in headers if h.activity_id == int(activity_id)]

    trades, reasons = {}, {}
    for header in headers:
        subtasks = list(header.subtasks.all())
        row = trades.setdefault(header.activity_id, {
            "label": header.activity.name, "headers": 0, "done": 0, "total": 0,
            "late": 0, "shifted": 0, "blocked": 0})
        row["headers"] += 1
        row["total"] += len(subtasks)
        for subtask in subtasks:
            if subtask.status == Subtask.Status.DONE:
                row["done"] += 1
            if subtask.status == Subtask.Status.BLOCKED:
                row["blocked"] += 1
            row["late"] += subtask.days_late
            row["shifted"] += subtask.days_shifted
            for key, days in (("delay_reason", subtask.days_late),
                              ("shift_reason", subtask.days_shifted)):
                if days:
                    label = dict(DelayReason.choices).get(getattr(subtask, key)) or "Not recorded"
                    reasons[label] = reasons.get(label, 0) + days

    rows = sorted(trades.values(), key=lambda row: row["late"] + row["shifted"], reverse=True)
    for row in rows:
        row["progress"] = int(round(row["done"] * 100 / row["total"])) if row["total"] else 0

    return render(request, "analytics/tasks.html", {
        "view": view,
        "project": project,
        "rows": rows,
        # ⚠ ANCHOR: ANALYTICS-WORK-FILTERS — the two controls this tab adds.
        "milestone_choices": milestone_choices,
        "activity_choices": activity_choices,
        "milestone_id": int(milestone_id) if milestone_id.isdigit() else None,
        "activity_id": int(activity_id) if activity_id.isdigit() else None,
        # ⚠ THE CHART IGNORES THESE. It is the same drawing the site team reads,
        #   from the same module, and a Gantt showing one phase out of six is a
        #   different picture from the one they discuss in the morning meeting.
        #   The tables above it are what the filters narrow.
        "filtered": bool(milestone_id.isdigit() or activity_id.isdigit()),
        "days_lost": sum(row["late"] + row["shifted"] for row in rows),
        "chart": charts.hbars([{
            "label": label, "value": days, "display": f"{days} d",
            "colour": charts.PALETTE[6],
        } for label, days in sorted(reasons.items(), key=lambda item: -item[1])]),
        # ⚠ Fixed at 100, or a site where the best trade is 33% done would draw
        #   that trade as a full bar.
        "progress_chart": charts.hbars(
            [{"label": row["label"], "value": row["progress"] or 1,
              "display": f"{row['progress']}% · {row['done']} of {row['total']}",
              "colour": charts.PALETTE[5]} for row in rows],
            maximum=100),
        # ⚠ THE SAME CHART THE SITE TEAM READS, from the same module. Two
        #   drawings of one schedule would eventually disagree.
        "chart_data": schedule_geometry.build(project) if project else None,
    })


def _short(label, limit=14):
    """Chart labels are 90px wide. A project code beats a truncated name."""
    label = label.split(" — ")[0]
    return label if len(label) <= limit else label[:limit - 1] + "…"


@requires("analytics.view")
def settlement(request):
    """
    The books question: how much has been paid, and how much is still to pay.

    >>> ANCHOR: ANALYTICS-SETTLEMENT <<<

    ⚠ THE THREE BUCKETS ADD BACK TO THE TOTAL, AND THAT IS THE POINT OF THE
      PAGE. Settled + payable now + not yet payable = everything approved
      onward, all four on the same basis. A settlement view whose parts do not
      reconcile is the thing an accountant stops trusting first.

    ⚠ NOT FILTERED BY MONTH — see `money.settlement`. What is owed is a question
      about today. The month filter still applies to the two figures that ARE
      about a period: what was invoiced and what was paid in it.
    """
    today = timezone.localdate()
    view = _filters(request, today)
    project, doc_type = view["project"], view["doc_type"]

    split = money.settlement(project, doc_type)
    unpaid = split["orders"]["payable_now"] + split["orders"]["not_yet_payable"]
    buckets = money.ageing(split["orders"]["payable_now"], today)

    paid_in_period = money.add_up(
        money.documents("paid", view["start"], view["end"], project, doc_type))

    by_month = []
    for key, label in view["months"]:
        first, last, _label, _kind = periods.bounds(today, key)
        by_month.append({
            "label": label.split()[0],
            "values": [
                money.add_up(money.documents("received", first, last, project, doc_type))["order_value"],
                money.add_up(money.documents("paid", first, last, project, doc_type))["net_payable"],
            ],
        })

    vendors = money.by_vendor(split["orders"]["payable_now"])

    return render(request, "analytics/payments.html", {
        "view": view,
        "split": split,
        "paid_in_period": paid_in_period,
        "buckets": [bucket for bucket in buckets if bucket["orders"]],
        "vendors": vendors,
        "vendor_chart": charts.hbars([{
            "label": row["vendor"].name if row["vendor"] else "—",
            "value": row["net"],
            "display": f"Rs {intcomma_in(row['net'])}",
            "colour": charts.PALETTE[2],
        } for row in vendors[:8]]),
        "bar": charts.stacked([
            {"label": "Settled", "value": split["settled"]["net_payable"],
             "colour": charts.PALETTE[5]},
            {"label": "Payable now", "value": split["payable_now"]["net_payable"],
             "colour": charts.PALETTE[3]},
            {"label": "Not yet payable", "value": split["not_yet_payable"]["net_payable"],
             "colour": charts.PALETTE[4]},
        ]),
        "ageing_chart": charts.hbars([{
            "label": bucket["label"],
            "value": bucket["total"],
            "display": f"Rs {intcomma_in(bucket['total'])}",
            "colour": charts.PALETTE[5] if bucket["key"] == "not_due" else
                      charts.PALETTE[3] if bucket["key"] in ("d30", "unknown") else
                      charts.PALETTE[6],
        } for bucket in buckets if bucket["orders"]]),
        "by_month": charts.bars(by_month, [
            {"label": "Invoiced", "colour": charts.PALETTE[0]},
            {"label": "Paid", "colour": charts.PALETTE[5]},
        ]),
        "series": [
            {"label": "Invoiced", "colour": charts.PALETTE[0]},
            {"label": "Paid", "colour": charts.PALETTE[5]},
        ],
        "unpaid_count": len(unpaid),
    })


def intcomma_in(value):
    """
    Indian digit grouping — 12,34,567. Used only for chart labels, which are
    plain strings rather than template output and so cannot use the `inr` filter.
    """
    whole = f"{int(round(value)):d}"
    if len(whole) <= 3:
        return whole
    head, tail = whole[:-3], whole[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts + [tail])


def _reserve_total(project=None):
    """
    Every activity's budget, added up. Zero when nothing has been estimated.

    ⚠ THE RESERVE IS A LIVE LINK TO THE ESTIMATE — rate × built-up area, read
      fresh. It moves if somebody edits a BOQ, which is exactly why editing a
      saved BOQ warns about it.
    """
    estimates = Estimate.objects.select_related("project").prefetch_related("lines")
    if project:
        estimates = estimates.filter(project=project)
    else:
        estimates = estimates.filter(
            project__status__in=[Project.Status.WON, Project.Status.COMPLETED])

    total = money.ZERO
    for estimate in estimates:
        for line in estimate.lines.all():
            total += line.rate * estimate.project.bua_sqft
    return total


def _days_lost(project=None):
    """
    Days lost to delay, from the task module's own arithmetic.

    ⚠ COUNTED THE SAME WAY THE DELAY LOG COUNTS IT — late finishes plus
      replanned days — because two screens giving two answers to "how many days
      have we lost" is worse than neither screen existing.
    """
    rows = Subtask.objects.all()
    if project:
        rows = rows.filter(header__project=project)
    late = sum(row.days_late for row in rows.filter(finished_on__isnull=False))
    shifted = sum(row.days_shifted for row in rows.filter(original_start__isnull=False))
    return late + shifted
