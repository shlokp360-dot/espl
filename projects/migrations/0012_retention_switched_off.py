# Retention switched off on the customer's instruction, 11 Sep 2026.
#
# >>> ANCHOR: WO-TERMS <<< (a reference to the existing anchor)
# The field stays — approved bills already hold retention at 10% and their
# figures must never move — but no NEW work order carries retention unless
# somebody types it, and the input is gone from the screen, so nobody will.
#
# The data step clears the old 10% default ONLY on orders that have no
# approved RA bill: an order already billed keeps whatever it was billed at,
# because a bill approved in August must print the same figures in September.
from django.db import migrations, models
import django.core.validators


def clear_unbilled_defaults(apps, schema_editor):
    PurchaseOrder = apps.get_model("projects", "PurchaseOrder")
    RABill = apps.get_model("finance", "RABill")
    billed = set(RABill.objects.filter(status__in=["approved", "paid"])
                 .values_list("purchase_order_id", flat=True))
    (PurchaseOrder.objects.filter(retention_pct=10)
     .exclude(pk__in=billed)
     .update(retention_pct=0))


def nothing_to_undo(apps, schema_editor):
    """The 10% cannot be told apart from a typed 10% afterwards; leave it."""


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0011_work_order_terms"),
        ("finance", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="purchaseorder",
            name="retention_pct",
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                help_text="Held back from every RA bill, on the work value (ex-GST). "
                          "Switched off by default; kept for orders billed before 11 Sep 2026.",
                max_digits=5,
                validators=[django.core.validators.MinValueValidator(0)],
            ),
        ),
        migrations.RunPython(clear_unbilled_defaults, nothing_to_undo),
    ]
