"""
Material rate trends — what one material has actually cost, order by order.

⚠ THE RATE IS THE ONE FROZEN ON THE DOCUMENT, EX-DISCOUNT: the line's taxable
    value divided by its quantity. That is the figure the vendor was actually
    held to, and it is read from `PurchaseOrderLine.taxable`, the same property
    the printed order uses — never re-derived from quantity and rate here.

⚠ ONLY DOCUMENTS THAT COMMIT — approved onward, on `approved_at`. A draft's
    rate is a hope, not a price, and it is left out exactly as it is left out
    of every committed figure (see analytics.money).

⚠ THE TOP FIFTEEN BY COMMITTED VALUE, not by number of orders. A material
    bought weekly in small lots is not where a rate change costs money; the
    question this screen answers is "did the price of what we spend on move".

⚠ ONE QUERY FOR EVERY LINE, THEN PYTHON. The lines carry their document and
    their material in the same fetch, and a test asserts that twenty more
    orders do not add queries.
"""
from decimal import Decimal

from analytics import money
from projects.bom_models import PurchaseOrderLine

ZERO = Decimal("0.00")
TOP = 15


def lines(project=None):
    """Every line on a committed document, oldest approval first."""
    rows = (PurchaseOrderLine.objects
            .filter(purchase_order__status__in=money.STAGE_STATUS["committed"],
                    purchase_order__approved_at__isnull=False)
            .select_related("purchase_order", "purchase_order__project",
                            "bom_line__material", "bom_line__material__group")
            .order_by("purchase_order__approved_at", "purchase_order_id", "id"))
    if project:
        rows = rows.filter(purchase_order__project=project)
    return list(rows)


def groups_in(lines):
    """
    The material groups that actually appear — the choices for the filter.

    ⚠ FROM THE LINES, NOT THE MASTER. Offering every group on a site that buys
      from four is the prototype dropdown that listed every project's header
      tasks — bug 14, again.
    """
    seen = {}
    for line in lines:
        group = line.bom_line.material.group
        if group is not None:
            seen[group.pk] = group.name
    return sorted(seen.items(), key=lambda item: item[1])


def _rate(line):
    """The frozen line rate after discount, or None when nothing was bought."""
    if not line.quantity:
        return None
    return (line.taxable / line.quantity).quantize(Decimal("0.01"))


def trend(lines, group_id=None, limit=TOP):
    """
    One row per material: the committed value, the rate on every document in
    approval order, and the min / average / latest with the change since the
    first.

    `group_id` narrows to one material group before the top `limit` is taken,
    so choosing a group shows that group's fifteen, not the fifteen overall
    that happen to fall in it.
    """
    rows = {}
    for line in lines:
        material = line.bom_line.material
        if group_id and material.group_id != group_id:
            continue
        rate = _rate(line)
        if rate is None:
            continue
        row = rows.setdefault(material.pk, {
            "material": material,
            "code": material.code,
            "label": material.name,
            "uom": material.uom,
            "group": material.group.name if material.group else "",
            "committed": ZERO,
            "points": [],
        })
        row["committed"] += line.taxable
        row["points"].append({
            "on": line.purchase_order.approved_at.date(),
            "rate": rate,
            "number": line.purchase_order.number,
        })

    ranked = sorted(rows.values(), key=lambda row: row["committed"], reverse=True)[:limit]
    for row in ranked:
        rates = [point["rate"] for point in row["points"]]
        first, latest = rates[0], rates[-1]
        row["first"] = first
        row["latest"] = latest
        row["low"] = min(rates)
        row["high"] = max(rates)
        row["average"] = (sum(rates, ZERO) / len(rates)).quantize(Decimal("0.01"))
        row["orders"] = len(rates)
        # ⚠ Change is latest against FIRST, not against the average — "what
        #   did it cost when we started, what does it cost now" is the question
        #   somebody renegotiating a rate actually asks.
        row["change_pct"] = (((latest - first) * 100 / first).quantize(Decimal("0.1"))
                             if first else None)
        row["rates"] = rates
    return ranked
