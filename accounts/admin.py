"""
The role, visible in Admin as part of the user it belongs to.

⚠ AN INLINE, NOT A SEPARATE ENTRY. Slice 8 taught this the hard way: a link
  table registered on its own gave a second, worse route to the same data, and
  the one thing actually being read was not editable at all. A role belongs to
  a person, so it is edited on the person.

⚠ ADMIN IS NOT THE USERS SCREEN. The designed screen under Master data enforces
  the safeguards — no self-demotion, no last-Admin removal, no delete. Django
  Admin bypasses all of it, which is why it is Admin-only and why the Users
  screen exists at all.
"""
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from accounts.models import UserProfile


class ProfileInline(admin.StackedInline):
    model = UserProfile
    # ⚠ THE PROFILE POINTS AT A USER TWICE — `user` is whose role it is, and
    #   `created_by` is who set them up. Admin cannot guess which relation the
    #   inline is about and refuses to start until it is told (admin.E202).
    fk_name = "user"
    can_delete = False
    extra = 0
    fields = ("role", "must_change_password", "created_by", "created_at")
    readonly_fields = ("created_by", "created_at")
    verbose_name_plural = "Role"


class UserAdmin(DjangoUserAdmin):
    inlines = [ProfileInline]
    list_display = ("username", "email", "first_name", "role_of_user", "is_active", "last_login")
    list_filter = ("is_active", "profile__role", "is_superuser")

    @admin.display(description="Role", ordering="profile__role")
    def role_of_user(self, obj):
        profile = getattr(obj, "profile", None)
        return profile.get_role_display() if profile else "—"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("profile")


User = get_user_model()
admin.site.unregister(User)
admin.site.register(User, UserAdmin)
