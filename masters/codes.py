"""
Material code generation.

WHAT THIS FILE IS FOR
    Producing the next material code, and nothing else.

WHAT DEPENDS ON IT
    Every material created by hand or by the Excel import.

THE FORMAT
    ACTIVITY-GROUP-SERIAL        e.g.  PLM-PL3-014
      PLM   the abbreviation of the material's HOME activity
      PL3   its group code
      014   a serial that restarts at 001 within each activity+group pair

THE TWO RULES THAT MATTER
    1. A code is assigned ONCE and NEVER regenerated. Reclassify a material and
       it keeps its old code. A code printed on a purchase order must never stop
       resolving, so a slightly stale code is the lesser evil.
    2. NOTHING PARSES A CODE. Never read `code[:3]` to work out the activity —
       use the foreign key. Parsing breaks silently the first time a material is
       reclassified, and the breakage looks like a data problem rather than a
       code problem.

SERIALS ARE NEVER REUSED
    Delete PLM-PL3-014 and the next plumbing material is 015, not 014. Reusing
    it would make an old purchase order point at a different material.
"""
import re

# >>> ANCHOR: CODE-GEN <<<
# Changing anything here changes every code generated from now on. It does NOT
# change codes that already exist — those are frozen. If you change the format,
# old and new codes will look different from each other, which is survivable
# (nothing parses them) but worth doing on purpose rather than by accident.

CODE_PATTERN = re.compile(r"^[A-Z]{3}-[A-Z0-9]{2,4}-(\d{3,})$")


def next_code(activity, group):
    """
    Return the next unused code for this activity and group.

    `activity` is a projects.Activity, `group` a masters.MaterialGroup.

    Looks at the highest serial already issued for the pair and adds one —
    including codes belonging to inactive or deleted-then-recreated materials,
    because serials are never reused.
    """
    from .models import Material                       # imported here to avoid a circular import

    if not activity.abbreviation:
        raise ValueError(
            f"Activity '{activity.name}' has no abbreviation, so no material code can be "
            f"built under it. Set a three-letter abbreviation on the activity first."
        )

    prefix = f"{activity.abbreviation}-{group.code}-"
    highest = 0
    for existing in Material.objects.filter(code__startswith=prefix).values_list("code", flat=True):
        match = CODE_PATTERN.match(existing)
        if match:
            highest = max(highest, int(match.group(1)))

    return f"{prefix}{highest + 1:03d}"


def is_valid(code):
    """True if `code` has the right shape. Says nothing about whether it exists."""
    return bool(CODE_PATTERN.match(code or ""))
