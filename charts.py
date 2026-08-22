"""
Charts, drawn as SVG by hand.

>>> ANCHOR: ANALYTICS-CHARTS <<<

⚠ NO CHART LIBRARY, AND THAT IS NOT STUBBORNNESS. This app has not one static
    file — every stylesheet is inline — and the client's server will sit inside
    their own network with no promise of reaching a CDN. A chart that renders on
    a laptop and shows an empty box on the site office's machine is worse than a
    table.

⚠ THE GEOMETRY IS HERE, NOT IN THE TEMPLATE. The same rule that put the Gantt in
    `tasks/schedule.py` and every BOM figure in `bom_calc.py`: arithmetic in a
    template cannot be tested.

⚠ EVERY FUNCTION RETURNS SAFE MARKUP AND ESCAPES ITS LABELS. A vendor called
    "Shah & Co" put an ampersand through this once; `&` is not valid raw in SVG
    and the whole chart disappears rather than showing a wrong character.
"""
from decimal import Decimal

from django.utils.html import escape
from django.utils.safestring import mark_safe

#: A deliberately small palette. More colours than this and nobody can tell two
#: activities apart in a legend, which is the only place the colour is explained.
PALETTE = ["#2E5C9A", "#7d4bb3", "#0f828f", "#C55A11", "#6a6d70", "#107e3e",
           "#A32D2D", "#8A6D1F"]


def colour(index):
    return PALETTE[index % len(PALETTE)]


def _f(value):
    """Decimal or int to float, for geometry only — never for money on screen."""
    return float(value or 0)


def bars(rows, series, height=170):
    """
    A grouped bar chart. `rows` is [{"label": "Apr", "values": [a, b]}, …].

    ⚠ THE SCALE STARTS AT ZERO AND THERE IS NO OPTION NOT TO. A bar chart with a
      cropped axis makes a 3% difference look like a doubling, which is the
      oldest way to mislead somebody with a true number.
    """
    rows = list(rows)
    if not rows:
        return mark_safe('<p style="color:#6B7280;font-size:12px;margin:0">Nothing in this period.</p>')

    top = max([_f(value) for row in rows for value in row["values"]] + [1])
    width, pad_left, pad_bottom = 560, 8, 26
    plot = height - pad_bottom
    group = (width - pad_left) / len(rows)
    bar_w = min(26, (group - 10) / max(1, len(series)))

    parts = [f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" '
             f'role="img" style="overflow:visible">']

    # Four gridlines and their values, because a bar with no scale is a shape.
    for step in range(5):
        y = plot - plot * step / 4
        parts.append(f'<line x1="{pad_left}" y1="{y:.1f}" x2="{width}" y2="{y:.1f}" '
                     f'stroke="#E5E8EE" stroke-width="1"/>')

    for index, row in enumerate(rows):
        x0 = pad_left + index * group
        for slot, value in enumerate(row["values"]):
            value = _f(value)
            bar_h = plot * value / top if top else 0
            x = x0 + (group - bar_w * len(series)) / 2 + slot * bar_w
            parts.append(
                f'<rect x="{x:.1f}" y="{plot - bar_h:.1f}" width="{bar_w - 2:.1f}" '
                f'height="{max(0, bar_h):.1f}" fill="{series[slot]["colour"]}" rx="2"/>')
        parts.append(
            f'<text x="{x0 + group / 2:.1f}" y="{height - 8}" text-anchor="middle" '
            f'font-size="10.5" fill="#6B7280">{escape(row["label"])}</text>')

    parts.append("</svg>")
    return mark_safe("".join(parts))


def donut(slices, size=170):
    """
    Proportions, as a ring. `slices` is [{"label": …, "value": …, "colour": …}].

    ⚠ A RING RATHER THAN A PIE, and only ever with a legend beside it. Nobody
      reads an angle accurately; what a reader actually takes from this is "one
      of these is most of it", which is the honest limit of the shape.
    """
    slices = [row for row in slices if _f(row["value"]) > 0]
    total = sum(_f(row["value"]) for row in slices)
    if not total:
        return mark_safe('<p style="color:#6B7280;font-size:12px;margin:0">Nothing to show yet.</p>')

    radius, stroke = size / 2 - 12, 22
    circumference = 2 * 3.141592653589793 * radius
    parts = [f'<svg viewBox="0 0 {size} {size}" width="{size}" height="{size}" role="img">',
             f'<g transform="translate({size/2},{size/2}) rotate(-90)">']

    offset = 0.0
    for row in slices:
        share = _f(row["value"]) / total
        length = circumference * share
        parts.append(
            f'<circle r="{radius}" fill="none" stroke="{row["colour"]}" stroke-width="{stroke}" '
            f'stroke-dasharray="{length:.2f} {circumference - length:.2f}" '
            f'stroke-dashoffset="{-offset:.2f}"/>')
        offset += length

    parts.append("</g></svg>")
    return mark_safe("".join(parts))


