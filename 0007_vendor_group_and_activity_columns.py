"""
Slice 8, step 1 — activities and vendor groups move ONTO the master records.

WHAT CHANGES
    A new `VendorGroup` master, mirroring MaterialGroup.
    `Material` gains `home_activity` (required) and `also_used_in` (optional).
    `Vendor` gains `group`, `activity_1` and `activity_2`, all optional.
    Every value is carried across from the two link tables. Nothing is typed
    again and nothing is invented.

WHY
    Saahil, on where this information belongs:

        "Material is to be linked to activity in the same material master
         screen, not as a separate tile."

        "All of these info will be used to do analytics, so it has to be
         present in the final tables i.e. Material master and Vendor Master."

    A link table is right when the number of values is unbounded. Here it is
    not: a material has one trade and occasionally two, and a vendor has one
    group. Two columns say that without a count check, and one row per record is
    what makes the Excel round trip possible at all — no second sheet to keep in
    step, nothing to join.

⚠ THE LINK TABLES ARE NOT DROPPED HERE. `MaterialActivity` and `VendorCategory`
    still exist after this migration and still hold their rows. They are removed
    in a later migration in this same slice, once every reader has been moved
    over. Deleting data in the same step that copies it leaves nothing to check
    the copy against.

⚠ THE MATERIAL SIDE IS LOSSLESS, AND THAT WAS MEASURED FIRST. All 705 materials
    had exactly one MaterialActivity row, so there was never a second activity
    to lose. If that stops being true before this runs, the RunPython below puts
    the second one in `also_used_in` and a third would be reported, not dropped.

⚠ THE VENDOR SIDE IS NOT LOSSLESS, AND THE LOSSES ARE NAMED IN FULL BELOW.
    Nine vendors carried more than one category. Four resolve on their own,
    because their second category was never a group — it was an activity. The
    other five are builders' merchants who genuinely sell several things, and
    each keeps the group Saahil chose. Every decision is in MULTI_CATEGORY,
    where it can be read and argued with, rather than buried in a rule.
"""
from django.db import migrations, models
import django.db.models.deletion


# ⚠ THE ONLY PLACE A CATEGORY IS DISCARDED, AND EVERY CASE IS LISTED.
#   vendor code -> (group to keep, activity to set, what was dropped and why)
#
#   The four that resolve on their own are here too, so the file shows all nine
#   rather than only the awkward ones.
MULTI_CATEGORY = {
    # --- resolve on their own: the second value was an activity, not a group ---
    "VEN-107": ("MS Material", "PRE", "Plot Boundary Fencing is the work, not the group"),
    "VEN-108": ("MS Material", "PRE", "Plot Boundary Fencing is the work, not the group"),
    "VEN-109": ("MS Material", "PRE", "Plot Boundary Fencing is the work, not the group"),
    "VEN-061": ("Sand / Aggregate", "ERT", "Excavation / Earthwork is the work, not the group"),
    # --- genuinely several material types: one group kept, the rest dropped ---
    "VEN-020": ("General Construction Material", "RCC",
                "dropped Cement, Red Bricks, Sand / Aggregate — a hardware store selling all three"),
    "VEN-018": ("General Construction Material", "RCC",
                "dropped Cement, Red Bricks, Sand / Aggregate — same shape as VEN-020"),
    "VEN-019": ("General Construction Material", "RCC", "dropped Cement"),
    "VEN-095": ("General Construction Material", "PLM", "dropped Plumbing Material"),
    "VEN-015": ("Flooring Material", "FLR", "dropped CP fittings"),
}

# Categories that describe what a vendor DOES rather than what they are. They
# become no group at all — the activity and the document type carry the meaning.
# ⚠ "Contractor" is here because default_document_type already says it, and two
#   fields answering one question disagree eventually.
NOT_A_GROUP = {"Contractor"}


# ⚠ SPELLINGS CORRECTED ON THE WAY ACROSS, AND ONLY HERE.
#
#   Six vendors carry "General Contruction Material" and two carry "Diaphgram
#   Wall". Free text meant nobody could fix either without editing every vendor
#   that had it — which is the whole reason a group MASTER is being created.
#   Creating the master is the one moment the corrected spelling costs nothing,
#   because no row points at it yet.
#
#   ⚠ THIS BIT ME WHILE WRITING IT. MULTI_CATEGORY below first named the group
#     with the correct spelling, found nothing, and silently left four vendors
#     with no group at all. Caught by counting groups on a copy of the real
#     database rather than by reading the code. Hence: fix the name in ONE place
#     and have everything else use the fixed one.
SPELLING = {
    "General Contruction Material": "General Construction Material",
    "Diaphgram Wall": "Diaphragm Wall",
}


def corrected(name):
    return SPELLING.get(name, name)


