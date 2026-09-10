"""
The site's address book.

  /login/   the front door — the ONE address a stranger may open
  /tasks/   the work board — who is doing what on a site, and by when
  /         the real screens: projects, and the BOM for one of them

>>> ANCHOR: NO-DJANGO-ADMIN <<<
⚠⚠ THERE IS NO /admin/. IT WAS REMOVED, AND IT MUST NOT COME BACK.
   Saahil, after seeing a raw Django screen during a walkthrough: "I don't want
   the admin or any other user to ever access the Django screens. Everything
   has to be interfaced with the UI that we have decided."

   He is right, and the reason is not tidiness. Django Admin walks past every
   rule this application exists to enforce — the activity rename that would
   silently zero a budget, the BOQ that locks at Won, the delete that is refused
   while something references it, the permission matrix, the vendor rate that
   may only be captured from an approved order. A screen that can edit any table
   directly makes all of those advisory.

⚠ NOTHING WAS LOST BY REMOVING IT, AND THAT WAS CHECKED RATHER THAN ASSUMED.
   Every model registered in an admin.py has its own screen: activities,
   materials, material groups, units, vendors, vendor groups, vendor rates,
   projects, estimates, task headers, users and all four compliance models. The
   old comment here claimed Admin was "still the only place some master tables
   are edited" — that was true once and stopped being true when the master data
   screens were built; the last gap closed when Material groups got its name
   field back.

⚠ THE REAL EMERGENCY EXIT IS `manage.py shell` ON THE SERVER, which needs
  server access rather than a browser and a superuser flag. That is the right
  shape for a break-glass tool: available to whoever administers the machine,
  not to anybody who happens to be signed in.

⚠ ACCOUNTS IS MOUNTED BEFORE PROJECTS. Its Users screen lives at
  /masters/users/, which sits inside the same /masters/ family as materials and
  vendors — the address matches where the screen appears on the Master data
  page, rather than where its code happens to live.
"""
from django.urls import include, path

urlpatterns = [
    path("", include("accounts.urls")),
    path("", include("tasks.urls")),
    path("", include("analytics.urls")),
    path("", include("compliance.urls")),
    path("", include("projects.urls")),
]