def stacked(parts, height=30):
    """
    One horizontal bar split into shares. `parts` is [{"label", "value", "colour"}].

    ⚠ FOR THINGS THAT ADD UP TO A WHOLE, AND ONLY FOR THOSE. Settled plus owed
      plus not-yet-due IS the total obligation, so a single bar is the honest
      picture — one glance says what proportion of the money has actually left
      the bank. Using this shape for figures that do not sum to something real
      would be a lie told with geometry.
    """
    parts = [row for row in parts if _f(row["value"]) > 0]
    total = sum(_f(row["value"]) for row in parts)
    if not total:
        return mark_safe('<p style="color:#6B7280;font-size:12px;margin:0">Nothing approved yet.</p>')

    out = ['<div style="display:flex;height:%dpx;border-radius:5px;overflow:hidden;'
           'border:1px solid #D6DCE4">' % height]
    for row in parts:
        pct = _f(row["value"]) * 100 / total
        out.append(
            f'<div style="width:{pct:.4f}%;background:{row["colour"]};display:flex;'
            f'align-items:center;justify-content:center;color:#fff;font-size:10.5px;'
            f'font-weight:600" title="{escape(row["label"])}">'
            f'{round(pct) if pct >= 9 else ""}{"%" if pct >= 9 else ""}</div>')
    out.append("</div>")
    return mark_safe("".join(out))


def hbars(rows, colour_of=None, height=16, maximum=None):
    """
    A ranked horizontal bar list — the shape for "who costs most".

    ⚠ RANKED AND LABELLED IN TEXT, not a legend. With ten vendors a donut is
      unreadable and a legend is a lookup table; a sorted list of bars can be
      read top to bottom without moving your eyes off the row.

    ⚠⚠ THE BAR MUST BE THE SAME MEASURE AS THE NUMBER BESIDE IT. Saahil caught
      this on the Buying page: the bars were committed RUPEES ranked against the
      biggest trade, and the figure printed beside each was that trade's own
      PERCENTAGE of budget — so the longest bar read 1% and a short one read 39%.
      The chart said the opposite of its own labels.

      `value` is what the bar is; `display` is what is printed. If they are not
      the same quantity, the chart is lying. There is a test.

    ⚠ `maximum` FIXES THE SCALE. For percentages pass 100 — otherwise the
      biggest row fills the track whatever it is, so three trades at 1%, 3% and
      12% would draw as a short, a medium and a full bar, and 12% would look
      like the budget was gone.
    """
    rows = [row for row in rows if _f(row["value"]) > 0]
    if not rows:
        return mark_safe('<p style="color:#6B7280;font-size:12px;margin:0">Nothing to show yet.</p>')

    top = maximum or max(_f(row["value"]) for row in rows)
    out = ['<div style="display:grid;gap:5px">']
    for index, row in enumerate(rows):
        width = _f(row["value"]) * 100 / top
        fill = row.get("colour") or (colour_of(index) if colour_of else colour(index))
        out.append(
            f'<div style="display:flex;align-items:center;gap:8px;font-size:11.5px">'
            f'<span style="flex:0 0 130px;color:#26282B;overflow:hidden;text-overflow:ellipsis;'
            f'white-space:nowrap">{escape(row["label"])}</span>'
            f'<span style="flex:1;background:#EDEFF3;border-radius:3px;height:{height}px">'
            f'<span style="display:block;width:{width:.4f}%;background:{fill};height:{height}px;'
            f'border-radius:3px"></span></span>'
            f'<span style="flex:0 0 96px;text-align:right;font-variant-numeric:tabular-nums;'
            f'color:#26282B">{escape(row["display"])}</span></div>')
    out.append("</div>")
    return mark_safe("".join(out))


def waterfall_steps(rows):
    """
    Turn the ladder into bar geometry — **as numbers**, before anything is drawn.

    >>> ANCHOR: ANALYTICS-WATERFALL <<<

    `rows` is [{"label", "amount", "kind"}] where kind is:
        "start"  the opening figure — a bar from zero
        "add"    a step up      (amount positive)
        "less"   a step down    (amount positive, drawn downwards)
        "total"  a subtotal — a bar from zero at the running balance

    ⚠ THE GEOMETRY IS TESTED AS ARITHMETIC AND THE SVG IS DUMB. A waterfall that
      is one step out looks like a plausible chart; nobody checks a picture
      against the ladder it came from. So every bar's top, bottom and running
      balance is computed here and asserted in the tests, and `waterfall()`
      below only turns those numbers into rectangles.

    ⚠ A "total" ROW IS NOT ADDED TO THE RUNNING BALANCE. It restates it. Adding
      it would double every subtotal — which is the classic way to get a
      waterfall wrong, and the reason this function exists apart from the
      drawing.
    """
    running = 0.0
    out, top = [], 0.0
    for row in rows:
        amount = _f(row["amount"])
        kind = row["kind"]
        if kind == "start":
            low, high, running = 0.0, amount, amount
        elif kind == "add":
            low, high = running, running + amount
            running += amount
        elif kind == "less":
            low, high = running - amount, running
            running -= amount
        else:                                   # total — restates, never adds
            low, high, running = 0.0, running, running
        out.append({
            "label": row["label"], "kind": kind, "amount": amount,
            "low": min(low, high), "high": max(low, high), "running": running,
        })
        top = max(top, abs(high), abs(low))
    return out, top or 1.0


