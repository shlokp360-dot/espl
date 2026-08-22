"""
Formatting numbers the way they are read in India. FORMATTING ONLY.

WHAT THIS FILE IS FOR
    Turning a number into the text on screen — 1,20,45,000 rather than
    120,45,000 or 12,045,000. Nothing here decides what a number IS.

⚠ WHAT MUST NEVER GO IN HERE
    Any arithmetic that means something to the business. Every derived BOM
    figure belongs in bom_calc.py and nowhere else — see ANCHORS.md. A filter
    that quietly multiplied, subtracted or defaulted a value would be a second
    place the rules live, which is exactly the failure this project has already
    had once (To Order computed in three places in the prototype).

    Multiplying a fraction by 100 to print it as a percentage is presentation,
    not arithmetic: 0.842 and 84.2% are the same fact written two ways.

INDIAN DIGIT GROUPING
    The last three digits, then twos.  1234567  ->  12,34,567
    Django's `intcomma` groups in threes throughout, which reads wrong here.
"""
from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


def _to_decimal(value):
    """Anything -> Decimal, or None when it simply is not a number."""
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _group_indian(digits):
    """
    '1234567' -> '12,34,567'.  Last three, then pairs, as everyone here reads it.
    """
    if len(digits) <= 3:
        return digits
    last_three, rest = digits[-3:], digits[:-3]
    pairs = []
    while len(rest) > 2:
        pairs.insert(0, rest[-2:])
        rest = rest[:-2]
    if rest:
        pairs.insert(0, rest)
    return ",".join(pairs + [last_three])


def _format(value, places):
    number = _to_decimal(value)
    if number is None:
        return ""
    quantum = Decimal(1).scaleb(-places) if places else Decimal(1)
    rounded = number.quantize(quantum)
    sign = "-" if rounded < 0 else ""
    text = f"{abs(rounded):.{places}f}"
    whole, _, fraction = text.partition(".")
    grouped = sign + _group_indian(whole)
    return f"{grouped}.{fraction}" if fraction else grouped


@register.filter
def rupees(value):
    """Whole rupees. 4269.66 -> 4,270. Used wherever paise are noise."""
    return _format(value, 0)


@register.filter
def rupees2(value):
    """Rupees and paise. 4269.66 -> 4,269.66. Used for rates."""
    return _format(value, 2)


@register.filter
def qty(value):
    """
    A quantity, with trailing zeros dropped: 1200.000 -> 1,200, 2.500 -> 2.5.
    Quantities are stored to three decimals but almost always whole, and a
    column of 1,200.000 is harder to scan than a column of 1,200.
    """
    number = _to_decimal(value)
    if number is None:
        return ""
    if number == number.to_integral_value():
        return _format(number, 0)
    # Up to two decimals, with any trailing zero dropped: 2.500 -> 2.5, not 2.50.
    text = _format(number, 2)
    return text.rstrip("0").rstrip(".")


@register.filter
def pct(value, places=1):
    """A fraction as a percentage: 0.842 -> 84.2%. Same fact, different notation."""
    number = _to_decimal(value)
    if number is None:
        return ""
    return f"{number * 100:.{int(places)}f}%"


_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
         "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen",
         "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _under_hundred(n):
    if n < 20:
        return _ONES[n]
    return _TENS[n // 10] + (" " + _ONES[n % 10] if n % 10 else "")


def _under_thousand(n):
    if n < 100:
        return _under_hundred(n)
    return _ONES[n // 100] + " Hundred" + (" " + _under_hundred(n % 100) if n % 100 else "")


@register.filter
def rupees_words(value):
    """
    A whole-rupee amount spelled out, Indian style: crore, lakh, thousand.

    Standard on an Indian purchase order, and it is a real safeguard rather than
    decoration — a figure and its words disagreeing is how an altered document
    gets noticed.

    FORMATTING ONLY, like everything else in this file: it re-reads a number, it
    never decides one.
    """
    number = _to_decimal(value)
    if number is None:
        return ""
    whole = int(number.quantize(Decimal(1)))
    if whole == 0:
        return "Rupees Zero Only"

    sign = "Minus " if whole < 0 else ""
    whole = abs(whole)
    crore, whole = divmod(whole, 10_000_000)
    lakh, whole = divmod(whole, 100_000)
    thousand, rest = divmod(whole, 1000)

    parts = []
    if crore:
        parts.append(_under_thousand(crore) + " Crore")
    if lakh:
        parts.append(_under_thousand(lakh) + " Lakh")
    if thousand:
        parts.append(_under_thousand(thousand) + " Thousand")
    if rest:
        parts.append(_under_thousand(rest))
    return f"{sign}Rupees " + " ".join(parts) + " Only"


@register.filter
def bar_width(value):
    """
    A fraction as a CSS width percentage, capped at 100 so a bar cannot run off
    its track. The uncapped figure is printed beside it, so nothing is hidden.
    """
    number = _to_decimal(value)
    if number is None:
        return "0"
    capped = min(Decimal("1"), max(Decimal("0"), number))
    return f"{capped * 100:.1f}"
