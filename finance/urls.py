from django.urls import path

from finance import views

urlpatterns = [
    path("finance/", views.home, name="finance_home"),

    # ---- bills: one register for PO invoices and WO RA bills ---------------
    path("finance/bills/", views.bills, name="finance_bills"),
    path("finance/bills/excel/", views.bills_excel, name="finance_bills_excel"),
    path("finance/bills/new/", views.bill_pick, name="finance_bill_pick"),

    # ---- RA bills on work orders -----------------------------------------
    path("finance/ra-bills/", views.ra_bills, name="finance_ra_bills"),
    path("finance/ra-bills/excel/", views.ra_bills_excel, name="finance_ra_bills_excel"),
    path("finance/wo/<int:po_id>/", views.work_order, name="finance_wo"),
    path("finance/wo/<int:po_id>/ra-bill/new/", views.ra_bill_new, name="finance_ra_bill_new"),
    path("finance/ra-bills/<int:bill_id>/", views.ra_bill, name="finance_ra_bill"),
    path("finance/ra-bills/<int:bill_id>/save/", views.ra_bill_save, name="finance_ra_bill_save"),
    path("finance/ra-bills/<int:bill_id>/approve/", views.ra_bill_approve, name="finance_ra_bill_approve"),
    path("finance/ra-bills/<int:bill_id>/pay/", views.ra_bill_pay, name="finance_ra_bill_pay"),
    path("finance/ra-bills/<int:bill_id>/pdf/", views.ra_bill_pdf, name="finance_ra_bill_pdf"),
    path("finance/ra-bills/<int:bill_id>/discard/", views.ra_bill_discard, name="finance_ra_bill_discard"),

    # ---- retention: SWITCHED OFF (customer, 11 Sep 2026). No routes. --------

    # ---- vendor invoices and payments on purchase orders --------------------
    path("finance/po/<int:po_id>/", views.purchase_order, name="finance_po"),
    path("finance/po/<int:po_id>/invoice/", views.invoice_new, name="finance_invoice_new"),
    path("finance/po/<int:po_id>/pay/", views.po_pay, name="finance_po_pay"),

    # ---- the payments register ---------------------------------------------
    path("finance/payments/", views.payments, name="finance_payments"),
    path("finance/payments/excel/", views.payments_excel, name="finance_payments_excel"),

    # ---- the vendor ledger and the TDS report --------------------------------
    path("finance/ledger/", views.vendor_ledger, name="finance_vendor_ledger"),
    path("finance/ledger/excel/", views.vendor_ledger_excel, name="finance_vendor_ledger_excel"),
    path("finance/tds/", views.tds, name="finance_tds"),
    path("finance/tds/excel/", views.tds_excel, name="finance_tds_excel"),
]
