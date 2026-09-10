"""
Slice 5a, step 1 — the fields the purchase-order screen and the PDF need.

WHAT THIS ADDS AND WHY

  BomLine.planned_rate
      What THIS project plans to pay per unit. Blank keeps the old behaviour
      exactly — the material master's estimation rate. It exists because a
      material sold as a lump (signage, a security deposit) always has quantity
      1, so the AMOUNT is the thing that varies per project, and it was locked
      inside company-wide master data.

  Project.billing_address / site_address
      The invoice goes to the office, the material goes to the site. A document
      prints four blocks: FROM · TO · BILL TO · SHIP TO.
      ⚠ Addresses only. There is deliberately no billing GSTIN: confirmed with
        Saahil that one registration covers every project, so the tax split
        keeps comparing the vendor's state with the company's.

  PurchaseOrder.document_type
      PO or WO. One engine, two documents.

  PurchaseOrder.terms
      A COPY of CompanyProfile.po_terms / .wo_terms taken when the draft is
      created — never read live, so editing the company's standard terms cannot
      rewrite an order already sent.

  PurchaseOrder.deduction_pct / tds_pct / tds_section
      ⚠ deduction_pct applies AFTER GST and is not a discount — it must print
        as "Less: agreed deduction (post-tax)".
      ⚠ TDS is withheld from the PAYMENT, computed on the taxable value and
        never on the GST. It never reduces what the vendor invoices.

  PurchaseOrderLine.discount_pct / reference
      A percentage discount that reduces the taxable value, and up to 300
      characters of free text the vendor actually reads. The reference is NOT
      BomLine.remark — that one is internal and must never be printed.

  Two indexes
      For the discount and approved-order dashboards. Saahil asked for approved
      orders copied into a separate reporting table; they are already rows in
      this one, and a copy would be a second source of truth that drifts.

ALL ADDITIVE, and every default preserves today's behaviour: existing orders
become PO with zero discount, zero deduction and no TDS.
"""
import django.core.validators
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('masters', '0005_companyprofile_vendor_default_document_type'),
        ('projects', '0006_project_completed_status'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='bomline',
            name='planned_rate',
            field=models.DecimalField(blank=True, decimal_places=2, help_text="What this project plans to pay per unit. Blank uses the material master's estimation rate. For a Lumpsum material, quantity 1 and the amount here.", max_digits=12, null=True, validators=[django.core.validators.MinValueValidator(0)]),
        ),
        migrations.AddField(
            model_name='project',
            name='billing_address',
            field=models.TextField(blank=True, help_text="Where the vendor's invoice goes. Prints as BILL TO."),
        ),
        migrations.AddField(
            model_name='project',
            name='site_address',
            field=models.TextField(blank=True, help_text='Where material is delivered. Prints as SHIP TO, and pre-fills the delivery address on every order for this project.'),
        ),
        migrations.AddField(
            model_name='purchaseorder',
            name='deduction_pct',
            field=models.DecimalField(decimal_places=2, default=0, help_text='Agreed deduction on the whole bill, applied AFTER GST.', max_digits=5, validators=[django.core.validators.MinValueValidator(0)]),
        ),
        migrations.AddField(
            model_name='purchaseorder',
            name='delivery_address',
            field=models.TextField(blank=True, help_text="Pre-filled from the project's site address. Prints as SHIP TO."),
        ),
        migrations.AddField(
            model_name='purchaseorder',
            name='document_type',
            field=models.CharField(choices=[('PO', 'Purchase Order'), ('WO', 'Work Order')], default='PO', max_length=2),
        ),
        migrations.AddField(
            model_name='purchaseorder',
            name='required_by',
            field=models.DateField(blank=True, help_text='When the site needs it.', null=True),
        ),
        migrations.AddField(
            model_name='purchaseorder',
            name='tds_pct',
            field=models.DecimalField(decimal_places=2, default=0, help_text='Withheld from payment, computed on the taxable value. Leave 0 if not applicable.', max_digits=5, validators=[django.core.validators.MinValueValidator(0)]),
        ),
        migrations.AddField(
            model_name='purchaseorder',
            name='tds_section',
            field=models.CharField(blank=True, help_text='e.g. 194Q for goods, 194C for a contractor.', max_length=10),
        ),
        migrations.AddField(
            model_name='purchaseorder',
            name='terms',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='purchaseorderline',
            name='discount_pct',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=5, validators=[django.core.validators.MinValueValidator(0)]),
        ),
        migrations.AddField(
            model_name='purchaseorderline',
            name='reference',
            field=models.CharField(blank=True, max_length=300),
        ),
        migrations.AddIndex(
            model_name='purchaseorder',
            index=models.Index(fields=['status', 'approved_at'], name='projects_pu_status_984260_idx'),
        ),
        migrations.AddIndex(
            model_name='purchaseorder',
            index=models.Index(fields=['vendor', 'status'], name='projects_pu_vendor__c32244_idx'),
        ),
    ]
