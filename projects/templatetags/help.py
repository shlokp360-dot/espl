"""
Rendering an ⓘ panel from `help_panels.PANELS`.

>>> ANCHOR: INFO-PANELS <<<
⚠ FORMATTING ONLY, the same rule as `inr.py`. Nothing here decides what a panel
  SAYS; it turns the data into the markup every screen shares.

⚠ `[[Order Qty]]` BECOMES BOLD AND NOTHING ELSE DOES. The syntax is named for
  what bold is allowed to mean — a button or a field you can point at on the
  screen — so emphasis cannot creep in by habit. Everything outside the brackets
  is escaped, so a panel can safely mention "Shah & Co" or a percentage.
"""
import re

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

from accounts.perms import can
from masters.models import PanelTranslation
from projects.help_panels import PANELS

register = template.Library()

_CONTROL = re.compile(r"\[\[(.+?)\]\]")


def render_text(text):
    """Escape everything, then bold the named controls. In that order."""
    out = escape(text)
    # ⚠ AFTER escaping, so a control named "Basic & GST" cannot inject markup.
    #   The brackets survive escaping untouched, which is why this works.
    return mark_safe(_CONTROL.sub(r"<b>\1</b>", out))


@register.inclusion_tag("_infopanel.html", takes_context=True)
def infopanel(context, key):
    """
    The panel for one screen, for the person reading it.

    ⚠ AN UNKNOWN KEY RENDERS NOTHING RATHER THAN RAISING. A typo in a template
      must not take a working screen down with it — but the test suite asserts
      every key used in a template exists, so the typo is caught before anybody
      sees the missing button.

    ⚠⚠ A STEP WHOSE ACTION THE READER CANNOT PERFORM IS NOT SHOWN. The tile rule
       and the tab rule, applied to instructions: telling a site engineer to
       press [[Add milestone]] is a 403 written as advice. `takes_context` is
       here only for that — the panel needs to know who is reading it.
    """
    panel = PANELS.get(key)
    if not panel:
        return {"panel": None}

    user = context.get("user")
    allowed = [entry for entry in panel["steps"]
               if not entry.get("perm") or can(user, entry["perm"])]

    # ⚠⚠ ONE QUERY PER SCREEN, AND THAT COST WAS MEASURED BEFORE IT WAS ADDED.
    #    Six rows on an indexed pair, about a millisecond. The BOM already runs
    #    30 queries and 1.2 seconds; the launchpad runs 2 and 10ms. Neither
    #    notices. No cache, deliberately: a cache here would be a rule somebody
    #    has to remember to invalidate, in a company with no IT team.
    #
    # ⚠ AN OVERLAY. A row exists only where somebody has written a translation,
    #   so an untouched install does no work beyond the empty lookup.
    written = dict(PanelTranslation.objects
                   .filter(panel_key=key)
                   .values_list("step_label", "gujarati"))

    steps = [dict(entry, html=render_text(entry["text"]),
                  gu_html=render_text(written.get(entry["label"]) or entry.get("gu") or ""))
             for entry in allowed]
    for entry, rendered in zip(allowed, steps):
        rendered["gu"] = written.get(entry["label"]) or entry.get("gu") or ""
    return {
        "panel": panel,
        "key": key,
        "steps": steps,
        # ⚠ THE TOGGLE APPEARS ONLY WHEN THERE IS SOMETHING TO TOGGLE TO. The
        #   Gujarati is written by Claude and checked by their own people before
        #   it ships; a language button that shows blank steps is worse than no
        #   button at all.
        # ⚠ AGAINST WHAT IS SHOWN, not the whole panel: a reader whose steps
        #   are all translated gets the toggle even if a hidden one is not.
        "bilingual": bool(steps) and all(entry["gu"] for entry in steps),
    }


@register.simple_tag
def infobutton(key):
    """The ⓘ in the header, wired to the panel below it."""
    if key not in PANELS:
        return ""
    return mark_safe(
        f'<button class="infobtn" type="button" title="How to use this screen" '
        f'onclick="document.getElementById(\'info-{escape(key)}\').showModal()">i</button>')
