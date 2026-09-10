"""
The Gantt chart, as arithmetic.

>>> ANCHOR: TASK-SCHEDULE <<<

⚠ ALL OF THE GEOMETRY IS HERE AND NONE OF IT IS IN THE TEMPLATE. The same rule
    that put every BOM figure in `bom_calc.py`: a percentage worked out inside a
    `<div>` cannot be tested, cannot be read against the rule it implements, and
    gets copied the second time somebody needs it. The template receives left and
    width as strings and draws them.

⚠ THE SCALE IS DERIVED FROM THE DATA, NEVER FIXED. Saahil asked for a month-year
    scale; the span is whatever the work actually covers, padded out to whole
    months at both ends so the labels line up with the bars. A chart with a fixed
    twelve-month window is a chart that is empty on a three-week job and useless
    on a two-year one.

⚠ THE BAR CARRIES THE DIFFERENCE. THE WORDS LIVE IN THE DELAY LOG.
    His correction, in one sentence: "the delay messages should not be visible on
    the chart, it should have a different log repository". So a row that ran past
    its date gets a second segment in a different colour and no text — the
    picture says how much, the log says why.

⚠ TWO KINDS OF OVERRUN, AND THEY ARE NOT THE SAME THING:

      a subtask's   it finished after its own date, or it is open and today is
                    already past it. That is LATE.
      a header's    its subtasks add up to more than the window the manager
                    committed to. Nothing has slipped yet — the plan simply no
                    longer fits, and it is visible before any date passes.

    Drawn differently on purpose. Reading them as one number is how a project
    convinces itself it is on time until the week it is not.

⚠ PERCENTAGES ARE FORMATTED AS STRINGS HERE. A float rendered by a template
    passes through locale formatting, and a decimal comma inside `left:12,5%`
    silently draws every bar at zero.
"""
from datetime import date, timedelta

from django.utils import timezone

from tasks.models import Subtask, TaskHeader


def _first_of_month(day):
    return day.replace(day=1)


def _last_of_month(day):
    if day.month == 12:
        return date(day.year, 12, 31)
    return date(day.year, day.month + 1, 1) - timedelta(days=1)


def _months_between(first, last):
    """Every month the span touches, as first-of-month dates."""
    out, cursor = [], _first_of_month(first)
    while cursor <= last:
        out.append(cursor)
        cursor = _last_of_month(cursor) + timedelta(days=1)
    return out


# >>> ANCHOR: TASK-SCHEDULE-SCALE <<<
# ⚠⚠ FIXED PIXELS PER DAY, NOT A PERCENTAGE OF THE SPAN. Saahil, on a real
#    project: "normally a project goes on for two years, but when I saw the
#    Gantt chart it was very confusing — when we have at least a year in, the
#    data is compressed at the end. Either make it a scrollable graph so the
#    user can scroll and review it, or make it better visually."
#
#    He is describing the arithmetic. Every bar used to be a PERCENTAGE of the
#    whole span, so a two-year job squeezed twenty-four months into the page
#    width — about 37px a month, which is where the mush came from. A month is
#    now the same width whether the project runs three weeks or three years, and
#    the chart scrolls sideways instead of shrinking.
#
# ⚠ THE NAMES COLUMN IS FROZEN and does not scroll with it. A chart you can
#   scroll but whose rows you can no longer identify is not an improvement.
PX_PER_DAY = 3.2

#: A month at the scale above is roughly 97px, which fits "Apr 2026" without
#: crowding. Kept as a name so the two are changed together and stay in step.
MIN_MONTH_PX = 88


def _px(days):
    """
    A width or an offset in pixels.

    ⚠ A ONE-DAY BAR IS 3.2px AND MUST STILL BE VISIBLE, so `min-width` lives in
      the STYLESHEET rather than being floored here. The arithmetic stays
      honest — a width inflated to be seeable would put the bar beside it in the
      wrong place, and on a scrolling chart that error accumulates all the way
      along the row.
    """
    return f"{max(0.0, days * PX_PER_DAY):.2f}"


