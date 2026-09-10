"""
Django Admin for projects, the Activity master and estimates.

This is scaffolding, not the final UI — it exists so master data can be entered
and checked long before the real screens are built.
"""
from django.contrib import admin, messages
from django.db.models import Count

from .models import Activity, Estimate, EstimateLine, MaterialActivity, Project


@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    """
    THE ACTIVITY MASTER — the list every project picks its trades from.

    An activity must exist here before any project can use it. Nothing is ever
    created by import or typed onto a project.
    """
    list_display = ("sort_order", "abbreviation", "name", "rate", "gst_percent",
                    "material_count", "is_active")
    list_editable = ("name", "rate", "gst_percent", "is_active")
    list_display_links = ("abbreviation",)
    search_fields = ("abbreviation", "name")
    list_filter = ("is_active",)
    ordering = ("sort_order",)
    save_on_top = True
    fieldsets = (
        ("Identity", {
            "fields": ("abbreviation", "name", "sort_order"),
            "description": "The abbreviation becomes the first part of every material code under "
                           "this activity, e.g. PLM in PLM-PL3-014. Three capital letters, and it "
                           "must be unique.",
        }),
        ("BOQ", {
            "fields": ("rate", "gst_percent", "basis"),
            "description": "Rate is rupees per sqft of built-up area, EX-GST. It pre-fills a "
                           "project's estimate and becomes that activity's budget on the BOM.",
        }),
        ("Status", {
            "fields": ("is_active",),
            "description": "Switch off instead of deleting once materials or projects use it. "
                           "An inactive activity disappears from pickers but every existing "
                           "record still resolves.",
        }),
    )

    def get_queryset(self, request):
        # ⚠ home_materials, not material_links — the latter counts rows in the
        #   dead table, so an activity's material count stopped moving in slice 8.
        return super().get_queryset(request).annotate(_materials=Count("home_materials"))

    @admin.display(description="Materials", ordering="_materials")
    def material_count(self, obj):
        return obj._materials


# ⚠ `MaterialActivity` IS DELIBERATELY NOT REGISTERED SINCE SLICE 8.
#
#   A material's trade is now two columns on the material — `home_activity` and
#   `also_used_in` — edited on the material master screen. Saahil: "Material is
#   to be linked to activity in the same material master screen, not as a
#   separate tile."
#
#   Adding or changing a row here would now change nothing at all. An Admin page
#   that saves without effect is worse than no Admin page, and it is the silent
#   version of the two-places-disagreeing problem this slice spent the day
#   removing.
#
#   The table and its 705 rows are untouched, so the migration that copied them
#   onto the material still has something to be checked against. Dropping the
#   model is a later migration, once the seed commands and the importer stop
#   referencing it.


class EstimateLineInline(admin.TabularInline):
    model = EstimateLine
    extra = 0
    fields = ("sort_order", "name", "rate", "gst_percent", "basis", "is_custom")


@admin.register(Estimate)
class EstimateAdmin(admin.ModelAdmin):
    list_display = ("project", "composite_rate", "base_cost", "grand_total", "cost_per_sqft", "saved_at")
    inlines = [EstimateLineInline]
    readonly_fields = ("composite_rate", "base_cost", "contingency_amount", "design_fee_amount",
                       "cost_before_gst", "gst_amount", "grand_total", "cost_per_sqft")

    def has_change_permission(self, request, obj=None):
        """
        >>> ANCHOR: BOQ-LOCK <<<
        ⚠ A WON PROJECT'S BOQ CANNOT BE EDITED HERE EITHER. Saahil's rule was
          "no exceptions", and Admin is where an exception would otherwise live.

        The reserve is a live link to these rates, so an edit made quietly in
        Admin would move the budget the site team is measured against without
        anyone seeing it happen. If a rate genuinely has to change, the project
        goes back to Quoted first — which is a visible act on a visible field.
        """
        if obj is not None and not obj.is_editable:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        """Deleting the estimate would take the reserve with it. Same rule."""
        if obj is not None and not obj.is_editable:
            return False
        return super().has_delete_permission(request, obj)

    def save_formset(self, request, form, formset, change):
        """
        Save the estimate lines, then say what that did to the BOM.

        >>> ANCHOR: BOM-CALC-RESERVE <<<
        An activity's reserve is a LIVE LINK to its estimate line — rate × BUA,
        read fresh every time — so changing a rate here silently moves the
        number the site team is measured against. Saahil asked, back when the
        live link was agreed, that editing a saved BOQ warn about exactly that.
        This is that warning.

        It reports the figures, not a vague caution: the old reserve, the new
        one, and where the planned value now sits against it. A message saying
        "this may affect the BOM" would train people to ignore it.

        Only fires when the project actually HAS a BOM. Before that, an estimate
        is just an estimate and there is nothing downstream to disturb.

        ⚠ THE WARNING ITSELF LIVES IN bom_calc.reserve_changes(), not here.
        The BOQ screen needs the identical message, and two copies would say
        different things within a month. This reads the rates before saving,
        hands them over afterwards, and prints whatever comes back.
        """
        from . import bom_calc

        # Rates as they were, read before anything is written. Keyed on NAME,
        # because that is what the reserve matches on.
        before = {line.name: line.rate
                  for line in form.instance.lines.all().only("name", "rate")}

        super().save_formset(request, form, formset, change)

        project = form.instance.project
        changes = bom_calc.reserve_changes(project, before)
        for change_note in changes:
            messages.warning(request, "⚠ BOM budget changed — "
                                      + bom_calc.describe_reserve_change(change_note))
        if changes:
            messages.info(request, "Reserves are read live from this estimate, so the BOM screen "
                                   "already shows the new figures. Nothing needs regenerating.")

        for deleted in formset.deleted_objects:
            activity = Activity.objects.filter(name=deleted.name).first()
            if activity and bom.lines.filter(activity=activity).exists():
                messages.warning(
                    request,
                    f"⚠ {deleted.name} was removed from {project.code}'s estimate, but its BOM still "
                    f"has {bom.lines.filter(activity=activity).count()} line(s) under it. Their "
                    f"reserve is now ₹0, so every percentage against that activity reads as if there "
                    f"were no budget. The lines are deliberately still visible.")


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    """
    ⚠ Marking a project COMPLETED is how a finished job leaves the project list.

    It cannot be deleted once anything has been delivered — a goods receipt
    protects its purchase-order line, which protects the order, which protects
    the project. Completed is the answer to that: the record stays whole, the
    list stays short.
    """
    list_display = ("code", "name", "location", "bua_sqft", "floors", "status", "created_at")
    list_filter = ("status",)
    list_editable = ("status",)
    search_fields = ("code", "name", "location")
