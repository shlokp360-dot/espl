"""
Sales addresses. Reads are GET; every write is a POST to its own address.
"""
from django.urls import path

from sales import views

urlpatterns = [
    path("sales/", views.home, name="sales_home"),

    # ---- units ---------------------------------------------------------
    path("sales/units/", views.units, name="sales_units"),
    path("sales/units/new/", views.unit_form, name="sales_unit_new"),
    path("sales/units/<int:unit_id>/edit/", views.unit_form, name="sales_unit_form"),
    path("sales/units/bulk/", views.units_bulk, name="sales_units_bulk"),
    path("sales/units/<int:unit_id>/book/", views.booking_new, name="sales_booking_new"),

    # ---- enquiries -----------------------------------------------------
    path("sales/enquiries/", views.enquiries, name="sales_enquiries"),
    path("sales/enquiries/new/", views.enquiry_form, name="sales_enquiry_new"),
    path("sales/enquiries/<int:enquiry_id>/", views.enquiry_form, name="sales_enquiry_form"),
    path("sales/enquiries/<int:enquiry_id>/visit/", views.enquiry_visit, name="sales_enquiry_visit"),
    path("sales/enquiries/<int:enquiry_id>/stage/", views.enquiry_stage, name="sales_enquiry_stage"),

    # ---- bookings ------------------------------------------------------
    path("sales/bookings/", views.bookings, name="sales_bookings"),
    path("sales/bookings/<int:booking_id>/", views.booking, name="sales_booking"),
    path("sales/bookings/<int:booking_id>/schedule/", views.booking_schedule, name="sales_booking_schedule"),
    path("sales/bookings/<int:booking_id>/mark/", views.booking_mark, name="sales_booking_mark"),
    path("sales/bookings/<int:booking_id>/cancel/", views.booking_cancel, name="sales_booking_cancel"),
    path("sales/bookings/<int:booking_id>/transfer/", views.booking_transfer, name="sales_booking_transfer"),
    path("sales/customers/<int:customer_id>/", views.customer_form, name="sales_customer_form"),

    # ---- demands and receipts -------------------------------------------
    path("sales/bookings/<int:booking_id>/demand/", views.demand_new, name="sales_demand_new"),
    path("sales/demands/<int:demand_id>/pdf/", views.demand_pdf, name="sales_demand_pdf"),
    path("sales/demands/for-header/", views.demands_for_header, name="sales_demands_for_header"),
    path("sales/bookings/<int:booking_id>/receipt/", views.receipt_new, name="sales_receipt_new"),

    # ---- registers -----------------------------------------------------
    path("sales/collections/", views.collections, name="sales_collections"),
    path("sales/collections/excel/", views.collections_excel, name="sales_collections_excel"),
    path("sales/receipts/", views.receipts, name="sales_receipts"),
    path("sales/receipts/excel/", views.receipts_excel, name="sales_receipts_excel"),
]
