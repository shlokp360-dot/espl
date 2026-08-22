"""
Adds the "unregistered supplier" tick to the Vendor Master, and creates the
LOCAL PURCHASE vendor.

WHY
    A purchase order cannot be approved without the vendor's GSTIN. That is
    right for a registered supplier and impossible for the hardware shop down
    the road, who has no GST number and never will. Without a way through,
    every cash and street purchase would simply stay off the system — which is
    the opposite of what it is for, because that spend still has to reach the
    budget and the analytics.

    So: one tick on the vendor, and one ready-made vendor to use it.

SAFE TO RUN
    Adds a column that defaults to False, so all 173 existing vendors are
    unchanged and still require a GSTIN. Then inserts one new vendor row.

⚠ THE PLACEHOLDER PHONE NUMBER
    A vendor's identity is their phone number — it is unique and it is how
    duplicates are avoided. LOCAL PURCHASE is not a person and has no phone, so
    it takes 0000000000. That is a placeholder, not a number to ring. It also
    means WhatsApp is left blank automatically, because the auto-fill only
    accepts a 10-digit mobile starting 6, 7, 8 or 9 — so nothing will ever try
    to send a purchase order to it.
"""
from django.db import migrations, models


LOCAL_CODE = "VEN-LOCAL"


def create_local_vendor(apps, schema_editor):
    Vendor = apps.get_model("masters", "Vendor")
    if Vendor.objects.filter(code=LOCAL_CODE).exists():
        return
    Vendor.objects.create(
        code=LOCAL_CODE,
        name="LOCAL PURCHASE (cash / street vendor)",
        phone="0000000000",          # placeholder — see the note above
        whatsapp_number="",
        gst_number="",
        is_unregistered=True,
        payment_terms="Cash",
        address="Not applicable — counter or street purchase",
    )


def remove_local_vendor(apps, schema_editor):
    """
    Only removes it if nothing has been bought through it. A vendor with
    purchase orders behind it is protected by the database anyway, which is the
    behaviour we want — a reversal must not be able to delete real history.
    """
    Vendor = apps.get_model("masters", "Vendor")
    Vendor.objects.filter(code=LOCAL_CODE, purchase_orders__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("masters", "0003_alter_material_uom"),
    ]

    operations = [
        migrations.AddField(
            model_name="vendor",
            name="is_unregistered",
            field=models.BooleanField(
                default=False,
                help_text="Tick for a local or street supplier with no GST registration. Their "
                          "purchase orders need no GSTIN and are raised at 0% GST.",
            ),
        ),
        migrations.RunPython(create_local_vendor, remove_local_vendor),
    ]
