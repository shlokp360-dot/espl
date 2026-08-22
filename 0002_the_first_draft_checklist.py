"""
The AMC and RERA checklists — A FIRST DRAFT, AND LABELLED AS ONE ON SCREEN.

⚠⚠ THIS CONTENT IS NOT CONFIRMED AND MUST BE CHECKED BY WHOEVER DOES ELEGANCE
    SKYZ'S LIAISON WORK. Rajachitthi, plinth checking, BU permission and RERA
    Forms 1/2/3 were assembled from what is publicly known about Ahmedabad
    Municipal Corporation and Gujarat RERA. **Getting one wrong here is a
    compliance risk, not a bug** — it is in `OPEN-BEFORE-GO-LIVE.md` for that
    reason, and the screen says so above the list.

⚠ SEEDED AS DATA, NOT HARDCODED IN CODE. Every row can be renamed, reordered or
    deactivated from Admin and from the checklist master without a deployment,
    which is the whole point of it being a master rather than a constant.

⚠ REVERSIBLE, AND THE REVERSE DELETES NOTHING THAT HAS A DOCUMENT AGAINST IT.
    Rolling this back on a system somebody has already used would otherwise
    orphan real uploads.
"""
from django.db import migrations

AMC = [
    ("Land and title", [
        ("7/12 extract / Property card", "one", None),
        ("Sale deed / title document", "one", None),
        ("N.A. (non-agricultural) permission", "one", None),
        ("Title clearance certificate", "one", None),
    ]),
    ("Plan passing", [
        ("Rajachitthi (development permission)", "one", None),
        ("Approved building plans", "one", None),
        ("Layout / sub-plot approval", "one", None),
        ("Fire NOC — provisional", "valid", 365),
    ]),
    ("Before work starts", [
        ("Commencement certificate", "one", None),
        ("Plinth checking certificate", "one", None),
        ("Labour licence", "valid", 365),
        ("Contract labour registration", "valid", 365),
    ]),
    ("Utilities and services", [
        ("Torrent Power connection sanction", "one", None),
        ("Water and drainage connection permission", "one", None),
        ("Borewell permission", "valid", 1095),
    ]),
    ("Environment and safety", [
        ("Consent to Establish (GPCB)", "valid", 1825),
        ("Construction and demolition waste plan", "one", None),
        ("Site safety declaration", "valid", 365),
    ]),
    ("On completion", [
        ("Fire NOC — final", "one", None),
        ("Building Use (BU) permission", "one", None),
        ("Completion certificate", "one", None),
    ]),
]

RERA = [
    ("Registration", [
        ("RERA registration certificate", "one", None),
        ("Registration extension order", "valid", 365),
        ("Promoter declaration (Form B)", "one", None),
    ]),
    ("Quarterly filings", [
        # ⚠ The three that made `REPEAT` necessary. Without that kind they would
        #   read "Held" forever after one upload — see compliance/models.py.
        ("Form 1 — architect's certificate", "repeat", None),
        ("Form 2 — engineer's certificate", "repeat", None),
        ("Form 3 — chartered accountant's certificate", "repeat", None),
        ("Quarterly progress update on the portal", "repeat", None),
    ]),
    ("Accounts", [
        ("Designated 70% account details", "one", None),
        ("Annual audit report (Form 5)", "valid", 365),
    ]),
    ("Agreements", [
        ("Allotment letter format", "one", None),
        ("Agreement for sale format", "one", None),
    ]),
]


def seed(apps, schema_editor):
    Type = apps.get_model("compliance", "ComplianceType")
    Title = apps.get_model("compliance", "ComplianceTitle")
    Item = apps.get_model("compliance", "ComplianceItem")

    for order, (code, name, every, note, content) in enumerate([
        ("AMC", "Ahmedabad Municipal Corporation", True,
         "Compulsory on every project.", AMC),
        ("RERA", "Gujarat RERA", False,
         "Ticked per project — private projects above the threshold.", RERA),
    ]):
        type = Type.objects.create(code=code, name=name, applies_to_every_project=every,
                                   note=note, sort_order=order)
        for title_order, (title_name, items) in enumerate(content):
            title = Title.objects.create(type=type, name=title_name, sort_order=title_order)
            for item_order, (item_name, kind, validity) in enumerate(items):
                Item.objects.create(title=title, name=item_name, kind=kind,
                                    validity_days=validity, sort_order=item_order)


def unseed(apps, schema_editor):
    """⚠ Leaves behind anything a real document has been filed against."""
    Type = apps.get_model("compliance", "ComplianceType")
    Item = apps.get_model("compliance", "ComplianceItem")
    Document = apps.get_model("compliance", "ComplianceDocument")

    used = set(Document.objects.values_list("item_id", flat=True))
    Item.objects.exclude(pk__in=used).delete()
    for type in Type.objects.filter(code__in=["AMC", "RERA"]):
        if not Item.objects.filter(title__type=type).exists():
            type.titles.all().delete()
            type.delete()


class Migration(migrations.Migration):

    dependencies = [("compliance", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
