"""
The period selector: PTD and CPD, on an Indian fiscal year.

>>> ANCHOR: ANALYTICS-PERIOD <<<

⚠ APRIL TO MARCH, EVERYWHERE. Saahil's answer when analytics was designed, and
    it is not a preference — every figure on these pages will eventually be read
    beside something their CA produced, and their CA works in fiscal years.
    A calendar year here would make two documents that should agree disagree.

⚠ TWO PERIODS ON EVERY PAGE, NOT A DATE RANGE PICKER.

      PTD   period to date — 1 April of the current fiscal year to today.
            "How are we doing this year."
      CPD   current period — ONE month, chosen from a list.
            "What happened in July."

    A free date range looks more powerful and is worse: two people comparing
    "the last quarter" pick different quarters, and neither notices. Two fixed
    shapes can be quoted at each other across a table.

⚠ ONLY MONTHS THAT HAVE STARTED ARE OFFERED. A month picker listing March next
    year invites somebody to open an empty page and wonder what broke.
"""
from datetime import date, timedelta

FY_START_MONTH = 4


def fiscal_start(day):
    """The 1 April that begins the fiscal year `day` falls in."""
    year = day.year if day.month >= FY_START_MONTH else day.year - 1
    return date(year, FY_START_MONTH, 1)


def fiscal_label(start):
    """`FY 2026-27` — the form their CA writes."""
    return f"FY {start.year}-{str(start.year + 1)[2:]}"


def months_so_far(today):
    """
    Every month of this fiscal year that has begun, oldest first.

    Each entry is `(key, label)` — `("2026-07", "Jul 2026")`. The key is what
    travels in the query string, because it sorts and cannot be misread as a
    date in the wrong order.
    """
    start = fiscal_start(today)
    out, year, month = [], start.year, start.month
    while (year, month) <= (today.year, today.month):
        first = date(year, month, 1)
        out.append((f"{year:04d}-{month:02d}", f"{first:%b %Y}"))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


def _month_end(first):
    return date(first.year + 1, 1, 1) if first.month == 12 else date(
        first.year, first.month + 1, 1)


def bounds(today, month=None):
    """
    The window a page is about.

    `month=None` (or an unreadable one) gives PTD: 1 April to today.
    `month="2026-07"` gives that month — and never past today, so the current
    month reads "1 July to today" rather than promising a fortnight that has not
    happened yet.

    Returns `(start, end, label, kind)`.
    """
    start_of_year = fiscal_start(today)

    if month:
        try:
            year, number = (int(part) for part in month.split("-"))
            first = date(year, number, 1)
        except (ValueError, TypeError):
            first = None
        if first and start_of_year <= first <= today:
            last = min(today, _month_end(first) - timedelta(days=1))
            return first, last, f"{first:%B %Y}", "CPD"

    return start_of_year, today, f"{fiscal_label(start_of_year)} to date", "PTD"
