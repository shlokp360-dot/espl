"""
Seeds the Activity master with the 16 standard trades plus Others and Common.

WHY THIS IS A MIGRATION AND NOT A ONE-OFF SCRIPT
    Nothing else can be imported until these rows exist — a material's code
    starts with an activity abbreviation, so the activity has to be there first.
    Putting it in a migration means a fresh database is usable immediately, and
    the seed is version-controlled rather than living in someone's notes.

WHERE THE NUMBERS COME FROM
    The ACTIVITIES tab of MATERIAL_MASTER.xlsx, which is the same list the BOQ
    prototype uses. Composite of the 16 trades = Rs 1,433/sqft, validated
    against Bhudarpura at Rs 1,843.12/sqft including contingency, design fee
    and GST — within 3.0% of the actual built cost.

    ALL RATES ARE EX-GST. See the GST note at the top of projects/models.py.

REVERSIBLE
    Rolling back deletes only rows that are still untouched. Anything already
    referenced by a project or a material is left alone, because deleting it
    would orphan those records.
"""
from django.db import migrations


# abbreviation, name, rate (Rs/sqft, ex-GST), sort_order, basis
ACTIVITIES = [
    ("PRE", "Preliminaries & Site Overheads", "60.00", 10,
     "Mobilization, temp works, site supervision, security, site expenses"),
    ("ERT", "Earthwork", "30.00", 20,
     "Excavation, backfilling, disposal, anti-termite treatment"),
    ("RCC", "RCC (Structural — footing, column, beam, slab)", "600.00", 30,
     "M25 concrete, Fe500 steel, formwork. Steel ~4.5 kg/sqft"),
    ("MAS", "Masonry (blocks/bricks + DPC)", "160.00", 40,
     "AAC block 200mm external walls in CM 1:6 or block adhesive"),
    ("PLS", "Plaster (Internal + External)", "90.00", 50,
     "Internal 12mm CM 1:4; external 15-20mm CM 1:5/1:6"),
    ("WPF", "Waterproofing", "15.00", 60,
     "Wet areas, terrace and sunken slabs — PU / brickbat coba, 2 coats"),
    ("FLR", "Flooring & Tiling (incl. dado, skirting, granite)", "130.00", 70,
     "Vitrified tiles main areas, anti-skid in wet areas, granite to stairs"),
    ("HKP", "Housekeeping, Polishing & Buffing", "15.00", 80,
     "Site cleaning through the build, final polish and buffing at handover"),
    ("DRW", "Doors & Windows", "95.00", 90,
     "Flush/laminated doors with frame & hardware, aluminium windows"),
    ("FAB", "Fabrication Work", "15.00", 100,
     "MS railings, grills, gates, structural steel fabrication on site"),
    ("PLM", "Plumbing & Sanitary (incl. water storage)", "65.00", 110,
     "CPVC internal supply, UPVC external, SWR drainage, UGWT/OHWT"),
    ("ELE", "Electrical", "55.00", 120,
     "Concealed PVC conduit, FRLS copper wiring (IS 694), unit DBs"),
    ("INF", "Internal Finishes (paint, ironmongery, minor fixings)", "35.00", 130,
     "2-coat acrylic emulsion over primer"),
    ("EXF", "External Finishes (texture, exterior paint)", "35.00", 140,
     "Exterior weatherproof paint / texture finish"),
    ("FIR", "Fire Fighting", "30.00", 150,
     "Wet riser, hydrant, hose reel, portable extinguishers"),
    ("SFT", "Safety & PPE", "3.00", 160,
     "Helmets, harnesses, nets, barricading and site safety provisions"),

    # Rate 0.00 on the two below is DELIBERATE and needs Saahil's decision.
    # A zero rate means a zero reserve, so anything spent under them shows as
    # entirely unbudgeted. That is the correct signal for Others; for Common it
    # is a placeholder until a rate is agreed.
    ("OTH", "Others", "0.00", 900,
     "Catch-all, always present, never removed. Holds custom BOQ parameters and "
     "purchases whose trade was deselected. Spend landing here was never quoted — "
     "that is a useful signal, not a leftovers bin."),
    ("COM", "Common (used across all activities)", "0.00", 910,
     "Consumables used across every trade — wall plugs, fevicol, hacksaw blades. "
     "Available on the BOQ like any other activity; NEEDS A RATE SETTING."),
]


def seed(apps, schema_editor):
    """
    Create any activity that is missing. Never overwrites an existing row.

    Matches on abbreviation OR name, not just abbreviation. That looks
    over-careful until you roll this migration back and re-apply it: rolling
    back 0002 DROPS the abbreviation column, so a surviving row keeps its name
    but loses its abbreviation. Matching on abbreviation alone would then try to
    create a second row with the same name and fail on the unique constraint.
    Caught by an actual rollback test, not by reading the code.
    """
    Activity = apps.get_model("projects", "Activity")
    for abbreviation, name, rate, sort_order, basis in ACTIVITIES:
        row = (Activity.objects.filter(abbreviation=abbreviation).first()
               or Activity.objects.filter(name=name).first())

        if row is None:
            Activity.objects.create(
                abbreviation=abbreviation, name=name, rate=rate,
                gst_percent="18.00", sort_order=sort_order, basis=basis, is_active=True,
            )
            continue

        # Matched by NAME but carrying a different abbreviation. This happens
        # after a rollback: 0002 dropped the column, and on re-apply its
        # placeholder filler gave the surviving row something meaningless like
        # A0A. For these 18 canonical activities the abbreviation in this file
        # is the correct one, so put it back — but only if no other row already
        # holds it, so we can never break the unique constraint.
        if row.abbreviation != abbreviation:
            taken = Activity.objects.filter(abbreviation=abbreviation).exclude(pk=row.pk).exists()
            if not taken:
                row.abbreviation = abbreviation
                row.save(update_fields=["abbreviation"])


def unseed(apps, schema_editor):
    """
    Remove seeded activities that nothing points at yet.

    Deliberately conservative: an activity used by a project estimate or by a
    material is LEFT IN PLACE, because deleting it would orphan those records.
    That mirrors the delete rule used everywhere else in this system — block the
    delete when something references it, rather than cascading.
    """
    Activity = apps.get_model("projects", "Activity")
    for abbreviation, *_ in ACTIVITIES:
        row = Activity.objects.filter(abbreviation=abbreviation).first()
        if row and not row.material_links.exists():
            row.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0002_rename_tradedefault_to_activity"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
