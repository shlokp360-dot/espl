"""
What state a drawing is in, worked out from what is on file.

>>> ANCHOR: DRAWINGS-STATUS <<<
⚠ DERIVED, NEVER TYPED. Nobody maintains a status column, so nothing can
    quietly disagree with the revisions actually held.

        REQUIRED    no revision has arrived
        RECEIVED    the newest revision is not approved
        APPROVED    the newest revision is approved

⚠ THE NEWEST REVISION IS THE ONLY ONE JUDGED. R1 arriving after an approved R0
    puts the drawing back to Received — the paper on site is no longer the
    paper that was approved, and the register must say so.

⚠ `latest_by_drawing` IS THE BULK HAND-DOWN. Every list screen fetches the
    newest revision for every drawing in ONE query and passes the map down; the
    `Drawing.status` property is for a single drawing and costs a query each.
"""
from drawings.models import DrawingRevision

REQUIRED = "required"
RECEIVED = "received"
APPROVED = "approved"

LABELS = {REQUIRED: "Required", RECEIVED: "Received", APPROVED: "Approved"}
PILLS = {REQUIRED: "p-draft", RECEIVED: "p-delivered", APPROVED: "p-approved"}
CHOICES = [(REQUIRED, "Required"), (RECEIVED, "Received"), (APPROVED, "Approved")]


def status_of(latest):
    """The state, given the newest revision (or None)."""
    if latest is None:
        return REQUIRED
    return APPROVED if latest.approved_on else RECEIVED


def latest_by_drawing(drawings):
    """
    {drawing id: newest revision} for a list of drawings, in one query.

    Rows come newest-first, so the first one seen per drawing is the current one.
    """
    ids = [drawing.id for drawing in drawings]
    if not ids:
        return {}
    latest = {}
    for revision in (DrawingRevision.objects
                     .filter(drawing_id__in=ids)
                     .select_related("approved_by", "uploaded_by")
                     .order_by("-uploaded_at", "-id")):
        latest.setdefault(revision.drawing_id, revision)
    return latest


def row_for(drawing, latest):
    """One register row: the drawing, its current revision and the derived state."""
    state = status_of(latest)
    return {"drawing": drawing, "latest": latest, "state": state,
            "label": LABELS[state], "pill": PILLS[state]}


def rows_for(drawings, latest=None):
    latest = latest_by_drawing(drawings) if latest is None else latest
    return [row_for(drawing, latest.get(drawing.id)) for drawing in drawings]


def summarise(rows):
    """Counts per state, for the KPIs and the overview."""
    counts = {REQUIRED: 0, RECEIVED: 0, APPROVED: 0}
    for row in rows:
        counts[row["state"]] += 1
    return {"counts": counts, "total": len(rows),
            "required": counts[REQUIRED], "received": counts[RECEIVED],
            "approved": counts[APPROVED]}
