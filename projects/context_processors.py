"""
What every template needs from the hub: the module links in the top bar.

One list, filtered by the same permission each tile carries, so the bar can never
offer a module the launchpad would not. Two queries at most (the user's profile is
already joined); nothing here touches a per-project table.
"""
from accounts.models import role_of
from projects import hub


def modules(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"modules": []}
    path = request.path
    out = []
    for tile in hub.tiles_for(role_of(user)):
        if not tile["live"]:
            continue
        tile["on"] = path.startswith(tile["url"]) if tile["url"] != "/" else False
        # A tile whose strip holds a screen living elsewhere — the purchase
        # order register at /orders/ is the first tab of Finance & Accounting.
        if not tile["on"]:
            tile["on"] = any(path.startswith(url) for url in tile["also_urls"])
        out.append(tile)
    # Master data lives under /masters/ and Projects under /projects/; a
    # per-project screen (/projects/3/bom/) lights up Projects, as it should.
    return {"modules": out}