def _pct(days, total):
    """
    ⚠ KEPT FOR THE TODAY MARKER AND NOTHING ELSE — see the note above. It is
      still the honest way to express "how far along the whole span is today",
      because that question really is about the proportion.
    """
    value = max(0.0, days * 100.0 / total) if total else 0.0
    return f"{value:.4f}"


def _bar(start, end, span_start, total):
    """
    One segment: where it begins and how wide it is, both inclusive of day one.

    ⚠ `total` IS NO LONGER USED FOR THE GEOMETRY and is kept only so every
      caller reads the same way. The width is pixels now — see
      ANCHOR: TASK-SCHEDULE-SCALE.
    """
    offset = (start - span_start).days
    length = (end - start).days + 1
    return {"left": _px(offset), "width": _px(max(1, length))}


# >>> ANCHOR: MILESTONE-LINE <<<
# How close two lines may be before their labels are stacked instead of sitting
# side by side.
#
# ⚠⚠ IN PIXELS, BECAUSE THE GEOMETRY IS IN PIXELS. This was a percentage of the
#    span while the chart scaled to the page, and switching to fixed pixels per
#    day made 6.0 mean six PIXELS — about two days — so nothing ever staggered
#    again. The chart still rendered perfectly and the labels sat on top of each
#    other, which is bug 24's shape exactly: a picture that looks right and is
#    not. A unit change is not a cosmetic change.
#
#    Roughly the width of a phase name at 10.5px, which is what has to clear.
LABEL_CLEARANCE = 90.0

#: How many rows of labels to cycle through before starting again. Two is enough
#: for the ordinary case of two phases finishing days apart; three covers a
#: cluster without pushing the strip so deep it needs its own scroll.
LABEL_LANES = 3


def _milestone_lines(headers, span_start, total):
    """
    One vertical dotted line per milestone, and where its label goes.

    ⚠⚠ THE DATE IS THE PHASE'S FINISH, AND IT IS COMPUTED, NEVER TYPED. It is
       the later of the promise and the work actually done, so when a task slips
       past the date the line moves with it. That is the same rule the rest of
       the module follows — a finish is captured, not declared — and it is why
       the old Milestone model had to go: it carried a date somebody typed,
       which could disagree with the work underneath it and never know.

    ⚠ LABELS STAGGER, LINES DO NOT MOVE. Saahil asked what happens when two
      phases finish days apart, and the honest answer was that their labels sit
      on top of each other. So a label that would collide with the previous one
      drops to the next lane; the line itself stays exactly on its date, because
      moving a line to make a label fit would be drawing a lie.
    """
    lines = []
    for header in headers:
        subtasks = list(header.subtasks.all())
        _work_start, work_end = header.work_span(subtasks)
        # max(), so a phase that ran over is marked where it really ended.
        finish = max(header.planned_end, work_end) if work_end else header.planned_end
        lines.append({
            "header": header,
            "date": finish,
            "left": _px((finish - span_start).days),
            "over": bool(header.days_over_plan(subtasks)),
        })

    lines.sort(key=lambda line: line["date"])

    # ⚠ THE LANE IS DECIDED AGAINST THE LAST LABEL PLACED IN EACH LANE, not
    #   against the previous line. Three phases within a fortnight otherwise all
    #   land in lane 1 the moment the second one has moved out of lane 0.
    last_in_lane = [None] * LABEL_LANES
    for line in lines:
        position = float(line["left"])
        for lane in range(LABEL_LANES):
            if last_in_lane[lane] is None or position - last_in_lane[lane] >= LABEL_CLEARANCE:
                line["lane"] = lane
                last_in_lane[lane] = position
                break
        else:
            # Every lane is crowded. Better a collision than a label hidden.
            line["lane"] = LABEL_LANES - 1
    return lines


