"""
Who raised a document, who took delivery, and who paid it.

WHY NOW
    `approved_at` and `approved_by` have been a pair since slice 5a. The other
    two steps recorded a timestamp and nothing else, which answers "when" and
    not "who" — and the permission matrix hands approve, deliver and pay to
    three different roles on purpose. A purchase manager delivers; an accountant
    pays; neither approves. Recording only the clock throws away the half of
    that which somebody will actually ask about.

⚠ NOTHING IS BACKFILLED. Every existing document keeps three empty columns,
    because there is no honest way to guess who marked it delivered last month.
    A screen showing "delivered by —" is truthful; a screen showing the admin's
    name against work he never did is not.

⚠ THREE NULLABLE FOREIGN KEYS ON AN EXISTING TABLE — no defaults, no data
    rewrite. `sqlmigrate` shows three ALTER TABLE ADD COLUMN statements and
    nothing else.
"""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0009_activity_left_for_masters"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="purchaseorder",
            name="created_by",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="purchase_orders_raised", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="purchaseorder",
            name="delivered_by",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="purchase_orders_delivered", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="purchaseorder",
            name="paid_by",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="purchase_orders_paid", to=settings.AUTH_USER_MODEL),
        ),
    ]