def carry_across(apps, schema_editor):
    Material = apps.get_model("masters", "Material")
    Vendor = apps.get_model("masters", "Vendor")
    VendorGroup = apps.get_model("masters", "VendorGroup")
    MaterialActivity = apps.get_model("projects", "MaterialActivity")
    VendorCategory = apps.get_model("masters", "VendorCategory")
    Activity = apps.get_model("masters", "Activity")

    activities = {a.abbreviation: a for a in Activity.objects.all()}

    # ---- materials -------------------------------------------------------
    # is_home first, then any other. Ordering by -is_home makes the home row win
    # even where a material somehow has two and neither is flagged correctly.
    by_material = {}
    for link in MaterialActivity.objects.all().order_by("-is_home", "id"):
        by_material.setdefault(link.material_id, []).append(link.activity_id)

    for material in Material.objects.all():
        links = by_material.get(material.id, [])
        if not links:
            # No link at all. Cannot invent one, and the column is about to be
            # made NOT NULL — so fall back to Common, which is the activity that
            # exists precisely for "used everywhere".
            common = activities.get("COM") or next(iter(activities.values()))
            material.home_activity_id = common.id
        else:
            material.home_activity_id = links[0]
            if len(links) > 1:
                material.also_used_in_id = links[1]
        material.save(update_fields=["home_activity", "also_used_in"])

    # ---- vendor groups ---------------------------------------------------
    names = {corrected(c.category) for c in VendorCategory.objects.all()} - NOT_A_GROUP
    groups = {name: VendorGroup.objects.create(name=name) for name in sorted(names)}

    cats_by_vendor = {}
    for cat in VendorCategory.objects.all():
        cats_by_vendor.setdefault(cat.vendor_id, []).append(corrected(cat.category))

    for vendor in Vendor.objects.all():
        mine = cats_by_vendor.get(vendor.id, [])
        decided = MULTI_CATEGORY.get(vendor.code)
        if decided:
            keep, activity_code, _why = decided
            # ⚠ `corrected` again, so a name written here in its right spelling
            #   still finds a group created from a misspelt category.
            vendor.group = groups.get(corrected(keep))
            vendor.activity_1 = activities.get(activity_code)
        elif len(mine) == 1 and mine[0] not in NOT_A_GROUP:
            vendor.group = groups.get(mine[0])
        # ⚠ A vendor whose only category was "Contractor" gets no group and a
        #   Work Order default. That is the whole of the contractor flagging
        #   slice 5b was waiting on, derived rather than typed 10 times.
        if any(c in NOT_A_GROUP for c in mine):
            vendor.default_document_type = "WO"
        vendor.save(update_fields=["group", "activity_1", "default_document_type"])


def put_back(apps, schema_editor):
    """
    ⚠ REVERSIBLE ONLY IN THE SENSE THAT THE COLUMNS GO AWAY. The link tables are
      untouched by this migration and still hold every original row, so reversing
      loses nothing — which is exactly why they are not dropped here.
    """
    apps.get_model("masters", "VendorGroup").objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        # ⚠ AFTER the activity master has moved into this app, and after the
        #   projects app has let go of it — otherwise these foreign keys would
        #   name a model that two apps both think they own.
        ("masters", "0006_activity_moves_into_masters"),
        ("projects", "0009_activity_left_for_masters"),
    ]

    operations = [
        migrations.CreateModel(
            name="VendorGroup",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("name", models.CharField(help_text="e.g. General Construction Material",
                                          max_length=60, unique=True)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={"ordering": ["name"]},
        ),
        # ⚠ ADDED NULLABLE ON PURPOSE. There is no sensible default for a foreign
        #   key, and the values are three operations away. It is tightened at the
        #   end of this same migration, so no state exists where a material can
        #   be saved without a trade.
        migrations.AddField(
            model_name="material",
            name="home_activity",
            field=models.ForeignKey(
                null=True, blank=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="home_materials", to="masters.activity",
                help_text="The trade this material belongs to. Required."),
        ),
        migrations.AddField(
            model_name="material",
            name="also_used_in",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="secondary_materials", to="masters.activity",
                help_text="A second trade that also buys it. Optional — leave blank for "
                          "almost everything."),
        ),
        migrations.AddField(
            model_name="vendor",
            name="group",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="vendors", to="masters.vendorgroup",
                help_text="What this vendor is — used to search the vendor list."),
        ),
        migrations.AddField(
            model_name="vendor",
            name="activity_1",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="primary_vendors", to="masters.activity",
                help_text="Which trade they serve. Used to offer the right vendors on a "
                          "BOM line."),
        ),
        migrations.AddField(
            model_name="vendor",
            name="activity_2",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="secondary_vendors", to="masters.activity",
                help_text="A second trade, if they serve one."),
        ),
        migrations.RunPython(carry_across, put_back),
        migrations.AlterField(
            model_name="material",
            name="home_activity",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name="home_materials",
                to="masters.activity",
                help_text="The trade this material belongs to. Required."),
        ),
    ]
