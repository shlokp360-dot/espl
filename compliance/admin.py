"""
Compliance in Django Admin — the emergency exit, not the screen.

⚠ THE CHECKLIST MASTER IS A DESIGNED SCREEN and is where this is maintained.
  Admin is registered because a list view is the only way to see one value
  across every record, and because the checklist content is a first draft that
  somebody may need to correct in bulk.
"""
from django.contrib import admin

from compliance.models import (
    ComplianceDocument, ComplianceItem, ComplianceTitle, ComplianceType, ProjectCompliance,
)


class TitleInline(admin.TabularInline):
    model = ComplianceTitle
    extra = 0


@admin.register(ComplianceType)
class ComplianceTypeAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "applies_to_every_project", "is_active")
    inlines = [TitleInline]


@admin.register(ComplianceTitle)
class ComplianceTitleAdmin(admin.ModelAdmin):
    list_display = ("name", "type", "sort_order", "is_active")
    list_filter = ("type", "is_active")
    list_select_related = ("type",)


@admin.register(ComplianceItem)
class ComplianceItemAdmin(admin.ModelAdmin):
    list_display = ("name", "title", "kind", "is_compulsory", "is_active")
    list_filter = ("title__type", "kind", "is_compulsory", "is_active")
    search_fields = ("name",)
    list_select_related = ("title", "title__type")


@admin.register(ComplianceDocument)
class ComplianceDocumentAdmin(admin.ModelAdmin):
    # ⚠ NO DELETE ACTION. Nothing in this module is ever deleted; see the model.
    list_display = ("item", "project", "reference", "issued_on", "expires_on", "uploaded_at")
    list_filter = ("project", "item__title__type")
    list_select_related = ("item", "project", "uploaded_by")
    readonly_fields = ("uploaded_at", "size_bytes", "original_name")


@admin.register(ProjectCompliance)
class ProjectComplianceAdmin(admin.ModelAdmin):
    list_display = ("project", "type", "applicable", "decided_at")
    list_select_related = ("project", "type")
