"""
`{% load perms %}` — so a template can hide what a role cannot use.

    {% if user|can:"po.approve" %}<button>Approve</button>{% endif %}

⚠ HIDING IS NOT SECURITY, AND THIS FILTER IS NOT THE GATE. The view's
  @requires() is. This exists so that a Purchase manager is not shown an
  Approve button that answers with a 403 — a button that refuses you is worse
  than no button, because it looks like a fault in the system rather than a
  rule of the business.
"""
from django import template

from accounts import perms

register = template.Library()


@register.filter(name="can")
def can(user, key):
    return perms.can(user, key)
