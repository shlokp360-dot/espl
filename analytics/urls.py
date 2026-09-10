"""
Analytics addresses.

⚠ EVERY PAGE IS A GET WITH ITS FILTERS IN THE QUERY STRING — `?month=2026-07`,
    `?project=3`, `?type=WO`. So a page can be bookmarked, sent to the CA, and
    reloaded to exactly the same figures. A filter held in the session instead
    would mean two people looking at "the same screen" and seeing different
    money, which is the one thing a reporting module must never do.
"""
from django.urls import path

from analytics import views

urlpatterns = [
    # ⚠ THE TABS MIRROR THE LAUNCHPAD TILES, on Saahil's instruction: an
    #   overview across everything, and then the same tiles a business head
    #   already knows — the estimate, the buying, the money, the work.
    path("analytics/", views.overview, name="analytics_home"),
    path("analytics/g2n/", views.g2n, name="analytics_g2n"),
    path("analytics/budget/", views.budget_page, name="analytics_budget"),
    path("analytics/bom/", views.bom_page, name="analytics_bom"),
    path("analytics/payments/", views.settlement, name="analytics_payments"),
    path("analytics/tasks/", views.tasks_page, name="analytics_tasks"),
    # ⚠ The drill target. Every clickable figure in the module lands here.
    path("analytics/documents/", views.documents, name="analytics_documents"),
    # The four later tabs — forecast, rates, vendors, and the sales desk's speed.
    path("analytics/cost-to-complete/", views.cost_to_complete, name="analytics_cost_to_complete"),
    path("analytics/rates/", views.rates_page, name="analytics_rates"),
    path("analytics/vendors/", views.vendors_page, name="analytics_vendors"),
    # ⚠ Open to sales.view as well — the only analytics page that is.
    path("analytics/sales/", views.sales_page, name="analytics_sales"),
]
