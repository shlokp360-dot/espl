"""
What a compliance line is, worked out from the documents against it.

>>> ANCHOR: COMPLIANCE-STATUS <<<

⚠⚠ DERIVED, NEVER TYPED. Nobody maintains a status field, so nothing can quietly
    disagree with reality. The same principle as delay days on a task being
    computed rather than declared — and the same reason: a stored status is only
    correct until the day nobody remembers to change it.

THE SIX ANSWERS, and what each means to somebody standing in front of an
inspector:

    MISSING       nothing has ever been uploaded
    HELD          a one-time document is filed. Nothing more to do, ever.
    VALID         it has a validity and that date is comfortably away
    EXPIRING      inside 60 days. The renewal has to start now.
    EXPIRED       the date has passed. This is the state that hurts.
    DUE_AGAIN     a quarterly filing whose newest document is over a quarter old

⚠ EXPIRING IS 60 DAYS, AND THE REMINDER IS A SEPARATE QUESTION. Sixty gives a
    municipal renewal time to move; the reminder AT 60 and 30 needs a
    notification channel that has not been chosen, and is flagged in
    `OPEN-BEFORE-GO-LIVE.md`. The COLOUR on the screen does not wait for that.

⚠ THE REAL FAILURE IS NOT A MISSING DOCUMENT. It is one that quietly lapsed —
    which is why EXPIRED and EXPIRING are their own answers rather than a blank.
"""
from datetime import timedelta

from django.utils import timezone

from compliance.models import Kind

MISSING = "missing"
HELD = "held"
VALID = "valid"
EXPIRING = "expiring"
EXPIRED = "expired"
DUE_AGAIN = "due_again"

#: The window in which a renewal has to be started.
EXPIRING_WITHIN_DAYS = 60

#: How stale a quarterly filing may be before it is due again.
REPEAT_AFTER_DAYS = 92

LABELS = {
    MISSING: "Missing",
    HELD: "Held",
    VALID: "Valid",
    EXPIRING: "Expiring",
    EXPIRED: "Expired",
    DUE_AGAIN: "Due again",
}

#: The pill class each answer wears. Red is only ever for something that is
#: actually wrong today.
PILLS = {
    MISSING: "p-lost",
    HELD: "p-delivered",
    VALID: "p-delivered",
    EXPIRING: "p-onsheet",
    EXPIRED: "p-nogst",
    DUE_AGAIN: "p-onsheet",
}

#: Everything a manager should be chased about, in the order it hurts.
NEEDS_ATTENTION = [EXPIRED, MISSING, EXPIRING, DUE_AGAIN]


def state_of(item, documents, today=None):
    """
    One line's answer. `documents` is that item's documents on ONE project,
    newest first — the ordering the model already guarantees.

    Returns `(state, latest, days)` where `days` is the number the screen prints
    beside the state: days to expiry, or days since the last filing, or None.
    """
    today = today or timezone.localdate()
    latest = documents[0] if documents else None

    if latest is None:
        return MISSING, None, None

    if item.kind == Kind.ONE:
        # ⚠ A ONE-TIME DOCUMENT IS NEVER "VALID" OR "EXPIRED". It is held. Giving
        #   it an expiry it does not have would put a permanent approval on a
        #   renewal list forever.
        return HELD, latest, None

    if item.kind == Kind.REPEAT:
        age = (today - latest.uploaded_at.date()).days
        return (DUE_AGAIN if age > REPEAT_AFTER_DAYS else HELD), latest, age

    # VALID — and an expiry that was never typed cannot be judged.
    if latest.expires_on is None:
        return HELD, latest, None

    days = (latest.expires_on - today).days
    if days < 0:
        return EXPIRED, latest, days
    if days <= EXPIRING_WITHIN_DAYS:
        return EXPIRING, latest, days
    return VALID, latest, days


def rows_for(project, items, documents, today=None):
    """
    Every item on a project with its state, in one pass.

    ⚠ THE DOCUMENTS ARE PASSED IN, NOT FETCHED HERE. The caller reads them once
      for the whole project — otherwise this is a query per line, on a screen
      that will hold sixty of them.
    """
    today = today or timezone.localdate()
    by_item = {}
    for document in documents:
        by_item.setdefault(document.item_id, []).append(document)

    out = []
    for item in items:
        held = by_item.get(item.pk, [])
        state, latest, days = state_of(item, held, today)
        out.append({
            "item": item,
            "state": state,
            "label": LABELS[state],
            "pill": PILLS[state],
            "days": days,
            "latest": latest,
            "history": held[1:],
            "count": len(held),
            "attention": state in NEEDS_ATTENTION and item.is_compulsory,
        })
    return out


def summarise(rows):
    """Counts by state, plus the one number a manager reads first."""
    counts = {state: 0 for state in LABELS}
    for row in rows:
        counts[row["state"]] += 1
    return {
        "counts": counts,
        "total": len(rows),
        # ⚠ COMPULSORY ONLY. An optional document that is missing is not a
        #   problem, and counting it as one teaches people to ignore the number.
        "attention": sum(1 for row in rows if row["attention"]),
        "held": counts[HELD] + counts[VALID],
        "percent": int(round((counts[HELD] + counts[VALID]) * 100 / len(rows))) if rows else 0,
    }


def expiring_soon(documents, today=None, within=EXPIRING_WITHIN_DAYS):
    """
    Everything with a validity, in date order — the timeline screen.

    ⚠ EXPIRED ONES COME FIRST AND ARE NEVER DROPPED. A list that only looked
      forward would hide the exact failure this module exists to prevent.
    """
    today = today or timezone.localdate()
    horizon = today + timedelta(days=within)
    dated = [document for document in documents
             if document.expires_on and document.expires_on <= horizon]
    return sorted(dated, key=lambda document: document.expires_on)