def build(project, today=None):
    """
    Everything the chart needs, or None when there is nothing to draw.

    Returns `span`, `months`, `rows`, `milestones` and `today` — no model objects
    beyond the ones the template names, and no arithmetic left to do.
    """
    today = today or timezone.localdate()

    headers = list(
        TaskHeader.objects
        .filter(project=project)
        .select_related("activity", "owner")
        .prefetch_related("subtasks__assignee"))
    if not headers:
        return None

    # ---- the span -------------------------------------------------------
    starts = [header.start for header in headers]
    ends = [header.planned_end for header in headers]
    for header in headers:
        for subtask in header.subtasks.all():
            starts.append(subtask.start)
            # An open row that is already overdue keeps growing until it is
            # ticked, so the chart has to make room for today.
            ends.append(max(subtask.planned_end,
                            subtask.finished_on or (today if subtask.status != Subtask.Status.DONE
                                                    else subtask.planned_end)))
    span_start = _first_of_month(min(starts))
    span_end = _last_of_month(max(ends))
    total = (span_end - span_start).days + 1

    months = [{
        "label": f"{month:%b %Y}",
        "width": _px((min(_last_of_month(month), span_end)
                      - max(month, span_start)).days + 1),
    } for month in _months_between(span_start, span_end)]

    lines = _milestone_lines(headers, span_start, total)

    # ---- the rows -------------------------------------------------------
    rows = []
    for header in headers:
        subtasks = list(header.subtasks.all())
        done, count = header.progress(subtasks)
        _work_start, work_end = header.work_span(subtasks)
        over = header.days_over_plan(subtasks)

        # >>> ANCHOR: MILESTONE-LINE <<<
        # ⚠⚠ THE ROW DRAWS ITS OWN WINDOW AGAIN, AND THIS REVERSES A DECISION.
        #   When milestones first moved to a dotted line, the row's own bar was
        #   removed outright — but the legend and the CSS describing it (
        #   ".gbar.hdr", ".gbar.hdrover") were left behind, so the screen kept
        #   promising a band it never drew. Nobody noticed on a two-year job
        #   where every milestone had subtasks under it soon enough. Saahil
        #   found it on a sixteen-month project with two milestones and nothing
        #   under them yet: the row showed nothing at all — not even a hint of
        #   its own span — and asked for "the months... filled properly as per
        #   the user's input", i.e. what was actually typed: the header's own
        #   start and days.
        #
        #   So the band is BACK, drawn from `header.start` to `header.
        #   planned_end` — the window that was typed, exactly what the legend
        #   already named. It is not a duplicate of the dotted line: the band
        #   is the PROMISE, unconditional and present from the moment a
        #   milestone is created, whether or not it has subtasks yet; the line
        #   is the JUDGED finish, which moves out only once work underneath it
        #   proves the promise wrong. A milestone with no subtasks draws a band
        #   and no overrun, because nothing has yet disagreed with the plan.
        window_bar = _bar(header.start, header.planned_end, span_start, total)
        over_bar = (_bar(header.planned_end + timedelta(days=1), work_end, span_start, total)
                    if over else None)

        rows.append({
            "kind": "milestone",
            "header": header,
            "done": done,
            "count": count,
            "over": over,
            "bar": window_bar,
            "over_bar": over_bar,
        })

        for subtask in subtasks:
            finished = subtask.finished_on
            overdue = subtask.days_overdue(today)
            # The late tail: from the day after its date to the day it actually
            # finished, or to today while it is still open.
            tail_end = finished if finished and finished > subtask.planned_end else (
                today if overdue else None)

            rows.append({
                "kind": "subtask",
                "subtask": subtask,
                "late": subtask.days_late or overdue,
                "bar": _bar(subtask.start, subtask.planned_end, span_start, total),
                "late_bar": (_bar(subtask.planned_end + timedelta(days=1), tail_end,
                                  span_start, total) if tail_end else None),
            })

    return {
        "span": {"start": span_start, "end": span_end, "days": total},
        "months": months,
        "rows": rows,
        "milestones": lines,
        # ⚠ THE LANES ACTUALLY IN USE, so the template draws one label strip per
        #   lane rather than three whether or not they are needed.
        "milestone_lanes": sorted({line["lane"] for line in lines}),
        # ⚠ THE WHOLE TRACK'S WIDTH, so the scrolling container knows how far it
        #   has to reach. Everything inside is positioned against this.
        "track_px": _px(total),
        # None when today is outside the span, so a chart of last year's work
        # does not draw a marker jammed against one edge.
        "today": (_px((today - span_start).days)
                  if span_start <= today <= span_end else None),
        "today_date": today,
    }
