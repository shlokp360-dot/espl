"""
Task management in Django Admin.

⚠ THIS IS THE EMERGENCY EXIT, NOT THE SCREEN. The board is where this work is
  done. Admin is registered for the same reason the master tables are: a list
  view is the only way to see one value across every record, and somebody will
  eventually need to fix a date on a site at eleven at night.
"""
from django.contrib import admin

from tasks.models import Subtask, TaskHeader


class SubtaskInline(admin.TabularInline):
    """Edited inside the header they belong to, never picked from a dropdown."""

    model = Subtask
    extra = 0
    fields = ("title", "assignee", "start", "days", "priority", "status",
              "finished_on", "delay_reason")


@admin.register(TaskHeader)
class TaskHeaderAdmin(admin.ModelAdmin):
    list_display = ("name", "project", "activity", "owner", "start", "days")
    list_filter = ("project", "activity")
    search_fields = ("name", "project__code", "project__name")
    # ⚠ Or this is one query per row for each of the four, on a screen that
    #   lists everything.
    list_select_related = ("project", "activity", "owner")
    inlines = [SubtaskInline]


