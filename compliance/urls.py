"""
Compliance addresses.

⚠ THE DOWNLOAD IS A VIEW, NOT A FILE PATH. `/compliance/document/12/` runs the
    permission check and then hands over the bytes; there is no address that
    reaches the media folder directly, and there must never be one.
"""
from django.urls import path

from compliance import views

urlpatterns = [
    path("compliance/", views.overview, name="compliance_home"),
    path("compliance/project/", views.project_screen, name="compliance_project_default"),
    path("compliance/project/<int:project_id>/", views.project_screen, name="compliance_project"),
    path("compliance/project/<int:project_id>/applies/", views.set_applicability,
         name="compliance_applies"),
    path("compliance/project/<int:project_id>/upload/<int:item_id>/", views.upload,
         name="compliance_upload"),
    # ⚠ ANCHOR: COMPLIANCE-PRUNING — one project dropping a line it does not need,
    #   and putting it back. POST-only, like every other write in this module.
    path("compliance/project/<int:project_id>/remove/<int:item_id>/", views.remove_item,
         name="compliance_remove_item"),
    path("compliance/project/<int:project_id>/restore/<int:item_id>/", views.restore_item,
         name="compliance_restore_item"),
    path("compliance/document/<int:document_id>/", views.download, name="compliance_download"),
    # The same bytes, opened in a tab. Same permission, same 404, still no MEDIA_URL.
    path("compliance/document/<int:document_id>/view/", views.view_inline, name="compliance_view"),
    path("compliance/document/<int:document_id>/correct/", views.correct, name="compliance_correct"),
    path("compliance/timeline/", views.timeline, name="compliance_timeline"),
    # The template every project is measured against.
    path("compliance/master/", views.master, name="compliance_master"),
    path("compliance/master/title/", views.master_title, name="compliance_master_title"),
    path("compliance/master/item/", views.master_item, name="compliance_master_item"),
    path("compliance/master/item/<int:item_id>/off/", views.master_deactivate,
         name="compliance_master_off"),
    path("compliance/master/type/", views.master_type, name="compliance_master_type"),
]
