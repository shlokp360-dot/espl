"""
Slice 5a, step 1 — the company we issue documents as, and what kind of document
each vendor gets.

CompanyProfile
    Until now there was nowhere to record our own name, address or GSTIN, so a
    purchase order could only have printed them by hard-coding the client's
    details into a template. One row, pinned to pk=1 in save().

    ⚠ Our GSTIN is not decoration: its first two digits are half of the
      CGST+SGST vs IGST decision, the vendor's GSTIN being the other half.

Vendor.default_document_type
    Who we order FROM decides what document comes out — a supplier gets a
    purchase order, a labour contractor gets a work order. Defaults to PO, so
    all 173 existing vendors keep behaving exactly as they do today.

ALL ADDITIVE. Nothing is dropped, renamed or rewritten.
"""
import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('masters', '0004_vendor_is_unregistered'),
    ]

    operations = [
        migrations.CreateModel(
            name='CompanyProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(default='Elegance Skyz Pvt. Ltd.', max_length=200)),
                ('address', models.TextField(blank=True)),
                ('gst_number', models.CharField(blank=True, help_text='Ours. The first two digits decide CGST+SGST vs IGST.', max_length=15, validators=[django.core.validators.RegexValidator('^$|^\\d{2}[A-Z]{5}\\d{4}[A-Z]{1}[A-Z\\d]{1}[Z]{1}[A-Z\\d]{1}$', 'A GSTIN is 15 characters, e.g. 24ABCDE1234F1Z5.')])),
                ('state', models.CharField(blank=True, help_text='Derived from our GSTIN.', max_length=60)),
                ('email', models.EmailField(blank=True, max_length=254)),
                ('phone', models.CharField(blank=True, max_length=15, validators=[django.core.validators.RegexValidator('^\\d*$', 'Digits only — no spaces, plus signs or dashes.')])),
                ('logo', models.FileField(blank=True, null=True, upload_to='company/')),
                ('po_terms', models.TextField(blank=True, default='1. This order number must appear on your invoice, delivery challan and e-way bill.\n2. Material to be supplied as per the description, specification and quantity above. Goods rejected at site are to be lifted by the supplier at their own cost.\n3. Payment as per the terms above, against a valid GST invoice and signed delivery challan.', help_text='Printed on purchase orders. Copied onto each order when it is created.')),
                ('wo_terms', models.TextField(blank=True, default='1. This order number must appear on your invoice and every running bill.\n2. Work to be carried out as per the scope above, including labour, tools and site cleaning unless stated otherwise.\n3. Payment against certified work, as per the terms above.', help_text='Printed on work orders. Copied onto each order when it is created.')),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'company profile',
                'verbose_name_plural': 'company profile',
            },
        ),
        migrations.AddField(
            model_name='vendor',
            name='default_document_type',
            field=models.CharField(choices=[('PO', 'Purchase Order'), ('WO', 'Work Order')], default='PO', help_text='Work Order for labour contractors, Purchase Order for suppliers. Can be switched per order on the preview.', max_length=2),
        ),
    ]
