"""
Every address the screens live at.

WHAT THIS FILE IS FOR
    Mapping a URL to a view, and giving each one a NAME. Templates link by name
    — {% url 'bom_screen' project.id %} — so an address can change here without
    hunting through the HTML for it.

WHY THE ACTIONS ARE POST-ONLY
    Saving, adding, removing and posting purchase orders all change something.
    A GET must never do that: browsers, link previews and back buttons re-fetch
    GET addresses freely, and a "delete" that works by being visited will
    eventually be visited by accident.
"""
from django.urls import path

from . import master_tabs, master_views, views

urlpatterns = [
    # ⚠ THE LAUNCHPAD TOOK "/" AND THE PROJECT LIST MOVED TO "/projects/".
    #   A home screen reachable only from a header link is one nobody opens, so
    #   it has to be what the bare address gives you. Both names still exist, so
    #   every {% url 'project_list' %} in the templates kept working untouched.
    path("", views.launchpad, name="launchpad"),
    path("projects/", views.project_list, name="project_list"),
    # The second level behind the Master data tile.
    path("masters/", views.master_data, name="master_data"),
    # ---------------------------------------------------------------------
    # The master data screens themselves. Materials and vendors stopped being
    # Admin links in slice 8; the rest of the tables are still Admin, because a
    # designed screen has to earn its place and those are edited twice a year.
    path("masters/materials/", master_views.material_list, name="material_list"),
    path("masters/materials/new/", master_views.material_form, name="material_new"),
    path("masters/materials/<int:material_id>/", master_views.material_form, name="material_edit"),
    path("masters/vendors/", master_views.vendor_list, name="vendor_list"),
    path("masters/vendors/new/", master_views.vendor_form, name="vendor_new"),
    path("masters/vendors/<int:vendor_id>/", master_views.vendor_form, name="vendor_edit"),
    # The Excel round trip. POST-only both ways: a download is cheap but it is
    # still an action, and an upload changes master data every BOQ is built on.
    path("masters/materials/export/", master_views.material_export, name="material_export"),
    path("masters/materials/template/", master_views.material_template, name="material_template"),
    path("masters/materials/import/", master_views.material_import, name="material_import"),
    path("masters/vendors/export/", master_views.vendor_export, name="vendor_export"),
    path("masters/vendors/template/", master_views.vendor_template, name="vendor_template"),
    path("masters/vendors/import/", master_views.vendor_import, name="vendor_import"),

    # ⚠ ANCHOR: INFO-PANELS — the Gujarati on the ⓘ panels. Admin only.
    path("masters/instructions/", master_tabs.panel_text, name="panel_text"),
    path("masters/instructions/<str:key>/save/", master_tabs.panel_text_save,
         name="panel_text_save"),

    # >>> ANCHOR: MASTER-TABS <<< the five entries behind the Master data tile.
    #   Nothing here opens Django Admin any more.
    path("masters/materials-home/", master_tabs.materials_home, name="materials_home"),
    path("masters/vendors-home/", master_tabs.vendors_home, name="vendors_home"),
    path("masters/material-groups/", master_tabs.material_group_list, name="material_group_list"),
    path("masters/material-groups/save/", master_tabs.material_group_save,
         name="material_group_save"),
    path("masters/vendor-groups/", master_tabs.vendor_group_list, name="vendor_group_list"),
    path("masters/vendor-groups/save/", master_tabs.vendor_group_save, name="vendor_group_save"),
    path("masters/units/", master_tabs.uom_list, name="uom_list"),
    path("masters/units/save/", master_tabs.uom_save, name="uom_save"),
    path("masters/vendor-rates/", master_tabs.vendor_rate_list, name="vendor_rate_list"),
    path("masters/activities/", master_tabs.activity_master, name="activity_master"),
    path("masters/activities/save/", master_tabs.activity_master_save,
         name="activity_master_save"),
    # Us. One row, and it prints at the top of every document.
    path("company/", views.company_profile, name="company_profile"),
    # The company's ₹/sqft per activity — what a new BOQ starts from.
    path("company/rates/", views.rate_defaults, name="rate_defaults"),
    # Creating and editing a project. One screen does both; the code is never typed.
    path("projects/new/", views.project_form, name="project_new"),
    path("projects/<int:project_id>/edit/", views.project_form, name="project_edit"),
    # Draft → Quoted → Won, from the BOQ screen, because that is the estimate
    # Won locks. POST-only: it is a change, and a change must never be a GET.
    path("projects/<int:project_id>/status/", views.project_status, name="project_status"),
    # The BOQ — step 2 of the process, and the source of every activity reserve.
    path("projects/<int:project_id>/boq/", views.boq_screen, name="boq_screen"),
    path("projects/<int:project_id>/boq/save/", views.boq_save, name="boq_save"),
    # >>> ANCHOR: BOQ-PDF <<<
    # Quoted onwards only — a Draft is refused with a reason. See views.boq_pdf.
    path("projects/<int:project_id>/boq/pdf/", views.boq_pdf, name="boq_pdf"),
    path("projects/<int:project_id>/boq/add/", views.boq_add_activity, name="boq_add_activity"),
    path("projects/<int:project_id>/boq/remove/<int:line_id>/",
         views.boq_remove_activity, name="boq_remove_activity"),
    path("projects/<int:project_id>/bom/", views.bom_screen, name="bom_screen"),
    path("projects/<int:project_id>/bom/create/", views.bom_generate, name="bom_generate"),
    path("projects/<int:project_id>/bom/save/", views.bom_save, name="bom_save"),
    path("projects/<int:project_id>/bom/add/", views.bom_add_lines, name="bom_add_lines"),
    path("projects/<int:project_id>/bom/remove/<int:line_id>/", views.bom_remove_line, name="bom_remove_line"),
    path("projects/<int:project_id>/bom/post-pos/", views.bom_post_pos, name="bom_post_pos"),
    # The purchase-order screen. Vendors first, then that vendor's documents —
    # level 3, the document itself, arrives in the next step.
    # >>> ANCHOR: BOM-STOCK-ONLY <<< the site engineer's screen, not the BOM.
    path("projects/<int:project_id>/stock/", views.stock_screen, name="stock_screen"),
    path("projects/<int:project_id>/stock/save/", views.stock_save, name="stock_save"),
    path("projects/<int:project_id>/orders/", views.po_screen, name="po_screen"),
    path("projects/<int:project_id>/orders/vendor/<int:vendor_id>/",
         views.po_vendor, name="po_vendor"),
    path("projects/<int:project_id>/orders/<int:po_id>/", views.po_detail, name="po_detail"),
    path("projects/<int:project_id>/orders/<int:po_id>/save/", views.po_save, name="po_save"),
    # ⚠ Approved onwards only — the view refuses a draft rather than rendering one.
    path("projects/<int:project_id>/orders/<int:po_id>/pdf/", views.po_pdf, name="po_pdf"),
    path("projects/<int:project_id>/orders/<int:po_id>/advance/", views.po_advance, name="po_advance"),
    path("projects/<int:project_id>/orders/<int:po_id>/line/<int:line_id>/remove/",
         views.po_line_remove, name="po_line_remove"),
    path("projects/<int:project_id>/po/preview/", views.po_preview, name="po_preview"),
    path("projects/<int:project_id>/po/create/", views.po_create, name="po_create"),
    path("projects/<int:project_id>/po/<int:po_id>/discard/",
         views.po_discard_confirm, name="po_discard_confirm"),
    path("projects/<int:project_id>/po/<int:po_id>/discard/do/",
         views.po_discard, name="po_discard"),

    # ---------------------------------------------------------------------
    # The cross-project document register — the Purchase orders tile.
    #
    # ⚠ NOT UNDER /projects/<id>/. That is the point of it: one address that
    #   shows every document on every project, so nobody has to travel through
    #   a project to look something up. The per-project screens above are
    #   untouched, and creation still happens only from the BOM.
    path("orders/", views.po_register, name="po_register"),
    path("orders/export/", views.po_register_excel, name="po_register_excel"),
    path("orders/pdfs/", views.po_register_zip, name="po_register_zip"),
    path("orders/advance/", views.po_register_advance, name="po_register_advance"),
]
