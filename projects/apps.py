"""
App config.

NOTE ON WHERE THINGS APPEAR IN ADMIN
    Django groups the Admin home page strictly by app, so the ACTIVITY MASTER
    shows under this section rather than beside the other masters. It is master
    data all the same. The single "Master data" menu we designed belongs to the
    real UI, not to Admin.
"""
from django.apps import AppConfig


class ProjectsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "projects"
    verbose_name = "Projects, activities & estimates"