def waterfall(rows, height=260, money=str):
    """The ladder as bars stepping down. `money` formats the label on each bar."""
    steps, top = waterfall_steps(rows)
    width, pad_bottom, pad_top = 700, 46, 18
    plot = height - pad_bottom - pad_top
    slot = width / max(1, len(steps))
    bar_w = min(52, slot - 10)

    def y(value):
        return pad_top + plot - (value / top) * plot

    parts = [f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" role="img">']
    for index, step in enumerate(steps):
        x = index * slot + (slot - bar_w) / 2
        high, low = y(step["high"]), y(step["low"])
        fill = ("#1F3864" if step["kind"] == "total"
                else "#107e3e" if step["kind"] == "start"
                else "#A32D2D" if step["kind"] == "less" else "#2E5C9A")
        parts.append(
            f'<rect x="{x:.1f}" y="{high:.1f}" width="{bar_w:.1f}" '
            f'height="{max(2, low - high):.1f}" fill="{fill}" rx="2"/>')
        # ⚠ THE AMOUNT IS ON THE BAR. A waterfall whose steps are unlabelled is
        #   a shape; the reader needs to add them up themselves to trust it.
        parts.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{high - 4:.1f}" text-anchor="middle" '
            f'font-size="9.5" fill="#26282B">{escape(money(step["amount"]))}</text>')
        for line, dy in zip(escape(step["label"]).split(" "), range(0, 99, 11)):
            parts.append(
                f'<text x="{x + bar_w / 2:.1f}" y="{height - pad_bottom + 13 + dy:.1f}" '
                f'text-anchor="middle" font-size="9.5" fill="#6B7280">{line}</text>')
        # The dotted carry line to the next bar, which is what makes it read as
        # a ladder rather than as a row of unrelated bars.
        if index + 1 < len(steps) and step["kind"] != "total":
            parts.append(
                f'<line x1="{x + bar_w:.1f}" y1="{y(step["running"]):.1f}" '
                f'x2="{(index + 1) * slot + (slot - bar_w) / 2:.1f}" '
                f'y2="{y(step["running"]):.1f}" stroke="#C3C9D4" stroke-dasharray="3 3"/>')
    parts.append("</svg>")
    return mark_safe("".join(parts))


def heatmap(rows, columns, value_of, label_of=str, legend=("low", "high")):
    """
    Two categories and one measure. `rows` are the row keys, `columns` the column
    keys, `value_of(row, column)` the number in the cell.

    ⚠ THE SCALE IS RELATIVE TO THE BIGGEST CELL, and the legend says so. An
      absolute scale would leave a quiet month looking identical to an empty one.

    ⚠ READABLE IN GREY. The ramp goes light-to-dark rather than green-to-red, so
      a printed copy still shows where the heat is — and so the eight percent of
      men who cannot separate red from green can read it at all.
    """
    cells = [[value_of(row, column) for column in columns] for row in rows]
    top = max([_f(value) for line in cells for value in line] + [0]) or 1.0

    out = ['<div style="overflow:auto"><table style="border-collapse:collapse;font-size:11.5px">',
           '<thead><tr><th style="background:none;color:#6B7280;text-align:left;padding:3px 8px"></th>']
    for column in columns:
        out.append(f'<th style="background:none;color:#6B7280;font-weight:600;padding:3px 8px">'
                   f'{escape(label_of(column))}</th>')
    out.append("</tr></thead><tbody>")

    for row, line in zip(rows, cells):
        out.append(f'<tr><td style="border:none;padding:3px 8px;white-space:nowrap;'
                   f'max-width:170px;overflow:hidden;text-overflow:ellipsis">'
                   f'{escape(label_of(row))}</td>')
        for value in line:
            share_of = _f(value) / top
            # A pale floor, so an empty cell still reads as a cell.
            shade = f"rgba(163,45,45,{0.08 + share_of * 0.82:.3f})" if _f(value) else "#F4F5F7"
            colour_text = "#fff" if share_of > 0.55 else "#26282B"
            out.append(
                f'<td style="border:1px solid #fff;padding:4px 9px;text-align:right;'
                f'background:{shade};color:{colour_text};font-variant-numeric:tabular-nums">'
                f'{escape(str(value)) if _f(value) else "·"}</td>')
        out.append("</tr>")
    out.append("</tbody></table></div>")
    out.append(f'<div style="font-size:10.5px;color:#6B7280;margin-top:6px">'
               f'{escape(legend[0])} → {escape(legend[1])}, shaded against the largest cell</div>')
    return mark_safe("".join(out))


def share(value, total):
    """A percentage as a whole number, and zero rather than an error at zero."""
    if not total:
        return 0
    return int(round(Decimal(value) * 100 / Decimal(total)))
