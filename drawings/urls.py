"""
Drawing addresses.

⚠ THE DOWNLOAD IS A VIEW, NOT A FILE PATH. `/drawings/file/12/` runs the
    permission check and then hands over the bytes; there is no address that
    reaches the media folder directly, and there must never be one.
"""
from django.urls import path

from drawings import views

urlpatterns = [
    path("drawings/", views.home, name="drawings_home"),
    path("drawings/project/", views.register, name="drawings_register_default"),
    path("drawings/project/<int:project_id>/", views.register, name="drawings_register"),
    path("drawings/project/<int:project_id>/new/", views.drawing_new, name="drawings_new"),
    path("drawings/project/<int:project_id>/bulk/", views.bulk, name="drawings_bulk"),
    path("drawings/project/<int:project_id>/drawing/<int:drawing_id>/", views.detail,
         name="drawings_detail"),
    path("drawings/project/<int:project_id>/drawing/<int:drawing_id>/edit/", views.drawing_edit,
         name="drawings_edit"),
    path("drawings/project/<int:project_id>/drawing/<int:drawing_id>/upload/", views.upload,
         name="drawings_upload"),
    path("drawings/project/<int:project_id>/revision/<int:revision_id>/approve/", views.approve,
         name="drawings_approve"),
    path("drawings/file/<int:revision_id>/", views.download, name="drawings_download"),
    # Masters.
    path("drawings/architects/", views.architects, name="drawings_architects"),
    path("drawings/architects/new/", views.architect_new, name="drawings_architect_new"),
    path("drawings/architects/<int:architect_id>/", views.architect_edit,
         name="drawings_architect_edit"),
    path("drawings/groups/", views.groups, name="drawings_groups"),
    path("drawings/groups/save/", views.groups_save, name="drawings_groups_save"),
]
