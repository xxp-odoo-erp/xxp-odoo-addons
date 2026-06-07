# Copyright (C) 2025 XXP
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

{
    "name": "CDEK Delivery",
    "summary": "Send shipping through CDEK and track them online",
    "category": "Inventory/Delivery",
    "author": "XXP, Maxim Shurupov",
    "website": "https://xxp-odoo.com",
    "version": "16.0.2.0.0",
    "license": "LGPL-3",
    "images": ["static/description/banner.png"],
    "depends": [
        "delivery",
    ],
    "external_dependencies": {
        "python": ["cdek"],
    },
    "demo": [
        "demo/res_partner_demo.xml",
        "demo/stock_package_type_demo.xml",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/sale_order_cdek_service_views.xml",
        "data/product_product_data.xml",
        "data/delivery_carrier_data.xml",
        "views/cdek_tariff_views.xml",
        "views/stock_picking_views.xml",
        "views/delivery_carrier_views.xml",
        "views/res_partner_views.xml",
        "views/product_views.xml",
        "wizard/choose_delivery_carrier_views.xml",
        "views/sale_menus.xml",
        "views/sale_order_views.xml",
        "wizard/search_cdek_office_views.xml",
    ],
}
